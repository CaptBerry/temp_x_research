from .ProjectObject import ProjectObject


class Folder(ProjectObject):
    def __init__(self, name="Folder"):
        super().__init__(name)
        self.children = []

    def add(self, obj):
        obj.parent = self
        self.children.append(obj)

    def remove(self, obj):
        self.children.remove(obj)
        obj.parent = None

    def clear(self):
        for child in self.children:
            child.parent = None
        self.children.clear()

    def __iter__(self):
        return iter(self.children)

    def __len__(self):
        return len(self.children)

    def to_dict(self) -> dict:
        """Преобразовать папку в словарь"""
        return {
            "type": "folder",
            "name": self.name,
            "children": [child.to_dict() for child in self.children],
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Воссоздать папку из словаря"""
        folder = cls(data["name"])
        folder.metadata = data.get("metadata", {})

        # Рекурсивно восстанавливаем детей
        for child_data in data.get("children", []):
            child_type = child_data.get("type")
            if child_type == "folder":
                child = Folder.from_dict(child_data)
            elif child_type == "surface":
                # Позже добавим Surface
                child = None
            elif child_type == "pointcloud":
                # Позже добавим PointCloud
                child = None
            else:
                child = None

            if child:
                folder.add(child)

        return folder