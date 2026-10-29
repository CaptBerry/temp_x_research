"""Serializable display settings, independent of Qt and VTK."""

from dataclasses import asdict, dataclass, replace
import math
import re
from models.ColorMap import ColorMap


@dataclass(frozen=True)
class Appearance:
    mode: str = "points"
    color: str = "#1f77b4"
    point_size: float = 6.0
    point_shape: str = "circle"
    outline: bool = False
    outline_color: str = "#222222"
    line_width: float = 1.0
    color_map: ColorMap | None = None
    opacity: float = 1.0
    label_visible: bool = True
    label_color: str = "#e67624"
    label_font: str = "arial"
    label_size: int = 16

    @staticmethod
    def modes(object_type):
        if object_type == "pointcloud":
            return ("points", "spheres")
        if object_type in ("cube", "layered_cube"):
            return ("points", "spheres", "surface", "wireframe")
        if object_type in ("well", "wellfile"):
            return ("wireframe", "points", "spheres")
        if object_type == "surface":
            return ("surface", "wireframe", "points", "spheres")
        raise ValueError("У этого объекта нет настроек отображения.")

    @classmethod
    def default(cls, object_type):
        cls.modes(object_type)
        if object_type in ("surface", "layered_cube"):
            return cls(mode="surface", outline=True)
        if object_type in ("well", "wellfile"):
            return cls(mode="wireframe", color="#d95f02", point_size=5)
        return cls()

    def validate(self, object_type):
        if self.color_map is not None:
            if not isinstance(self.color_map, ColorMap):
                raise ValueError("Некорректная палитра.")
            self.color_map.validate()
        if self.mode not in self.modes(object_type):
            raise ValueError("Недопустимый режим отображения объекта.")
        if self.point_shape not in ("circle", "square"):
            raise ValueError("Неизвестная форма точки.")
        if type(self.outline) is not bool:
            raise ValueError("Обводка должна быть включена или выключена.")
        if type(self.label_visible) is not bool:
            raise ValueError("Подпись скважины должна быть включена или выключена.")
        if self.label_font not in ("arial", "times", "courier"):
            raise ValueError("Шрифт подписи: выберите Arial, Times или Courier.")
        if type(self.label_size) is not int or not 8 <= self.label_size <= 72:
            raise ValueError("Размер подписи должен быть от 8 до 72 пикселей.")
        for color in (self.color, self.outline_color, self.label_color):
            if not isinstance(color, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
                raise ValueError("Цвет должен иметь формат #RRGGBB.")
        for value, minimum, maximum, label in (
            (self.point_size, 1, 64, "Размер точки"),
            (self.line_width, 0.5, 20, "Толщина линии"),
            (self.opacity, 0, 1, "Непрозрачность"),
        ):
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not minimum <= value <= maximum):
                unit = " пикселей" if label in ("Размер точки", "Толщина линии") else ""
                raise ValueError(f"{label}: допустимо от {minimum} до {maximum}{unit}.")

    def updated(self, object_type, **changes):
        try:
            candidate = replace(self, **changes)
        except TypeError as error:
            raise ValueError("Неизвестное свойство отображения.") from error
        candidate.validate(object_type)
        return candidate

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data, object_type):
        if not isinstance(data, dict):
            raise ValueError("Настройки отображения должны быть JSON-объектом.")
        data = dict(data)
        # Saved during the short-lived per-object implementation. Axis scale is
        # now a project setting; Project migrates a common non-default value.
        for axis in "xyz":
            data.pop(f"scale_{axis}", None)
        if data.get("color_map") is not None:
            data["color_map"] = ColorMap.from_dict(data["color_map"])
        return cls.default(object_type).updated(object_type, **data)
