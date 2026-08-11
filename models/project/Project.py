from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from models.Folder import Folder
from models.Surface import Surface
from models.PointCloud import PointCloud


class Project:
    """
    Главный класс проекта.

    Отвечает за:

        • дерево объектов
        • файловую структуру проекта
        • загрузку/сохранение
        • поиск объектов
        • импорт файлов
        • изменение дерева

    GUI должен работать только через методы Project.
    """

    VERSION = 2

    # ----------------------------------------------------------
    # регистрация поддерживаемых типов объектов
    # ----------------------------------------------------------

    OBJECT_TYPES = {
        "folder": Folder,
        "surface": Surface,
        "pointcloud": PointCloud,
    }

    @classmethod
    def register_type(cls, name: str, object_class):
        cls.OBJECT_TYPES[name] = object_class

    # ----------------------------------------------------------
    # создание
    # ----------------------------------------------------------

    def __init__(self):

        self.name = "New Project"

        self.root = Folder("Work")

        self.project_path: Path | None = None

        self.modified = False

        self.created = datetime.now().isoformat()
        self.last_saved = None

    # ----------------------------------------------------------
    # свойства
    # ----------------------------------------------------------

    @property
    def is_saved(self):

        return self.project_path is not None

    @property
    def project_file(self):

        if self.project_path is None:
            return None

        return self.project_path / "project.json"

    @property
    def source_path(self):

        if self.project_path is None:
            return None

        return self.project_path / "source"

    @property
    def work_path(self):

        if self.project_path is None:
            return None

        return self.project_path / "work"

    @property
    def cache_path(self):

        if self.project_path is None:
            return None

        return self.project_path / "cache"

    # ----------------------------------------------------------
    # создание проекта
    # ----------------------------------------------------------

    @classmethod
    def create(cls, path: str | Path, name: str | None = None):

        path = Path(path)

        project = cls()

        project.project_path = path

        if name is None:
            project.name = path.name
        else:
            project.name = name

        project._create_project_structure()

        project.save()

        return project

    # ----------------------------------------------------------
    # открытие проекта
    # ----------------------------------------------------------

    @classmethod
    def open(cls, project_file):

        project_file = Path(project_file)

        with open(project_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        project = cls()

        project.project_path = project_file.parent

        project.name = data["name"]

        project.created = data.get("created")

        project.last_saved = data.get("last_saved")

        project.modified = False

        # дерево загрузим позже
        project._deserialize(data)

        return project

    # ----------------------------------------------------------
    # сохранение
    # ----------------------------------------------------------

    def save(self):

        if self.project_path is None:
            raise RuntimeError("Project path is not specified.")

        self._create_project_structure()

        self.last_saved = datetime.now().isoformat()

        data = self._serialize()

        with open(self.project_file, "w", encoding="utf8") as f:
            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )

        self.modified = False

    # ----------------------------------------------------------
    # файловая структура
    # ----------------------------------------------------------

    def _create_project_structure(self):

        self.project_path.mkdir(parents=True, exist_ok=True)

        self.source_path.mkdir(exist_ok=True)

        self.work_path.mkdir(exist_ok=True)

        self.cache_path.mkdir(exist_ok=True)

    # ----------------------------------------------------------
    # сериализация
    # ----------------------------------------------------------

    def _serialize(self):

        return {

            "version": self.VERSION,

            "name": self.name,

            "created": self.created,

            "last_saved": self.last_saved,

            "tree": self.root.to_dict()

        }

    def _deserialize(self, data):

        self.root = self._load_node(data["tree"])

    def _load_node(self, data):

        object_type = data["type"]

        cls = self.OBJECT_TYPES.get(object_type)

        if cls is None:
            raise RuntimeError(
                f"Unknown project object type: {object_type}"
            )

        obj = cls.from_dict(data)

        for child_data in data.get("children", []):
            child = self._load_node(child_data)

            obj._add(child)

        return obj

    # ----------------------------------------------------------
    # служебные
    # ----------------------------------------------------------

    def mark_modified(self):

        self.modified = True

    def __repr__(self):

        return f"<Project {self.name}>"

    # ----------------------------------------------------------
    # работа с деревом
    # ----------------------------------------------------------

    def add(self, obj, parent=None):
        """
        Добавить объект в дерево проекта.

        Если parent не указан, объект добавляется
        в корень Work.
        """

        if parent is None:
            parent = self.root

        if not isinstance(parent, Folder):
            raise TypeError("Parent must be Folder")

        if obj.parent is not None:
            raise RuntimeError("Object already belongs to project.")

        parent.add(obj)

        self.modified = True

        return obj

    def remove(self, obj):
        """
        Удалить объект из дерева.
        """

        if obj.parent is None:
            return

        obj.parent.remove(obj)

        self.modified = True

    def clear(self):
        """
        Очистить дерево проекта.
        """

        self.root.clear()

        self.modified = True

    def move(self, obj, new_parent):
        """
        Переместить объект.
        """

        if obj.parent is None:
            raise RuntimeError("Object has no parent.")

        if not isinstance(new_parent, Folder):
            raise TypeError("new_parent must be Folder")

        obj.parent.remove(obj)

        new_parent.add(obj)

        self.modified = True

    def rename(self, obj, new_name):
        """
        Переименовать объект.
        """

        obj.name = new_name

        self.modified = True

    # ----------------------------------------------------------
    # поиск
    # ----------------------------------------------------------

    def find(self, predicate):
        """
        Универсальный поиск.

        Пример:

        project.find(lambda x: x.name == "Top")
        """

        for obj in self.walk():

            if predicate(obj):
                return obj

        return None

    def find_by_name(self, name):

        return self.find(lambda x: x.name == name)

    def find_folder(self, name):

        obj = self.find(lambda x:
                        isinstance(x, Folder)
                        and x.name == name)

        return obj

    def exists(self, name):

        return self.find_by_name(name) is not None

    # ----------------------------------------------------------
    # обход дерева
    # ----------------------------------------------------------

    def walk(self, node=None):
        """
        Итератор по всем объектам проекта.
        """

        if node is None:
            node = self.root

        yield node

        if isinstance(node, Folder):

            for child in node.children:
                yield from self.walk(child)

    def children(self, folder=None):

        if folder is None:
            folder = self.root

        return list(folder.children)

    def get_path(self, obj):

        names = []

        current = obj

        while current is not None:
            names.append(current.name)

            current = current.parent

        return "/".join(reversed(names))

    def find_by_path(self, path):

        parts = Path(path).parts

        node = self.root

        if parts[0] == self.root.name:
            parts = parts[1:]

        for name in parts:

            found = None

            for child in node.children:

                if child.name == name:
                    found = child

                    break

            if found is None:
                return None

            node = found

        return node

    def objects(self, object_type=None):

        if object_type is None:
            return list(self.walk())

        return [

            obj

            for obj in self.walk()

            if isinstance(obj, object_type)

        ]

    def folders(self):

        return [

            obj

            for obj in self.walk()

            if isinstance(obj, Folder)

        ]

    def surfaces(self):

        return [

            obj

            for obj in self.walk()

            if isinstance(obj, Surface)

        ]

    def pointclouds(self):

        return [

            obj

            for obj in self.walk()

            if isinstance(obj, PointCloud)

        ]

    def _restore_parents(self, node):

        if not isinstance(node, Folder):
            return

        for child in node.children:
            child.parent = node

            self._restore_parents(child)

    def to_json(self):

        return json.dumps(

            self._serialize(),

            indent=4,

            ensure_ascii=False

        )

    def save_as(self, path):

        self.project_path = Path(path)

        self.save()

    def close(self):

        self.root.clear()

        self.project_path = None

        self.modified = False

    def has_unsaved_changes(self):

        return self.modified

    def import_file(
        self,
        obj,
        destination_folder=None
    ):

        self.add(obj, destination_folder)

        self.modified = True

        return obj

    def validate(self):

        if self.project_path is None:
            return False

        if not self.project_file.exists():
            return False

        if not self.source_path.exists():
            return False

        if not self.work_path.exists():
            return False

        return True