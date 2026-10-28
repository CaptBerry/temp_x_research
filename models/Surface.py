from pathlib import Path
import numpy as np

from models.project.ProjectObject import ProjectObject
from models.Appearance import Appearance


class Surface(ProjectObject):
    TYPE = "surface"

    def __init__(self, name="Surface", file_path=None):
        super().__init__(name)
        self.file_path = str(file_path) if file_path is not None else None
        self.file_type = Path(file_path).suffix.lstrip(".").lower() if file_path else None
        self.vertices = []
        self.faces = []
        self.normals = []
        self.appearance = Appearance.default(self.TYPE)
        self.surface_kind = "general"

    def validate(self):
        self.appearance.validate(self.TYPE)
        if self.surface_kind not in ("general", "section", "fault"):
            raise ValueError("Неизвестный вид поверхности.")
        if self.appearance.color_map is not None:
            self.color_values(self.appearance.color_map.field)
        vertices = np.asarray(self.vertices, dtype=float)
        if vertices.size and (vertices.ndim != 2 or vertices.shape[1] != 3):
            raise ValueError("Вершины поверхности должны иметь форму N × 3.")
        if not np.isfinite(vertices).all():
            raise ValueError("Вершины поверхности содержат некорректные координаты.")
        faces = np.asarray(self.faces)
        if faces.ndim != 1 or (faces.size and faces.dtype.kind not in "iu"):
            raise ValueError("Грани должны быть одномерным массивом целых индексов VTK.")
        offset = 0
        while offset < len(faces):
            count = int(faces[offset])
            indices = faces[offset + 1:offset + 1 + count]
            if count < 3 or len(indices) != count or (indices < 0).any() or (indices >= len(vertices)).any():
                raise ValueError("Грань поверхности содержит некорректные индексы вершин.")
            offset += count + 1
        normals = np.asarray(self.normals, dtype=float)
        if normals.size and (normals.shape != vertices.shape or not np.isfinite(normals).all()):
            raise ValueError("Нормали должны соответствовать вершинам поверхности.")

    def numeric_fields(self):
        return ["z"]

    def color_values(self, field):
        if field != "z":
            raise ValueError("Для поверхности доступна окраска только по высоте Z.")
        vertices = np.asarray(self.vertices, dtype=float)
        if vertices.size == 0:
            raise ValueError("Поверхность не содержит вершин.")
        return vertices[:, 2]

    @property
    def face_count(self):
        faces = np.asarray(self.faces, dtype=int)
        count = offset = 0
        while offset < len(faces):
            offset += int(faces[offset]) + 1
            count += 1
        return count

    @property
    def area(self):
        vertices = np.asarray(self.vertices, dtype=float)
        faces = np.asarray(self.faces, dtype=int)
        area = 0.0
        offset = 0
        while offset < len(faces):
            count = int(faces[offset])
            corners = vertices[faces[offset + 1:offset + 1 + count]]
            for i in range(1, count - 1):
                area += np.linalg.norm(np.cross(corners[i] - corners[0], corners[i + 1] - corners[0])) / 2
            offset += count + 1
        return float(area)

    def to_dict(self) -> dict:
        """Преобразовать поверхность в словарь"""
        data = self._base_dict()
        data.update(file_path=self.file_path, file_type=self.file_type,
                    appearance=self.appearance.to_dict(), surface_kind=self.surface_kind)
        return data

    @classmethod
    def from_dict(cls, data: dict):
        """Воссоздать поверхность из словаря"""
        surface = cls(data["name"], data.get("file_path"))
        surface.file_type = data.get("file_type")
        surface._load_base(data)
        surface.appearance = Appearance.from_dict(data.get("appearance", {}), cls.TYPE)
        surface.surface_kind = data.get("surface_kind", "general")
        return surface
