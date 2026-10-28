"""Surfer CLR palettes and their data-value ranges (no GUI dependencies)."""

from dataclasses import dataclass, asdict
from pathlib import Path
import colorsys
import math

import numpy as np


@dataclass(frozen=True)
class ColorStop:
    position: float
    color: str
    alpha: int = 255


@dataclass(frozen=True)
class OpacityStop:
    position: float
    opacity: float


@dataclass(frozen=True)
class ColorMap:
    field: str
    minimum: float
    maximum: float
    stops: tuple[ColorStop, ...]
    interpolation: int = 0
    opacity_stops: tuple[OpacityStop, ...] = ()
    value_scale: str = "linear"

    @classmethod
    def default(cls, field, minimum, maximum):
        return cls(field, minimum, maximum, (
            ColorStop(0, "#0000ff"), ColorStop(50, "#ffff00"),
            ColorStop(100, "#ff0000")))

    def validate(self):
        if not isinstance(self.field, str) or not self.field:
            raise ValueError("Выберите числовой параметр палитры.")
        if not all(type(v) in (int, float) and math.isfinite(v)
                   for v in (self.minimum, self.maximum)) or self.minimum >= self.maximum:
            raise ValueError("Нижний предел палитры должен быть меньше верхнего.")
        if type(self.interpolation) is not int or self.interpolation not in range(10):
            raise ValueError("Неизвестный способ интерполяции палитры.")
        if self.value_scale not in ("linear", "log"):
            raise ValueError("Неизвестная шкала значений палитры.")
        if self.value_scale == "log" and self.minimum <= 0:
            raise ValueError("Для логарифмической палитры оба предела должны быть положительными.")
        if len(self.stops) < 2 or len(self.stops) > 10000:
            raise ValueError("Палитра должна содержать от 2 до 10000 цветовых узлов.")
        for nodes in (self.stops, self.opacity_stops):
            positions = [node.position for node in nodes]
            if any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 100
                   for p in positions) or positions != sorted(positions):
                raise ValueError("Позиции узлов должны идти от 0 до 100 по возрастанию.")
            if nodes and (positions[0] != 0 or positions[-1] != 100):
                raise ValueError("Узлы палитры должны включать 0 и 100%.")
        for stop in self.stops:
            if (not isinstance(stop.color, str) or len(stop.color) != 7
                    or not stop.color.startswith("#")
                    or any(c not in "0123456789abcdefABCDEF" for c in stop.color[1:])):
                raise ValueError("Цвет узла должен иметь формат #RRGGBB.")
            if type(stop.alpha) is not int or not 0 <= stop.alpha <= 255:
                raise ValueError("Прозрачность цветового узла должна быть от 0 до 255.")
        for stop in self.opacity_stops:
            if type(stop.opacity) not in (int, float) or not math.isfinite(stop.opacity) or not 0 <= stop.opacity <= 100:
                raise ValueError("Прозрачность должна быть от 0 до 100%.")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        try:
            result = cls(data["field"], data["minimum"], data["maximum"],
                         tuple(ColorStop(**s) for s in data["stops"]),
                         data.get("interpolation", 0),
                         tuple(OpacityStop(**s) for s in data.get("opacity_stops", [])),
                         data.get("value_scale", "linear"))
            result.validate()
            return result
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("Некорректные данные палитры в проекте.") from error

    def value_at(self, position):
        """Return the data value at a color-stop position in percent."""
        fraction = position / 100
        if self.value_scale == "log":
            return 10 ** (math.log10(self.minimum) * (1 - fraction)
                          + math.log10(self.maximum) * fraction)
        return self.minimum + (self.maximum - self.minimum) * fraction

    def position_of(self, value):
        """Return the color-stop position for a data value."""
        if self.value_scale == "log":
            if value <= 0:
                raise ValueError("Логарифмическая палитра требует положительного значения.")
            return 100 * (math.log10(value) - math.log10(self.minimum)) / (
                math.log10(self.maximum) - math.log10(self.minimum))
        return 100 * (value - self.minimum) / (self.maximum - self.minimum)

    def rgba(self, count=256):
        """Sample the CLR transfer function into an 8-bit VTK lookup table."""
        self.validate()
        positions = np.linspace(0, 100, count)
        stops = self.stops
        result = np.empty((count, 4), dtype=np.uint8)
        for index, position in enumerate(positions):
            exact = [s for s in stops if s.position == position]
            right = next((i for i, s in enumerate(stops) if s.position > position), len(stops))
            left = max(0, right - 1)
            right = min(right, len(stops) - 1)
            a, b = stops[left], stops[right]
            if exact:
                a = b = exact[-1]
            t = 0 if a.position == b.position else (position - a.position) / (b.position - a.position)
            if self.interpolation == 1:
                t = 1 - t
            elif self.interpolation == 2:
                t = (1 - math.cos(math.pi * t)) / 2
            elif self.interpolation == 3:
                t = 0
            elif self.interpolation == 4:
                t = 0.5
            elif self.interpolation == 5:
                t = 1
            rgb_a = tuple(int(a.color[j:j + 2], 16) for j in (1, 3, 5))
            rgb_b = tuple(int(b.color[j:j + 2], 16) for j in (1, 3, 5))
            if self.interpolation >= 6:
                h1, l1, s1 = colorsys.rgb_to_hls(*(v / 255 for v in rgb_a))
                h2, l2, s2 = colorsys.rgb_to_hls(*(v / 255 for v in rgb_b))
                clockwise = (h2 - h1) % 1
                delta = {6: clockwise, 7: clockwise - 1,
                         8: clockwise if clockwise <= 0.5 else clockwise - 1,
                         9: clockwise if clockwise > 0.5 else clockwise - 1}[self.interpolation]
                rgb = colorsys.hls_to_rgb((h1 + delta * t) % 1, l1 + (l2 - l1) * t,
                                           s1 + (s2 - s1) * t)
                result[index, :3] = np.rint(np.asarray(rgb) * 255).astype(np.uint8)
            else:
                result[index, :3] = np.rint(np.asarray(rgb_a) * (1 - t) + np.asarray(rgb_b) * t).astype(np.uint8)
            alpha = a.alpha * (1 - t) + b.alpha * t
            if self.opacity_stops:
                alpha *= np.interp(position, [s.position for s in self.opacity_stops],
                                   [s.opacity for s in self.opacity_stops]) / 100
            result[index, 3] = round(alpha)
        return result


def load_surfer_clr(path, field, minimum, maximum):
    """Read Surfer CLR versions 1–3; all anchors are embedded in the project."""
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("Файл палитры слишком большой.")
    lines = [line.split() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not lines or len(lines[0]) < 3 or lines[0][0] != "ColorMap":
        raise ValueError("Это не файл палитры Surfer CLR.")
    try:
        version, method = int(lines[0][1]), int(lines[0][2])
        if version not in (1, 2, 3):
            raise ValueError("Поддерживаются палитры CLR версий 1–3.")
        if version == 3:
            if len(lines[0]) != 5:
                raise ValueError("Неверный заголовок CLR 3.")
            ncolors, nopacity = map(int, lines[0][3:])
            if ncolors < 2 or ncolors > 10000 or nopacity < 0 or nopacity > 10000 or len(lines) != 1 + ncolors + nopacity:
                raise ValueError("Число узлов не совпадает с заголовком CLR.")
            color_lines = lines[1:1 + ncolors]
            opacity_lines = lines[1 + ncolors:]
        else:
            if len(lines[0]) != 3:
                raise ValueError("Неверный заголовок CLR.")
            color_lines, opacity_lines = lines[1:], []
        expected = 4 if version == 1 else 5
        if any(len(line) != expected for line in color_lines) or any(len(line) != 2 for line in opacity_lines):
            raise ValueError("Неверный формат узлов CLR.")
        stops = []
        for line in color_lines:
            position = float(line[0])
            channels = [int(v) for v in line[1:]]
            if any(not 0 <= v <= 255 for v in channels):
                raise ValueError("Цветовые каналы CLR должны быть от 0 до 255.")
            stops.append(ColorStop(position, "#{:02x}{:02x}{:02x}".format(*channels[:3]),
                                   channels[3] if version > 1 else 255))
        opacity = tuple(OpacityStop(float(p), float(v)) for p, v in opacity_lines)
        palette = ColorMap(field, minimum, maximum, tuple(stops), method, opacity)
        palette.validate()
        return palette
    except (IndexError, TypeError, OverflowError) as error:
        raise ValueError("Некорректный файл палитры CLR.") from error
