"""Disk format: immutable assets and an atomically replaced manifest.

Obsolete assets are removed only after the new manifest has been committed.
Only JSON and NumPy arrays without pickle are read from project files.
"""

import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import tempfile

import numpy as np

from importers.CsvImporter import CsvImporter
from models.CornerPointGrid import CornerPointGrid
from models.DataCube import DataCube
from models.LayeredCube import LayeredCube
from models.DisplayPoints import LayeredDisplayPoints
from models.PointCloud import PointCloud
from models.Surface import Surface
from models.WellFile import WellFile
from models.CalculationArtifact import CalculationArtifact
from models.project.TableStorage import TableStorage


logger = logging.getLogger(__name__)


class ProjectFormatError(ValueError):
    pass


class ProjectStorage:
    VERSION = 4
    _HASH = re.compile(r"[0-9a-f]{64}\Z")
    _WORK_SUFFIXES = (".table.npz", ".surface.npz", ".corner.npz", ".calculation.zip")

    @staticmethod
    def read_manifest(path):
        with Path(path).open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ProjectFormatError("Файл проекта должен содержать JSON-объект.")
        version = data.get("version", 2)
        if type(version) is not int or version not in (2, 3, ProjectStorage.VERSION):
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
    def _store_source(cls, directory, source, name):
        source = Path(source)
        prefix = name.encode("utf-8") + b"\0"

        def source_hash(path):
            digest = hashlib.sha256(prefix)
            with path.open("rb") as stream:
                while block := stream.read(8 * 1024 * 1024):
                    digest.update(block)
            return digest.hexdigest()

        before = source.stat()
        identifier = source_hash(source)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError("Исходный файл изменился во время сохранения проекта.")
        relative = Path("source") / identifier / name
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and (source.resolve() == target.resolve()
                                 or target.stat().st_size == before.st_size
                                 and source_hash(target) == identifier):
            return relative.as_posix()
        descriptor, temporary = tempfile.mkstemp(prefix=".saving-", dir=target.parent)
        try:
            copied = hashlib.sha256(prefix)
            with os.fdopen(descriptor, "wb") as output, source.open("rb") as stream:
                while block := stream.read(8 * 1024 * 1024):
                    copied.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            if copied.hexdigest() != identifier:
                raise OSError("Исходный файл изменился во время сохранения проекта.")
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return relative.as_posix()

    @classmethod
    def _prune_assets(cls, directory, manifest):
        work_refs = set()
        source_refs = set()

        def collect(node):
            if node.get("data_file"):
                work_refs.add(node["data_file"])
            if node.get("file_path"):
                source_refs.add(node["file_path"])
            for child in node.get("children", []):
                collect(child)

        collect(manifest["tree"])
        work = directory / "work"
        for path in work.iterdir():
            if (path.is_file() and any(path.name.endswith(suffix) for suffix in cls._WORK_SUFFIXES)
                    and cls._HASH.fullmatch(path.name.split(".", 1)[0])
                    and path.relative_to(directory).as_posix() not in work_refs):
                path.unlink()

        source = directory / "source"
        for path in source.iterdir():
            if path.is_dir() and not path.is_symlink() and cls._HASH.fullmatch(path.name):
                for file in path.iterdir():
                    if file.is_file() and file.relative_to(directory).as_posix() not in source_refs:
                        file.unlink()
                if not any(path.iterdir()):
                    path.rmdir()
            elif (path.is_file() and cls._HASH.fullmatch(path.stem)
                  and path.relative_to(directory).as_posix() not in source_refs):
                path.unlink()

    @classmethod
    def save(cls, project, directory, saved_at):
        directory = Path(directory).resolve()
        for name in ("source", "work", "cache"):
            (directory / name).mkdir(parents=True, exist_ok=True)
        manifest = project._serialize()
        manifest["last_saved"] = saved_at
        source_paths = {}
        source_cache = {}
        objects = {obj.uuid: obj for obj in project.walk()}

        def store_node(node):
            obj = objects[node["uuid"]]
            if isinstance(obj, CalculationArtifact):
                node["data_file"] = cls._store_asset(directory, "work", ".calculation.zip", obj.dumps())
            if isinstance(obj, (WellFile, LayeredCube, LayeredDisplayPoints)):
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
                    name = obj.metadata.get("source_name", source.name)
                    if (not isinstance(name, str) or not name or name in (".", "..")
                            or Path(name).name != name or Path(name).is_reserved()):
                        name = source.name
                    key = (source.resolve(), name)
                    if key not in source_cache:
                        source_cache[key] = cls._store_source(directory, source, name)
                    node["file_path"] = source_cache[key]
                source_paths[obj.uuid] = node["file_path"]
            for child in node.get("children", []):
                store_node(child)

        store_node(manifest["tree"])
        content = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        cls._write_atomic(directory / "project.json", content)
        try:
            cls._prune_assets(directory, manifest)
        except OSError:
            logger.warning("Не удалось удалить устаревшие файлы проекта: %s", directory, exc_info=True)
        return source_paths

    @classmethod
    def load_assets(cls, project, manifest):
        legacy = manifest.get("version", 2) == 2

        def load_node(obj, node):
            if isinstance(obj, CalculationArtifact):
                obj.load(cls.asset_path(project.project_path, node.get("data_file")))
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
                    if not path.is_file():
                        raise ProjectFormatError(
                            f"Отсутствует файл данных объекта «{obj.name}»: "
                            f"{node['data_file']}. Восстановите его из копии проекта."
                        )
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
                        if obj.metadata.get("prediction"):
                            codes = obj.dataframe["class_index"].to_numpy(float)
                            classes = list(obj.metadata.get("classes", []))
                            valid = np.isfinite(codes) & (codes >= 0) & (codes < len(classes))
                            labels = np.full(len(codes), "Нет прогноза", dtype=object)
                            labels[valid] = np.asarray(classes, dtype=object)[codes[valid].astype(int)]
                            obj.dataframe["source_row"] = np.arange(len(codes))
                            obj.dataframe["class_name"] = labels
                            obj.dataframe["status"] = np.where(valid, "прогноз", "недостаточно данных")
                            if "confidence" not in obj.dataframe:
                                obj.dataframe["confidence"] = np.nan
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
            if isinstance(obj, (WellFile, LayeredCube, LayeredDisplayPoints)):
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
