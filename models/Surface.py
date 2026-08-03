from .ProjectObject import ProjectObject


class Surface(ProjectObject):
    def __init__(self, name="Surface", file_path=None):
        super().__init__(name)
        self.file_path = file_path
        self.file_type = None  # Например: 'stl', 'obj', 'ply'
        self.vertices = []
        self.faces = []
        self.normals = []

    def to_dict(self) -> dict:
        """Преобразовать поверхность в словарь"""
        return {
            "type": "surface",
            "name": self.name,
            "file_path": self.file_path,
            "file_type": self.file_type,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Воссоздать поверхность из словаря"""
        surface = cls(data["name"], data.get("file_path"))
        surface.file_type = data.get("file_type")
        surface.metadata = data.get("metadata", {})
        return surface