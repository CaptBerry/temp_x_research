from .ProjectObject import ProjectObject


class PointCloud(ProjectObject):
    def __init__(self, name="PointCloud", file_path=None):
        super().__init__(name)
        self.file_path = file_path
        self.file_type = None  # Например: 'xyz', 'las', 'ply'
        self.points = []  # Список точек [x, y, z]
        self.colors = []  # Опционально: цвета
        self.normals = []  # Опционально: нормали

    def to_dict(self) -> dict:
        """Преобразовать облако точек в словарь"""
        return {
            "type": "pointcloud",
            "name": self.name,
            "file_path": self.file_path,
            "file_type": self.file_type,
            "point_count": len(self.points),  # Только количество, сами точки не сохраняем
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Воссоздать облако точек из словаря"""
        pointcloud = cls(data["name"], data.get("file_path"))
        pointcloud.file_type = data.get("file_type")
        pointcloud.metadata = data.get("metadata", {})
        return pointcloud