"""Edit a Surfer-style palette and its data range."""

from dataclasses import replace
import math
import numpy as np

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPolygonF
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QListWidget, QMessageBox,
    QPushButton, QVBoxLayout, QWidget, QColorDialog,
    QSlider,
)

from models.ColorMap import ColorMap, ColorStop, load_surfer_clr


INTERPOLATIONS = ("Линейная", "Обратная", "Косинусная", "Ступень: начало",
                  "Ступень: середина", "Ступень: конец", "HSL по часовой",
                  "HSL против часовой", "HSL кратчайшая", "HSL длиннейшая")


class GradientStrip(QWidget):
    stopSelected = pyqtSignal(int)
    stopMoved = pyqtSignal(int, float)

    def __init__(self):
        super().__init__()
        self.palette = None
        self.selected = 0
        self.dragging = False
        self.setMinimumHeight(76)

    def _bounds(self):
        return 12, max(1, self.width() - 24)

    def paintEvent(self, event):
        if self.palette is None:
            return
        painter = QPainter(self)
        left, width = self._bounds()
        if self.palette.minimum >= self.palette.maximum:
            painter.end()
            return
        rgba = self.palette.rgba(max(2, width))
        for x, (r, g, b, a) in enumerate(rgba):
            painter.fillRect(left + x, 14, 1, 30, QColor(int(r), int(g), int(b), int(a)))
        painter.setPen(QColor("#333333"))
        painter.drawRect(left, 14, width, 30)
        for i, stop in enumerate(self.palette.stops):
            x = left + width * stop.position / 100
            painter.setBrush(QColor(stop.color))
            painter.setPen(QColor("#000000") if i == self.selected else QColor("#777777"))
            painter.drawPolygon(QPolygonF([QPointF(x, 48), QPointF(x - 7, 64), QPointF(x + 7, 64)]))
        painter.end()

    def mousePressEvent(self, event):
        if self.palette is None:
            return
        left, width = self._bounds()
        distances = [abs(event.position().x() - (left + width * s.position / 100))
                     for s in self.palette.stops]
        nearest = int(np.argmin(distances))
        if distances[nearest] <= 12:
            self.selected = nearest
            self.dragging = True
            self.stopSelected.emit(nearest)
            self.update()

    def mouseMoveEvent(self, event):
        if self.dragging:
            left, width = self._bounds()
            percent = max(0, min(100, (event.position().x() - left) * 100 / width))
            self.stopMoved.emit(self.selected, percent)

    def mouseReleaseEvent(self, event):
        self.dragging = False


class PaletteDialog(QDialog):
    def __init__(self, obj, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Палитра")
        self.resize(610, 480)
        self.obj = obj
        self.palette = obj.appearance.color_map
        self._loading = False
        fields = obj.numeric_fields()
        if not fields:
            raise ValueError("Объект не содержит числовых параметров для окраски.")
        if self.palette is None:
            if obj.TYPE in ("wellfile", "layered_cube"):
                excluded = {"x", "y", "z", "I", "J", "K", "N_POINTS",
                            "CENTER_X", "CENTER_Y", "CENTER_Z"}
                excluded.update(filter(None, (getattr(obj, "roof_column", None),
                                               getattr(obj, "base_column", None))))
                field = next((name for name in fields if name not in excluded), fields[0])
            else:
                field = obj.z_column if hasattr(obj, "z_column") and obj.z_column in fields else fields[0]
            values = obj.color_values(field)
            finite = values[np.isfinite(values)]
            minimum, maximum = float(finite.min()), float(finite.max())
            if minimum == maximum:
                minimum -= 0.5
                maximum += 0.5
            self.palette = ColorMap.default(field, minimum, maximum)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.field_combo = QComboBox()
        for field in fields:
            self.field_combo.addItem("Высота Z" if obj.TYPE == "surface" else field, field)
        self.minimum_spin = self._number_spin()
        self.maximum_spin = self._number_spin()
        self.minimum_slider = QSlider(Qt.Orientation.Horizontal)
        self.maximum_slider = QSlider(Qt.Orientation.Horizontal)
        self.minimum_slider.setRange(0, 1000)
        self.maximum_slider.setRange(0, 1000)
        self._slider_domain = (0, 1)
        minimum_row = QHBoxLayout()
        minimum_row.addWidget(self.minimum_slider, 2)
        minimum_row.addWidget(self.minimum_spin, 1)
        maximum_row = QHBoxLayout()
        maximum_row.addWidget(self.maximum_slider, 2)
        maximum_row.addWidget(self.maximum_spin, 1)
        self.interpolation_combo = QComboBox()
        self.interpolation_combo.addItems(INTERPOLATIONS)
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("Линейная", "linear")
        self.scale_combo.addItem("Логарифмическая (log10)", "log")
        self.scale_combo.setToolTip("Для логарифмической шкалы значения и пределы должны быть положительными.")
        form.addRow("Параметр", self.field_combo)
        form.addRow("Нижний предел", minimum_row)
        form.addRow("Верхний предел", maximum_row)
        form.addRow("Шкала значений", self.scale_combo)
        form.addRow("Интерполяция", self.interpolation_combo)
        layout.addLayout(form)
        self.gradient = GradientStrip()
        layout.addWidget(self.gradient)
        layout.addWidget(QLabel("Узлы: перетащите маркер, чтобы изменить его положение"))
        middle = QHBoxLayout()
        self.stop_list = QListWidget()
        middle.addWidget(self.stop_list, 2)
        detail = QFormLayout()
        self.position_spin = self._number_spin()
        self.position_spin.setRange(0, 100)
        self.position_spin.setDecimals(3)
        self.position_spin.setSuffix(" %")
        self.value_spin = self._number_spin()
        self.color_button = QPushButton("Выбрать цвет…")
        self.alpha_spin = QDoubleSpinBox()
        self.alpha_spin.setRange(0, 255)
        self.alpha_spin.setDecimals(0)
        self.alpha_spin.setToolTip("0 — прозрачный, 255 — непрозрачный")
        detail.addRow("Позиция", self.position_spin)
        detail.addRow("Значение", self.value_spin)
        detail.addRow("Цвет", self.color_button)
        detail.addRow("Непрозрачность", self.alpha_spin)
        detail_widget = QWidget()
        detail_widget.setLayout(detail)
        middle.addWidget(detail_widget, 3)
        layout.addLayout(middle)
        buttons = QHBoxLayout()
        load_button = QPushButton("Загрузить CLR…")
        add_button = QPushButton("Добавить узел")
        remove_button = QPushButton("Удалить узел")
        reset_button = QPushButton("Диапазон по данным")
        for button in (load_button, add_button, remove_button, reset_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(box)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        self.field_combo.currentIndexChanged.connect(self._field_changed)
        self.minimum_spin.valueChanged.connect(self._limits_changed)
        self.maximum_spin.valueChanged.connect(self._limits_changed)
        self.minimum_slider.valueChanged.connect(lambda n: self._slider_changed(n, True))
        self.maximum_slider.valueChanged.connect(lambda n: self._slider_changed(n, False))
        self.scale_combo.currentIndexChanged.connect(self._scale_changed)
        self.interpolation_combo.currentIndexChanged.connect(self._method_changed)
        self.stop_list.currentRowChanged.connect(self._select)
        self.gradient.stopSelected.connect(self.stop_list.setCurrentRow)
        self.gradient.stopMoved.connect(self._move_stop)
        self.position_spin.valueChanged.connect(self._position_changed)
        self.value_spin.valueChanged.connect(self._value_changed)
        self.alpha_spin.valueChanged.connect(self._alpha_changed)
        self.color_button.clicked.connect(self._choose_color)
        load_button.clicked.connect(self._load)
        add_button.clicked.connect(self._add)
        remove_button.clicked.connect(self._remove)
        reset_button.clicked.connect(self._reset_range)
        self._set_slider_domain()
        self._refresh(0)

    @staticmethod
    def _number_spin():
        spin = QDoubleSpinBox()
        spin.setRange(-1e15, 1e15)
        spin.setDecimals(15)
        spin.setKeyboardTracking(False)
        return spin

    def _refresh(self, selected=None):
        self._loading = True
        try:
            self.field_combo.setCurrentIndex(self.field_combo.findData(self.palette.field))
            logarithmic = self.palette.value_scale == "log"
            for spin in (self.minimum_spin, self.maximum_spin, self.value_spin):
                spin.setMinimum(1e-15 if logarithmic else -1e15)
            self.scale_combo.setCurrentIndex(self.scale_combo.findData(self.palette.value_scale))
            self.minimum_spin.setValue(self.palette.minimum)
            self.maximum_spin.setValue(self.palette.maximum)
            low, high = self._slider_domain
            self.minimum_slider.setValue(self._slider_index(self.palette.minimum))
            self.maximum_slider.setValue(self._slider_index(self.palette.maximum))
            self.interpolation_combo.setCurrentIndex(self.palette.interpolation)
            self.stop_list.clear()
            for stop in self.palette.stops:
                value = self.palette.value_at(stop.position)
                self.stop_list.addItem(f"{value:.8g}  ({stop.position:.3f}%)   {stop.color.upper()}")
            selected = min(selected if selected is not None else 0, len(self.palette.stops) - 1)
            self.stop_list.setCurrentRow(selected)
            self._select(selected)
            self.gradient.palette = self.palette
            self.gradient.selected = selected
            self.gradient.update()
        finally:
            self._loading = False

    def _select(self, index):
        if index < 0 or index >= len(self.palette.stops):
            return
        stop = self.palette.stops[index]
        self._loading = True
        self.position_spin.setValue(stop.position)
        value = self.palette.value_at(stop.position)
        self.value_spin.setValue(value)
        if self.palette.value_scale == "log":
            self.value_spin.setSingleStep(max(value * 0.1, 1e-15))
        self.alpha_spin.setValue(stop.alpha)
        movable = 0 < index < len(self.palette.stops) - 1
        self.position_spin.setEnabled(movable)
        self.value_spin.setEnabled(movable)
        self.color_button.setStyleSheet(f"background-color: {stop.color};")
        self.gradient.selected = index
        self.gradient.update()
        self._loading = False

    def _replace_stop(self, index, stop):
        stops = list(self.palette.stops)
        stops[index] = stop
        stops.sort(key=lambda s: s.position)
        selected = stops.index(stop)
        self.palette = replace(self.palette, stops=tuple(stops))
        self._refresh(selected)

    def _move_stop(self, index, position):
        if index in (0, len(self.palette.stops) - 1):
            return
        stop = self.palette.stops[index]
        self._replace_stop(index, replace(stop, position=position))

    def _position_changed(self, position):
        if not self._loading:
            self._move_stop(self.stop_list.currentRow(), position)

    def _value_changed(self, value):
        if not self._loading and self.palette.minimum < self.palette.maximum:
            percent = self.palette.position_of(value)
            self._move_stop(self.stop_list.currentRow(), max(0, min(100, percent)))

    def _alpha_changed(self, alpha):
        if not self._loading:
            index = self.stop_list.currentRow()
            self._replace_stop(index, replace(self.palette.stops[index], alpha=int(alpha)))

    def _choose_color(self):
        index = self.stop_list.currentRow()
        if index < 0:
            return
        color = QColorDialog.getColor(QColor(self.palette.stops[index].color), self, "Цвет узла")
        if color.isValid():
            self._replace_stop(index, replace(self.palette.stops[index], color=color.name()))

    def _field_changed(self):
        if not self._loading:
            field = self.field_combo.currentData()
            try:
                minimum, maximum = self._data_range(field, self.palette.value_scale)
            except ValueError as error:
                self._refresh(self.stop_list.currentRow())
                QMessageBox.warning(self, "Недоступная шкала", str(error))
                return
            self.palette = replace(self.palette, field=field, minimum=minimum, maximum=maximum)
            self._set_slider_domain()
            self._refresh(self.stop_list.currentRow())

    def _data_range(self, field, value_scale):
        values = self.obj.color_values(field)
        finite = values[np.isfinite(values)]
        if value_scale == "log":
            finite = finite[finite > 0]
        if len(finite) == 0:
            raise ValueError("Для логарифмической шкалы нужны положительные значения параметра.")
        minimum, maximum = float(finite.min()), float(finite.max())
        if minimum == maximum:
            if value_scale == "log":
                minimum /= math.sqrt(10)
                maximum *= math.sqrt(10)
            else:
                minimum -= 0.5
                maximum += 0.5
        return minimum, maximum

    def _scale_changed(self):
        if self._loading:
            return
        value_scale = self.scale_combo.currentData()
        if value_scale == "log":
            try:
                positive_minimum, positive_maximum = self._data_range(self.palette.field, value_scale)
            except ValueError as error:
                self._refresh(self.stop_list.currentRow())
                QMessageBox.warning(self, "Недоступная шкала", str(error))
                return
            minimum = self.palette.minimum if self.palette.minimum > 0 else positive_minimum
            maximum = max(self.palette.maximum, positive_maximum, minimum * (1 + 1e-12))
            self.palette = replace(self.palette, value_scale=value_scale,
                                   minimum=minimum, maximum=maximum)
        else:
            self.palette = replace(self.palette, value_scale=value_scale)
        self._set_slider_domain()
        self._refresh(self.stop_list.currentRow())

    def _set_slider_domain(self):
        values = self.obj.color_values(self.palette.field)
        finite = values[np.isfinite(values)]
        if self.palette.value_scale == "log":
            finite = finite[finite > 0]
            low = min(float(finite.min()), self.palette.minimum) if len(finite) else self.palette.minimum
            high = max(float(finite.max()), self.palette.maximum) if len(finite) else self.palette.maximum
            low_log, high_log = math.log10(low), math.log10(high)
            padding = max((high_log - low_log) * 0.1, 0.1)
            self._slider_domain = (10 ** max(-15, low_log - padding),
                                   10 ** min(15, high_log + padding))
            return
        low = min(float(finite.min()), self.palette.minimum)
        high = max(float(finite.max()), self.palette.maximum)
        padding = max((high - low) * 0.1, 0.5 if high == low else 0)
        self._slider_domain = (low - padding, high + padding)

    def _slider_index(self, value):
        low, high = self._slider_domain
        if self.palette.value_scale == "log":
            return round(1000 * (math.log10(value) - math.log10(low)) /
                         (math.log10(high) - math.log10(low)))
        return round(1000 * (value - low) / (high - low))

    def _slider_changed(self, index, lower):
        if not self._loading:
            low, high = self._slider_domain
            if self.palette.value_scale == "log":
                value = 10 ** (math.log10(low) + (math.log10(high) - math.log10(low)) * index / 1000)
            else:
                value = low + (high - low) * index / 1000
            (self.minimum_spin if lower else self.maximum_spin).setValue(value)

    def _limits_changed(self):
        if not self._loading:
            self.palette = replace(self.palette, minimum=self.minimum_spin.value(), maximum=self.maximum_spin.value())
            self._refresh(self.stop_list.currentRow())

    def _method_changed(self):
        if not self._loading:
            self.palette = replace(self.palette, interpolation=self.interpolation_combo.currentIndex())
            self.gradient.palette = self.palette
            self.gradient.update()

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Палитра Surfer", "", "Surfer CLR (*.clr *.CLR);;Все файлы (*)")
        if path:
            try:
                loaded = load_surfer_clr(path, self.field_combo.currentData(),
                                         self.minimum_spin.value(), self.maximum_spin.value())
                self.palette = replace(loaded, value_scale=self.palette.value_scale)
                self.palette.validate()
                self._refresh(0)
            except (OSError, UnicodeError, ValueError) as error:
                QMessageBox.warning(self, "Не удалось загрузить палитру", str(error))

    def _add(self):
        index = self.stop_list.currentRow()
        stops = list(self.palette.stops)
        if len(stops) >= 10000:
            return
        if index < 0:
            index = 0
        left = min(index, len(stops) - 2)
        position = (stops[left].position + stops[left + 1].position) / 2
        color = stops[left].color
        new_stop = ColorStop(position, color)
        stops.append(new_stop)
        stops.sort(key=lambda s: s.position)
        self.palette = replace(self.palette, stops=tuple(stops))
        self._refresh(stops.index(new_stop))

    def _remove(self):
        index = self.stop_list.currentRow()
        if 0 < index < len(self.palette.stops) - 1 and len(self.palette.stops) > 2:
            stops = list(self.palette.stops)
            stops.pop(index)
            self.palette = replace(self.palette, stops=tuple(stops))
            self._refresh(min(index, len(stops) - 2))

    def _reset_range(self):
        minimum, maximum = self._data_range(self.palette.field, self.palette.value_scale)
        self.palette = replace(self.palette, minimum=minimum, maximum=maximum)
        self._set_slider_domain()
        self._refresh(self.stop_list.currentRow())

    def _accept(self):
        try:
            self.palette.validate()
            self.obj.color_values(self.palette.field)
        except ValueError as error:
            QMessageBox.warning(self, "Некорректная палитра", str(error))
            return
        self.accept()
