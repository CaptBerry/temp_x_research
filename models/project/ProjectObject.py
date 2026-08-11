from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import uuid4


class ProjectObject(ABC):
    """
    Базовый класс любого объекта проекта.

    Наследники:
        Folder
        Surface
        PointCloud
        Cube
        Well
        Polyline
        ...
    """

    TYPE = "object"

    def __init__(self, name: str = "Object"):

        self.uuid = str(uuid4())

        self.name = name

        self.parent = None

        self.visible = True

        self.locked = False

        self.metadata = {}

    # ---------------------------------------------------------
    # свойства дерева
    # ---------------------------------------------------------
    @property
    def children(self):
        return ()

    @property
    def is_root(self):

        return self.parent is None

    @property
    def root(self):

        obj = self

        while obj.parent is not None:
            obj = obj.parent

        return obj

    @property
    def path(self):
        """
        Полный путь объекта внутри дерева проекта.
        """

        names = []

        obj = self

        while obj is not None:

            names.append(obj.name)

            obj = obj.parent

        return "/".join(reversed(names))

    @property
    def depth(self):

        depth = 0

        obj = self.parent

        while obj is not None:

            depth += 1

            obj = obj.parent

        return depth

    # ---------------------------------------------------------
    # сериализация
    # ---------------------------------------------------------

    def _base_dict(self):

        return {

            "type": self.TYPE,

            "uuid": self.uuid,

            "name": self.name,

            "visible": self.visible,

            "locked": self.locked,

            "metadata": self.metadata

        }

    def _load_base(self, data):

        self.uuid = data.get("uuid", str(uuid4()))

        self.visible = data.get("visible", True)

        self.locked = data.get("locked", False)

        self.metadata = data.get("metadata", {})

    @abstractmethod
    def to_dict(self):
        ...

    @classmethod
    @abstractmethod
    def from_dict(cls, data):
        ...

    # ---------------------------------------------------------
    # python
    # ---------------------------------------------------------

    def __repr__(self):

        return (

            f"<{self.__class__.__name__} "

            f"name='{self.name}'>"

        )