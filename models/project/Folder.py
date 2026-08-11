from __future__ import annotations

from models.project.ProjectObject import ProjectObject


class Folder(ProjectObject):
    """
    Узел дерева проекта.

    Folder ничего не знает о Project и других типах объектов.
    Изменять дерево может только Project через внутренние методы
    _add() и _remove().
    """

    TYPE = "folder"

    def __init__(self, name: str = "Folder"):
        super().__init__(name)

        self._children: list[ProjectObject] = []

    # ------------------------------------------------------------------
    # Внутренние методы.
    # Их должен использовать только Project.
    # ------------------------------------------------------------------

    def _add(self, obj: ProjectObject):

        if obj.parent is not None:
            raise RuntimeError(
                f"'{obj.name}' already belongs to another folder."
            )

        obj.parent = self

        self._children.append(obj)

    def _remove(self, obj: ProjectObject):

        self._children.remove(obj)

        obj.parent = None

    def _clear(self):
        """
        Полностью очистить папку.
        """

        for child in self._children:

            if isinstance(child, Folder):
                child._clear()

            child.parent = None

        self._children.clear()

    # ------------------------------------------------------------------
    # Только чтение
    # ------------------------------------------------------------------

    @property
    def children(self):
        return tuple(self._children)

    @property
    def count(self):
        return len(self._children)

    @property
    def empty(self):
        return len(self._children) == 0

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    def to_dict(self):

        return {

            "type": self.TYPE,

            "name": self.name,

            "metadata": self.metadata,

            "children": [

                child.to_dict()

                for child in self._children

            ]

        }

    @classmethod
    def from_dict(cls, data):

        folder = cls(data["name"])

        folder.metadata = data.get("metadata", {})

        #
        # Детей загружает Project.
        #

        return folder

    # ------------------------------------------------------------------
    # Python API
    # ------------------------------------------------------------------

    def __iter__(self):
        return iter(self._children)

    def __getitem__(self, index):
        return self._children[index]

    def __len__(self):
        return len(self._children)

    def __contains__(self, obj):
        return obj in self._children

    def __repr__(self):

        return (
            f"<Folder "
            f"name='{self.name}' "
            f"objects={len(self._children)}>"
        )