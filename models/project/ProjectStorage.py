"""Disk format: immutable assets and an atomically replaced manifest.

Unreferenced assets are retained so a failed save never damages the last one.
Only JSON and NumPy arrays without pickle are read from project files.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

import numpy as np

from importers.CsvImporter import CsvImporter
from models.CornerPointGrid import CornerPointGrid
from models.DataCube import DataCube
from models.LayeredCube import LayeredCube
from models.PointCloud import PointCloud
from models.Surface import Surface
from models.WellFile import WellFile
from models.project.TableStorage import TableStorage


class ProjectFormatError(ValueError):
    pass


class ProjectStorage:
    VERSION = 3

    @staticmethod
    def read_manifest(path):
        with Path(path).open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ProjectFormatError("Файл проекта должен содержать JSON-объект.")
        version = data.get("version", 2)
        if type(version) is not int or version not in (2, ProjectStorage.VERSION):
            raise ProjectFormatError(f"Неподдерживаемая версия проекта: {version}")
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ProjectFormatError("В проекте не указано имя.")
        if not isinstance(data.get("tree"), dict):
            raise ProjectFormatError("В проекте отсутствует дерево объектов.")
        return data

    @staticmethod
    def asset_path(directory, relative_path):
        if not isinstance(relative_path, str) or not relative_path:
            raise ProjectFormatError("Не указан путь к данным объекта.")
        directory = Path(directory).resolve()
        relative = Path(relative_path)
        target = (directory / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(directory):
            raise ProjectFormatError("Путь к данным выходит за пределы проекта.")
        return target

    @staticmethod
    def _write_atomic(path, content):
        path = Path(path)
        descriptor, temporary = tempfile.mkstemp(prefix=".saving-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @classmethod
    def _store_asset(cls, directory, category, suffix, content):
        relative = Path(category) / (hashlib.sha256(content).hexdigest() + suffix)
        target = directory / relative
        if not target.exists() or target.read_bytes() != content:
            cls._write_atomic(target, content)
        return relative.as_posix()

    @classmethod
    def save(cls, project, directory, saved_at):
        directory = Path(directory).resolve()
        for name in ("source", "work", "cache"):
            (directory / name).mkdir(parents=True, exist_ok=True)
        manifest = project._serialize()
        manifest["last_saved"] = saved_at
        source_paths = {}
        objects = {obj.uuid: obj for obj in project.walk()}

        def store_node(node):
            obj = objects[node["uuid"]]
            if isinstance(obj, (WellFile, LayeredCube)):
                obj.validate()
            if isinstance(obj, DataCube) and obj.is_corner_point:
                obj.validate()
                grid = obj.corner_grid
                buffer = io.BytesIO()
                arrays = {"coord": np.asarray(grid.coord, dtype=np.float64),
                          "zcorn": np.asarray(grid.zcorn, dtype=np.float64),
                          "actnum": np.asarray(grid.actnum, dtype=np.uint8)}
                if grid.explicit_corners is not None:
                    arrays["explicit_corners"] = np.asarray(grid.explicit_corners, dtype=np.float64)
                arrays.update({f"property_{index}": np.asarray(values, dtype=np.float64)
                               for index, values in enumerate(grid.properties.values())})
                np.savez_compressed(buffer, **arrays)
                node["data_file"] = cls._store_asset(directory, "work", ".corner.npz", buffer.getvalue())
            elif isinstance(obj, PointCloud):
                obj.validate()
                content = TableStorage.dumps(obj.dataframe)
                node["data_file"] = cls._store_asset(directory, "work", ".table.npz", content)
            elif isinstance(obj, Surface):
                obj.validate()
                buffer = io.BytesIO()
                np.savez_compressed(buffer, vertices=np.asarray(obj.vertices, dtype=float),
                                    faces=np.asarray(obj.faces, dtype=np.int64),
                                    normals=np.asarray(obj.normals, dtype=float))
                node["data_file"] = cls._store_asset(directory, "work", ".surface.npz", buffer.getvalue())
            if isinstance(obj, (PointCloud, Surface)):
                source = Path(obj.file_path) if obj.file_path else None
                node["file_path"] = None
                if source is not None and source.is_file():
                    node["file_path"] = cls._store_asset(
                        directory, "source", source.suffix.lower(), source.read_bytes()
                    )
                source_paths[obj.uuid] = node["file_path"]
            for child in node.get("children", []):
                store_node(child)

        store_node(manifest["tree"])
        content = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        cls._write_atomic(directory / "project.json", content)
        return source_paths

    @classmethod
    def load_assets(cls, project, manifest):
        legacy = manifest.get("version", 2) == 2

        def load_node(obj, node):
            if isinstance(obj, (PointCloud, Surface)):
                source = node.get("file_path")
                if source:
                    if legacy:
                        source = Path(source)
                        if not source.is_absolute():
                            source = project.project_path / source
                    else:
                        source = cls.asset_path(project.project_path, source)
                    obj.file_path = str(source)
                if not legacy:
                    path = cls.asset_path(project.project_path, node.get("data_file"))
                    if isinstance(obj, DataCube) and obj.is_corner_point:
                        names = node.get("grid_property_names")
                        dimensions = node.get("grid_dimensions")
                        if (not isinstance(names, list) or any(not isinstance(name, str) for name in names)
                                or len(set(names)) != len(names)
                                or not isinstance(dimensions, list) or len(dimensions) != 3):
                            raise ProjectFormatError("Некорректные метаданные corner-point grid.")
                        with np.load(path, allow_pickle=False) as arrays:
                            properties = {name: arrays[f"property_{index}"]
                                          for index, name in enumerate(names)}
                            grid = CornerPointGrid(tuple(dimensions), arrays["coord"],
                                                   arrays["zcorn"], arrays["actnum"].astype(bool),
                                                   properties,
                                                   arrays["explicit_corners"] if "explicit_corners" in arrays else None)
                        obj.set_corner_grid(grid)
                    elif isinstance(obj, PointCloud):
                        obj.dataframe = TableStorage.load(path)
                    else:
                        with np.load(path, allow_pickle=False) as arrays:
                            obj.vertices = arrays["vertices"]
                            obj.faces = arrays["faces"]
                            obj.normals = arrays["normals"]
                else:
                    cls._load_legacy_object(obj)
                if isinstance(obj, PointCloud):
                    obj.validate()
                    if node.get("point_count", obj.point_count) != obj.point_count:
                        raise ProjectFormatError(f"Число строк не совпадает: {obj.name}")
                else:
                    obj.validate()
            for child, child_data in zip(obj.children, node.get("children", [])):
                load_node(child, child_data)
            if isinstance(obj, (WellFile, LayeredCube)):
                obj.validate()

        load_node(project.root, manifest["tree"])

    @staticmethod
    def _load_legacy_object(obj):
        if not obj.file_path or not Path(obj.file_path).is_file():
            raise ProjectFormatError(
                f"В старом проекте не сохранены данные '{obj.name}'. "
                f"Для восстановления нужен исходный файл: {obj.file_path}"
            )
        if isinstance(obj, PointCloud):
            obj.dataframe = CsvImporter().load(obj.file_path)
            if any(column is None for column in (obj.x_column, obj.y_column, obj.z_column)):
                columns = {str(column).lower(): column for column in obj.dataframe.columns}
                if not all(axis in columns for axis in ("x", "y", "z")):
                    raise ProjectFormatError(f"Не задано соответствие координат: {obj.name}")
                obj.set_mapping(*(columns[axis] for axis in ("x", "y", "z")), parameters=obj.parameters)
        else:
            import pyvista as pv
            mesh = pv.read(obj.file_path).extract_surface()
            obj.vertices = mesh.points
            obj.faces = mesh.faces
            obj.normals = mesh.point_normals
