from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile

from models.project.Folder import Folder
from models.project.ProjectObject import ProjectObject
from models.project.ProjectStorage import ProjectFormatError, ProjectStorage
from models.Surface import Surface
from models.PointCloud import PointCloud
from models.Well import Well
from models.WellFile import WellFile
from models.DataCube import DataCube
from models.LayeredCube import LayeredCube
from models.DisplayPoints import DisplayPoints, LayeredDisplayPoints
from models.CalculationArtifact import CalculationArtifact, TrainingSet, CatalogWell
from models.Canvas import CanvasDocument


class Project:
    """Owns the object tree and dirty state, independently of Qt and disk I/O."""

    VERSION = ProjectStorage.VERSION
    OBJECT_TYPES = {"folder": Folder, "surface": Surface, "pointcloud": PointCloud,
                    "well": Well, "wellfile": WellFile, "cube": DataCube,
                    "layered_cube": LayeredCube, "calculation": CalculationArtifact,
                    "display_points": DisplayPoints, "layered_display_points": LayeredDisplayPoints,
                    "training_set": TrainingSet}

    def __init__(self):
        self.name = "New Project"
        self.root = Folder("Work")
        self.root._add(self._new_canvas_folder())
        self.canvas = CanvasDocument()
        self.project_path: Path | None = None
        self.modified = False
        self._change_serial = 0
        self.created = datetime.now(timezone.utc).isoformat()
        self.last_saved = None
        self.axis_scale = (1.0, 1.0, 1.0)
        self.axes_visible = True
        self.axes_grid_visible = False
        self.axes_label_decimals = 2
        self.axes_round_grid = False
        self.clip_enabled = False
        self.clip_origin = (0.0, 0.0, 0.0)
        self.clip_rotation = (0.0, 0.0, 0.0)
        self.clip_invert = False
        self.clip_initialized = False
        self._migrated_axis_scale = False

    @classmethod
    def register_type(cls, name, object_class):
        cls.OBJECT_TYPES[name] = object_class

    @property
    def is_saved(self):
        return self.project_path is not None

    @property
    def project_file(self):
        return self.project_path / "project.json" if self.is_saved else None

    @property
    def source_path(self):
        return self.project_path / "source" if self.is_saved else None

    @property
    def work_path(self):
        return self.project_path / "work" if self.is_saved else None

    @property
    def cache_path(self):
        return self.project_path / "cache" if self.is_saved else None

    @staticmethod
    def _check_destination(path):
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise FileExistsError("Выберите новую или пустую папку для проекта.")

    @classmethod
    def create(cls, path, name=None):
        path = Path(path).resolve()
        cls._check_destination(path)
        project = cls()
        project.name = cls._valid_name(name if name is not None else path.name)
        project._save_to(path, new_destination=True)
        return project

    @classmethod
    def open(cls, project_file):
        project_file = Path(project_file).resolve()
        if project_file.is_dir():
            project_file /= "project.json"
        data = ProjectStorage.read_manifest(project_file)
        project = cls()
        project.project_path = project_file.parent
        project.name = data["name"]
        project.created = data.get("created", project.created)
        project.last_saved = data.get("last_saved")
        project._deserialize(data)
        ProjectStorage.load_assets(project, data)
        reorganized = project.organize_canvas_results()
        project.modified = (data.get("version", 2) != cls.VERSION
                            or project._migrated_axis_scale or reorganized)
        return project

    def _save_to(self, path, *, new_destination=False):
        saved_at = datetime.now(timezone.utc).isoformat()
        if new_destination:
            path.parent.mkdir(parents=True, exist_ok=True)
            # A failed first save must not leave a nonempty destination which
            # prevents retrying Save As. Stage beside the chosen destination.
            with tempfile.TemporaryDirectory(prefix=".xsearch-", dir=path.parent) as temporary:
                staging = Path(temporary).resolve()
                if not staging.is_relative_to(path.parent.resolve()):
                    raise ValueError("Временная папка находится вне каталога назначения.")
                paths = ProjectStorage.save(self, staging, saved_at)
                self._check_destination(path)
                if path.exists():
                    path.rmdir()  # Only an empty destination is allowed here.
                os.replace(staging, path)
        else:
            paths = ProjectStorage.save(self, path, saved_at)
        # Commit in-memory state only after the manifest has been replaced.
        self.project_path = Path(path).resolve()
        self.last_saved = saved_at
        for obj in self.walk():
            if obj.uuid in paths:
                relative = paths[obj.uuid]
                obj.file_path = str(self.project_path / relative) if relative else None
        self.modified = False
        self._change_serial += 1

    def save(self):
        if self.project_path is None:
            raise RuntimeError("Не указана папка проекта.")
        self._save_to(self.project_path)

    def save_as(self, path):
        path = Path(path).resolve()
        if path != self.project_path:
            self._check_destination(path)
        self._save_to(path, new_destination=path != self.project_path)

    def _serialize(self):
        CanvasDocument.from_dict(self.canvas.to_dict())
        from scene.clipping import validate_clipping
        validate_clipping(self.clip_enabled, self.clip_origin,
                          self.clip_rotation, self.clip_invert)
        self._validate_axis_scale(self.axis_scale)
        self._validate_axes_display(self.axes_visible, self.axes_grid_visible)
        self._validate_axes_format(self.axes_label_decimals, self.axes_round_grid)
        return dict(version=self.VERSION, name=self.name, created=self.created,
                    last_saved=self.last_saved, axis_scale=list(self.axis_scale),
                    axes_visible=self.axes_visible,
                    axes_grid_visible=self.axes_grid_visible,
                    axes_label_decimals=self.axes_label_decimals,
                    axes_round_grid=self.axes_round_grid,
                    clipping=dict(enabled=self.clip_enabled,
                                  origin=list(self.clip_origin),
                                  rotation=list(self.clip_rotation),
                                  invert=self.clip_invert,
                                  initialized=self.clip_initialized),
                    canvas=self.canvas.to_dict(), tree=self.root.to_dict())

    def set_clipping(self, enabled, origin, rotation, invert=False):
        from scene.clipping import validate_clipping
        candidate = validate_clipping(enabled, origin, rotation, invert)
        if candidate == (self.clip_enabled, self.clip_origin,
                         self.clip_rotation, self.clip_invert):
            return False
        self.clip_enabled, self.clip_origin, self.clip_rotation, self.clip_invert = candidate
        self.clip_initialized = True
        self.mark_modified()
        return True

    @staticmethod
    def _validate_axis_scale(values):
        if (not isinstance(values, (list, tuple)) or len(values) != 3
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       or not 0.001 <= value <= 10000 for value in values)):
            raise ValueError("Масштаб каждой оси должен быть от 0,001 до 10000.")
        return tuple(float(value) for value in values)

    def set_axis_scale(self, x, y, z):
        candidate = self._validate_axis_scale((x, y, z))
        if candidate == self.axis_scale:
            return False
        self.axis_scale = candidate
        self.mark_modified()
        return True

    @staticmethod
    def _validate_axes_display(visible, grid_visible):
        if type(visible) is not bool or type(grid_visible) is not bool:
            raise ValueError("Видимость осей и координатной сетки должна быть включена или выключена.")
        return visible, grid_visible

    @staticmethod
    def _validate_axes_format(decimals, round_grid):
        if type(decimals) is not int or not 0 <= decimals <= 9:
            raise ValueError("Число знаков после запятой должно быть от 0 до 9.")
        if type(round_grid) is not bool:
            raise ValueError("Округление сетки должно быть включено или выключено.")
        return decimals, round_grid

    def set_axes_settings(self, scale, visible, grid_visible, *,
                          label_decimals=None, round_grid=None):
        candidate_scale = self._validate_axis_scale(scale)
        candidate_visible, candidate_grid = self._validate_axes_display(visible, grid_visible)
        candidate_decimals, candidate_round = self._validate_axes_format(
            self.axes_label_decimals if label_decimals is None else label_decimals,
            self.axes_round_grid if round_grid is None else round_grid)
        if ((candidate_scale, candidate_visible, candidate_grid,
             candidate_decimals, candidate_round) ==
                (self.axis_scale, self.axes_visible, self.axes_grid_visible,
                 self.axes_label_decimals, self.axes_round_grid)):
            return False
        self.axis_scale = candidate_scale
        self.axes_visible = candidate_visible
        self.axes_grid_visible = candidate_grid
        self.axes_label_decimals = candidate_decimals
        self.axes_round_grid = candidate_round
        self.mark_modified()
        return True

    def _deserialize(self, data):
        self.canvas = CanvasDocument.from_dict(data.get("canvas", {}))
        from scene.clipping import validate_clipping
        clipping = data.get("clipping", {})
        if not isinstance(clipping, dict):
            raise ProjectFormatError("Некорректные настройки отсечения.")
        (self.clip_enabled, self.clip_origin, self.clip_rotation,
         self.clip_invert) = validate_clipping(
            clipping.get("enabled", False), clipping.get("origin", (0, 0, 0)),
            clipping.get("rotation", (0, 0, 0)), clipping.get("invert", False))
        self.clip_initialized = clipping.get("initialized", bool(clipping))
        if type(self.clip_initialized) is not bool:
            raise ProjectFormatError("Некорректные настройки отсечения.")
        self.axes_visible, self.axes_grid_visible = self._validate_axes_display(
            data.get("axes_visible", True), data.get("axes_grid_visible", False))
        self.axes_label_decimals, self.axes_round_grid = self._validate_axes_format(
            data.get("axes_label_decimals", 2), data.get("axes_round_grid", False))
        if "axis_scale" in data:
            self.axis_scale = self._validate_axis_scale(data["axis_scale"])
        else:
            # Migrate the earlier per-object scale when all non-default values
            # agree. Conflicting old transforms cannot define one scene scale.
            legacy_scales = set()

            def collect_legacy(node):
                appearance = node.get("appearance", {}) if isinstance(node, dict) else {}
                if isinstance(appearance, dict) and any(f"scale_{a}" in appearance for a in "xyz"):
                    scale = tuple(appearance.get(f"scale_{a}", 1) for a in "xyz")
                    if scale != (1, 1, 1):
                        legacy_scales.add(self._validate_axis_scale(scale))
                for child in node.get("children", []) if isinstance(node, dict) else []:
                    collect_legacy(child)

            collect_legacy(data["tree"])
            if len(legacy_scales) == 1:
                self.axis_scale = legacy_scales.pop()
                self._migrated_axis_scale = True
        identifiers = set()

        def load_node(node):
            if not isinstance(node, dict) or not isinstance(node.get("name"), str):
                raise ProjectFormatError("Некорректный узел дерева проекта.")
            object_class = self.OBJECT_TYPES.get(node.get("type"))
            if object_class is None:
                raise ProjectFormatError(f"Неизвестный тип объекта: {node.get('type')}")
            obj = object_class.from_dict(node)
            if not isinstance(obj.uuid, str) or not obj.uuid or obj.uuid in identifiers:
                raise ProjectFormatError("Повторяющийся или некорректный UUID объекта.")
            identifiers.add(obj.uuid)
            children = node.get("children", [])
            if not isinstance(children, list) or (children and not isinstance(obj, Folder)):
                raise ProjectFormatError("Дочерние объекты разрешены только у папок.")
            for child in children:
                obj._add(load_node(child))
            return obj

        self.root = load_node(data["tree"])
        if not isinstance(self.root, Folder):
            raise ProjectFormatError("Корень проекта должен быть папкой.")

    def mark_modified(self):
        self._change_serial += 1
        self.modified = True

    @staticmethod
    def _valid_name(name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Имя не может быть пустым.")
        return name.strip()

    def _require_member(self, obj):
        if not any(node is obj for node in self.walk()):
            raise ValueError("Объект не принадлежит этому проекту.")

    @staticmethod
    def _new_canvas_folder():
        folder = Folder("Canvas")
        folder.metadata["system_role"] = "canvas_results"
        return folder

    def canvas_folder(self):
        """The persistent tree container for objects produced by Canvas runs."""
        folder = next((child for child in self.root.children
                       if child.TYPE == "folder"
                       and child.metadata.get("system_role") == "canvas_results"), None)
        if folder is None:
            folder = next((child for child in self.root.children
                           if child.TYPE == "folder" and child.name == "Canvas"
                           and not child.metadata.get("system_role")), None)
            if folder is not None:
                folder.metadata["system_role"] = "canvas_results"
                self.mark_modified()
        if folder is None:
            folder = self.add(self._new_canvas_folder())
        return folder

    def add_canvas_result(self, obj):
        return self.add(obj, self.canvas_folder())

    def organize_canvas_results(self):
        """Migrate old output locations without changing UUIDs or nested assets."""
        serial = self._change_serial
        folder = self.canvas_folder()
        result_ids = {run.get("output_uuid") for run in self.canvas.runs}
        results = [obj for obj in self.walk()
                   if obj is not self.root and obj is not folder
                   and (obj.uuid in result_ids or obj.metadata.get("canvas_node"))]
        candidates = {obj.uuid for obj in results}
        for obj in results:
            parent = obj.parent
            # A layered result moves as a whole. Keep user grouping inside Canvas.
            while parent is not None:
                if parent is folder or parent.uuid in candidates:
                    break
                parent = parent.parent
            if parent is None:
                self.move(obj, folder)
        return self._change_serial != serial

    def add(self, obj, parent=None):
        parent = self.root if parent is None else parent
        self._require_member(parent)
        if not isinstance(parent, Folder):
            raise TypeError("Родитель должен быть папкой.")
        if not isinstance(obj, ProjectObject) or obj.parent is not None:
            raise ValueError("Объект уже принадлежит дереву или имеет неверный тип.")
        descendants = list(self.walk(obj))
        existing_ids = {node.uuid for node in self.walk()}
        incoming_ids = [node.uuid for node in descendants]
        if len(set(incoming_ids)) != len(incoming_ids) or existing_ids.intersection(incoming_ids):
            raise ValueError("Объект уже находится в проекте или имеет повторяющийся UUID.")
        container_style = None
        if isinstance(parent, (WellFile, LayeredCube, LayeredDisplayPoints)):
            container_style = parent.appearance
            container_style.validate(obj.TYPE)
            if container_style.color_map is not None:
                obj.color_values(container_style.color_map.field)
        parent._add(obj)
        if container_style is not None:
            obj.appearance = container_style
            if isinstance(parent, LayeredDisplayPoints):
                obj.display_grid = parent.display_grid
        self.mark_modified()
        return obj

    def remove(self, obj):
        self._require_member(obj)
        if isinstance(obj, CatalogWell):
            raise ValueError("Скважина каталога удаляется только вместе с каталогом; её можно скрыть галочкой.")
        if obj is self.root:
            raise ValueError("Нельзя удалить корневую папку.")
        obj.parent._remove(obj)
        self.mark_modified()

    def clear(self):
        folder = self.canvas_folder()
        self.root._clear()
        self.root._add(folder)
        self.mark_modified()

    def move(self, obj, new_parent):
        self._require_member(obj)
        self._require_member(new_parent)
        if obj is self.root or not isinstance(new_parent, Folder):
            raise ValueError("Невозможно переместить объект в указанную папку.")
        if any(node is new_parent for node in self.walk(obj)):
            raise ValueError("Нельзя переместить папку внутрь самой себя.")
        if obj.parent is new_parent:
            return
        if isinstance(new_parent, WellFile):
            if not isinstance(obj, Well) or any(well.well_id == obj.well_id for well in new_parent.wells):
                raise ValueError("В файл скважин можно переместить только скважину с новым ID.")
        if isinstance(new_parent, LayeredCube):
            if (not isinstance(obj, DataCube) or not obj.is_corner_point
                    or obj.metadata.get("layer_index") is None
                    or any(str(layer.metadata.get("layer_index")) == str(obj.metadata["layer_index"])
                           for layer in new_parent.layers)):
                raise ValueError("В послойный куб можно переместить только новый слой corner-point grid.")
        container_style = None
        if isinstance(new_parent, LayeredDisplayPoints):
            if (not isinstance(obj, DisplayPoints) or obj.metadata.get("layer_name") is None
                    or any(layer.metadata["layer_name"] == obj.metadata["layer_name"]
                           for layer in new_parent.layers)):
                raise ValueError("В слои точек можно переместить только новый слой точек.")
        if isinstance(new_parent, (WellFile, LayeredCube, LayeredDisplayPoints)):
            container_style = new_parent.appearance
            container_style.validate(obj.TYPE)
            if container_style.color_map is not None:
                obj.color_values(container_style.color_map.field)
        obj.parent._remove(obj)
        new_parent._add(obj)
        if container_style is not None:
            obj.appearance = container_style
            if isinstance(new_parent, LayeredDisplayPoints):
                obj.display_grid = new_parent.display_grid
        self.mark_modified()

    def rename(self, obj, new_name):
        self._require_member(obj)
        if isinstance(obj, CatalogWell):
            raise ValueError("Имя дочерней скважины берётся из каталога образцов.")
        new_name = self._valid_name(new_name)
        if obj.name != new_name:
            obj.name = new_name
            self.mark_modified()

    def rename_project(self, name):
        name = self._valid_name(name)
        if self.name != name:
            self.name = name
            self.mark_modified()

    def set_visible(self, obj, visible):
        self._require_member(obj)
        if obj.visible != bool(visible):
            obj.visible = bool(visible)
            self.mark_modified()

    def set_subtree_visible(self, container, visible):
        """Set a container and every descendant to one visibility state."""
        self._require_member(container)
        if not isinstance(container, Folder):
            raise ValueError("Групповая видимость доступна только контейнеру.")
        visible = bool(visible)
        changed = False
        for obj in self.walk(container):
            if obj.visible != visible:
                obj.visible = visible
                changed = True
        if changed:
            self.mark_modified()
        return changed

    def set_appearance(self, obj, **changes):
        self._require_member(obj)
        if isinstance(obj, (WellFile, LayeredCube, LayeredDisplayPoints)):
            candidate = obj.appearance.updated(obj.TYPE, **changes)
            if candidate.color_map is not None:
                obj.color_values(candidate.color_map.field)
            # Validate every child before changing the container or any child.
            for child in obj.children:
                candidate.validate(child.TYPE)
                if candidate.color_map is not None:
                    child.color_values(candidate.color_map.field)
            if candidate == obj.appearance and all(child.appearance == candidate
                                                   for child in obj.children):
                return False
            obj.appearance = candidate
            for child in obj.children:
                child.appearance = candidate
            self.mark_modified()
            return True
        if not isinstance(obj, (PointCloud, Surface)):
            raise ValueError("У этого объекта нет настроек отображения.")
        candidate = obj.appearance.updated(obj.TYPE, **changes)
        if isinstance(obj, DataCube) and not obj.is_corner_point and candidate.mode in ("surface", "wireframe"):
            raise ValueError("Для куба из узлов доступны только точки, сферы и ячейки.")
        if candidate.mode == "cells" and not (isinstance(obj, DataCube) and obj.is_corner_point) \
                and obj.cell_edges() is None:
            raise ValueError("Для отображения ячеек нужны центры в строках и слоях XYZ.")
        if candidate.color_map is not None:
            obj.color_values(candidate.color_map.field)
        if candidate == obj.appearance:
            return False
        obj.appearance = candidate
        self.mark_modified()
        return True

    def set_display_grid(self, obj, **changes):
        self._require_member(obj)
        if not isinstance(obj, (DisplayPoints, LayeredDisplayPoints)):
            raise ValueError("Настройки сетки доступны для нового варианта импорта точек.")
        candidate = obj.display_grid.updated(**changes)
        targets = [obj, *obj.children] if isinstance(obj, LayeredDisplayPoints) else [obj]
        if all(target.display_grid == candidate for target in targets):
            return False
        for target in targets:
            target.display_grid = candidate
        self.mark_modified()
        return True

    def is_visible(self, obj):
        while obj is not None:
            if not obj.visible:
                return False
            obj = obj.parent
        return True

    def find(self, predicate):
        return next((obj for obj in self.walk() if predicate(obj)), None)

    def find_by_id(self, object_id):
        return self.find(lambda obj: obj.uuid == object_id)

    def find_by_name(self, name):
        return self.find(lambda obj: obj.name == name)

    def find_folder(self, name):
        return self.find(lambda obj: isinstance(obj, Folder) and obj.name == name)

    def exists(self, name):
        return self.find_by_name(name) is not None

    def walk(self, node=None):
        node = self.root if node is None else node
        yield node
        for child in node.children:
            yield from self.walk(child)

    def children(self, folder=None):
        return list((self.root if folder is None else folder).children)

    def get_path(self, obj):
        self._require_member(obj)
        return obj.path

    def find_by_path(self, path):
        parts = str(path).replace("\\", "/").strip("/").split("/")
        node = self.root
        if parts and parts[0] == node.name:
            parts = parts[1:]
        for name in filter(None, parts):
            node = next((child for child in node.children if child.name == name), None)
            if node is None:
                return None
        return node

    def objects(self, object_type=None):
        return [obj for obj in self.walk() if object_type is None or isinstance(obj, object_type)]

    def folders(self):
        return self.objects(Folder)

    def surfaces(self):
        return self.objects(Surface)

    def pointclouds(self):
        return [obj for obj in self.walk() if type(obj) is PointCloud]

    def wells(self):
        return self.objects(Well)

    def well_files(self):
        return self.objects(WellFile)

    def cubes(self):
        return self.objects(DataCube)

    def to_json(self):
        """Metadata preview; persistence must use save()/save_as()."""
        return json.dumps(self._serialize(), indent=2, ensure_ascii=False)

    def close(self):
        self.__init__()

    def has_unsaved_changes(self):
        return self.modified

    def import_file(self, obj, destination_folder=None):
        if isinstance(obj, (PointCloud, Surface, WellFile, LayeredCube, LayeredDisplayPoints)):
            obj.validate()
        return self.add(obj, destination_folder)

    def validate(self):
        return self.is_saved and all(path.exists() for path in
                                    (self.project_file, self.source_path, self.work_path))

    def __repr__(self):
        return f"<Project {self.name}>"
