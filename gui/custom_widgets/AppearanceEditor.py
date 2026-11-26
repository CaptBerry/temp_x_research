from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from models.Appearance import Appearance


class AppearanceEditor(QGroupBox):
    appearanceChanged = pyqtSignal(str, dict)
    paletteRequested = pyqtSignal(str)
    displayGridChanged = pyqtSignal(str, dict)

    MODE_LABELS = {
        "points": "Точки", "spheres": "Сферы",
        "surface": "Поверхность", "wireframe": "Каркас",
        "cells": "Объёмные ячейки",
        "corner_grid": "Corner-point grid", "grid_wireframe": "Каркас corner-point grid",
    }

    def __init__(self, parent=None):
        super().__init__("Отображение", parent)
        self._loading = False
        self._object_id = None
        self._object_type = None
        self._appearance = None
        layout = QVBoxLayout(self)
        self.selection_label = QLabel()
        self.selection_label.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)
        self.fields = QWidget()
        form = QFormLayout(self.fields)
        form.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.fields)

        self.mode_combo = QComboBox()
        self.shape_combo = QComboBox()
        self.shape_combo.addItem("Круг", "circle")
        self.shape_combo.addItem("Квадрат", "square")
        self.color_button = QPushButton()
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(1, 64)
        self.size_spin.setDecimals(1)
        self.size_spin.setSuffix(" px")
        self.size_spin.setKeyboardTracking(False)
        self.size_spin.setToolTip("Диаметр заливки точки. Обводка добавляется снаружи.")
        self.outline_check = QCheckBox("Показывать")
        self.outline_label = QLabel("Обводка")
        self.outline_color_button = QPushButton()
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.5, 20)
        self.width_spin.setDecimals(1)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setSuffix(" px")
        self.width_spin.setKeyboardTracking(False)
        self.width_label = QLabel("Толщина обводки")
        self.transparency_spin = QDoubleSpinBox()
        self.transparency_spin.setRange(0, 100)
        self.transparency_spin.setDecimals(1)
        self.transparency_spin.setSuffix(" %")
        self.transparency_spin.setKeyboardTracking(False)
        self.transparency_spin.setToolTip("0% — непрозрачно, 100% — полностью прозрачно.")
        self.reset_button = QPushButton("Сбросить настройки")
        self.palette_button = QPushButton("Настроить палитру…")
        self.clear_palette_button = QPushButton("Отключить палитру")
        form.addRow("Режим", self.mode_combo)
        form.addRow("Форма точки", self.shape_combo)
        form.addRow("Цвет", self.color_button)
        form.addRow("Палитра", self.palette_button)
        form.addRow(self.clear_palette_button)
        form.addRow("Размер точки", self.size_spin)
        form.addRow(self.outline_label, self.outline_check)
        form.addRow("Цвет обводки", self.outline_color_button)
        form.addRow(self.width_label, self.width_spin)
        form.addRow("Прозрачность", self.transparency_spin)
        form.addRow(self.reset_button)
        self.label_group = QGroupBox("Подписи скважин")
        label_form = QFormLayout(self.label_group)
        self.label_visible_check = QCheckBox("Показывать")
        self.label_color_button = QPushButton()
        self.label_font_combo = QComboBox()
        for caption, family in (("Arial", "arial"), ("Times", "times"),
                                ("Courier", "courier")):
            self.label_font_combo.addItem(caption, family)
        self.label_size_spin = QSpinBox()
        self.label_size_spin.setRange(8, 72)
        self.label_size_spin.setSuffix(" px")
        label_form.addRow("Подпись", self.label_visible_check)
        label_form.addRow("Цвет", self.label_color_button)
        label_form.addRow("Шрифт", self.label_font_combo)
        label_form.addRow("Размер", self.label_size_spin)
        layout.addWidget(self.label_group)
        self.grid_group = QGroupBox("Сетка отображения")
        grid_form = QFormLayout(self.grid_group)
        self.grid_form = grid_form
        self.grid_z_direction = QComboBox()
        self.grid_z_direction.addItem("Высоты: Z вверх", "up")
        self.grid_z_direction.addItem("Глубины: Z вниз", "down")
        grid_form.addRow("Направление Z", self.grid_z_direction)
        self.grid_method = QComboBox()
        self.grid_method.addItem("Интерполяция IDW", "interpolate")
        self.grid_method.addItem("Отдельные ячейки у точек", "samples")
        self.grid_method.addItem("Равномерная сетка", "uniform")
        grid_form.addRow("Построение", self.grid_method)
        self.grid_radius = QDoubleSpinBox()
        self.grid_radius.setRange(0, 1e9)
        self.grid_radius.setDecimals(4)
        self.grid_radius.setSpecialValueText("Авто")
        self.grid_radius.setKeyboardTracking(False)
        self.grid_radius.setToolTip(
            "Радиус в единицах координат. Для интервалов расстояние считается в XY, "
            "для объёмных XYZ — в 3D. 0 — подобрать автоматически.")
        grid_form.addRow("Радиус интерполяции", self.grid_radius)
        self.grid_size_spins = []
        self.grid_dimension_spins = []
        for axis in "XYZ":
            size = QDoubleSpinBox()
            size.setRange(0, 1e9)
            size.setDecimals(4)
            size.setSpecialValueText("Авто")
            size.setKeyboardTracking(False)
            size.setToolTip("Размер в единицах координат. 0 — определить по расстояниям между точками.")
            grid_form.addRow(f"Размер {axis}", size)
            self.grid_size_spins.append(size)
        for axis in "XYZ":
            count = QSpinBox()
            count.setRange(0, 256)
            count.setSpecialValueText("Авто")
            grid_form.addRow(f"Ячеек по {axis}", count)
            self.grid_dimension_spins.append(count)
        self.grid_hint = QLabel()
        self.grid_hint.setWordWrap(True)
        grid_form.addRow(self.grid_hint)
        self.grid_apply = QPushButton("Построить / перестроить")
        grid_form.addRow(self.grid_apply)
        layout.addWidget(self.grid_group)
        self._grid_intervals = False
        self.grid_method.currentIndexChanged.connect(self._sync_grid_controls)
        self.grid_z_direction.currentIndexChanged.connect(self._apply_z_direction)
        self.grid_apply.clicked.connect(self._apply_grid)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.shape_combo.currentIndexChanged.connect(self._changed)
        self.size_spin.valueChanged.connect(self._changed)
        self.outline_check.toggled.connect(self._changed)
        self.width_spin.valueChanged.connect(self._changed)
        self.transparency_spin.valueChanged.connect(self._changed)
        self.color_button.clicked.connect(lambda: self._choose_color(self.color_button, "Цвет объекта"))
        self.outline_color_button.clicked.connect(
            lambda: self._choose_color(self.outline_color_button, "Цвет обводки"))
        self.label_visible_check.toggled.connect(self._label_changed)
        self.label_font_combo.currentIndexChanged.connect(self._label_changed)
        self.label_size_spin.valueChanged.connect(self._label_changed)
        self.label_color_button.clicked.connect(
            lambda: self._choose_color(self.label_color_button, "Цвет подписи", self._label_changed))
        self.reset_button.clicked.connect(self._reset)
        self.palette_button.clicked.connect(lambda: self.paletteRequested.emit(self._object_id))
        self.clear_palette_button.clicked.connect(self._clear_palette)
        self.set_object(None)

    @staticmethod
    def _set_color(button, color):
        swatch = QPixmap(18, 18)
        swatch.fill(QColor(color))
        button.setIcon(QIcon(swatch))
        button.setText(color.upper())
        button.setProperty("color", color)

    def set_object(self, obj):
        self._loading = True
        try:
            supported = obj is not None and hasattr(obj, "appearance")
            self._object_id = obj.uuid if supported else None
            self._object_type = obj.TYPE if supported else None
            self.fields.setEnabled(supported)
            self.label_group.setVisible(supported and obj.TYPE in ("well", "wellfile"))
            self.grid_group.setVisible(supported and hasattr(obj, "display_grid"))
            self.selection_label.setText(obj.name if supported else "Выберите объект в дереве.")
            self.mode_combo.clear()
            if not supported:
                self.hint.clear()
                return
            if hasattr(obj, "display_grid"):
                self._grid_intervals = obj.has_intervals
                self.grid_z_direction.setCurrentIndex(self.grid_z_direction.findData(obj.display_grid.z_direction))
                self.grid_method.setCurrentIndex(self.grid_method.findData(obj.display_grid.method))
                self.grid_radius.setValue(obj.display_grid.interpolation_radius)
                for spin, value in zip(self.grid_size_spins, obj.display_grid.cell_size):
                    spin.setValue(value)
                for spin, value in zip(self.grid_dimension_spins, obj.display_grid.dimensions):
                    spin.setValue(value)
                self._sync_grid_controls()
            modes = Appearance.modes(obj.TYPE)
            if obj.TYPE == "cube" and obj.is_corner_point:
                modes = ("points", "spheres", "surface", "wireframe")
            if obj.TYPE == "cube" and not obj.is_corner_point:
                modes = ("points", "spheres", "cells")
            if obj.TYPE == "pointcloud" and obj.cell_edges() is None:
                modes = ("points", "spheres")
            if obj.TYPE == "cube" and not obj.is_corner_point and obj.cell_edges() is None:
                modes = ("points", "spheres")
            for mode in modes:
                label = "Траектория" if obj.TYPE in ("well", "wellfile") and mode == "wireframe" else self.MODE_LABELS[mode]
                self.mode_combo.addItem(label, mode)
            appearance = obj.appearance
            self._appearance = appearance
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(appearance.mode))
            self.shape_combo.setCurrentIndex(self.shape_combo.findData(appearance.point_shape))
            self.size_spin.setValue(appearance.point_size)
            self.outline_check.setChecked(self._outline_for_mode(appearance, appearance.mode))
            self.width_spin.setValue(appearance.line_width)
            self.transparency_spin.setValue((1 - appearance.opacity) * 100)
            self._set_color(self.color_button, appearance.color)
            self.clear_palette_button.setEnabled(appearance.color_map is not None)
            self.color_button.setEnabled(appearance.color_map is None)
            self.palette_button.setText("Изменить палитру…" if appearance.color_map else "Настроить палитру…")
            self._set_color(self.outline_color_button, appearance.outline_color)
            if obj.TYPE in ("well", "wellfile"):
                self.label_visible_check.setChecked(appearance.label_visible)
                self._set_color(self.label_color_button, appearance.label_color)
                self.label_font_combo.setCurrentIndex(self.label_font_combo.findData(appearance.label_font))
                self.label_size_spin.setValue(appearance.label_size)
                self._sync_label_controls()
            self._sync_controls()
        finally:
            self._loading = False

    def _sync_controls(self):
        mode = self.mode_combo.currentData()
        self.outline_label.setText("Обводка призм" if mode in ("cells", "corner_grid") else "Обводка")
        self.outline_check.setToolTip(
            "Обводка призм сохраняется отдельно от обводки точек, включая перестроение и открытие проекта."
            if mode in ("cells", "corner_grid") else "")
        self.shape_combo.setEnabled(mode == "points")
        self.size_spin.setEnabled(mode in ("points", "spheres"))
        supports_outline = mode in ("points", "surface", "cells", "corner_grid")
        self.outline_check.setEnabled(supports_outline)
        outlined = supports_outline and self.outline_check.isChecked()
        self.outline_color_button.setEnabled(outlined)
        self.width_spin.setEnabled(outlined or mode in ("wireframe", "grid_wireframe"))
        self.width_label.setText("Толщина линий" if mode in ("wireframe", "grid_wireframe") else "Толщина обводки")
        self.hint.setText("Обводка доступна в режиме «Точки»." if mode == "spheres" else "")

    @staticmethod
    def _outline_for_mode(appearance, mode):
        if mode in ("cells", "corner_grid") and appearance.prism_outline is not None:
            return appearance.prism_outline
        return appearance.outline

    def _mode_changed(self):
        if self._loading or self._object_id is None:
            return
        self._loading = True
        try:
            self.outline_check.setChecked(self._outline_for_mode(
                self._appearance, self.mode_combo.currentData()))
        finally:
            self._loading = False
        self._changed()

    def _sync_grid_controls(self):
        samples = self.grid_method.currentData() == "samples"
        interpolate = self.grid_method.currentData() == "interpolate"
        self.grid_form.setRowVisible(self.grid_radius, interpolate)
        for axis, spin in enumerate(self.grid_size_spins):
            spin.setEnabled(samples and (axis != 2 or not self._grid_intervals))
            self.grid_form.setRowVisible(spin, samples and (axis != 2 or not self._grid_intervals))
        for axis, spin in enumerate(self.grid_dimension_spins):
            spin.setEnabled(not samples and (axis != 2 or not self._grid_intervals))
            self.grid_form.setRowVisible(spin, not samples and (axis != 2 or not self._grid_intervals))
        text = ("Каждая точка задаёт центр своей ячейки. Значения не усредняются."
                if samples else "Точки в одной ячейке усредняются только для отображения.")
        if interpolate:
            text = ("Связанная сетка с общими углами. IDW использует до 32 ближайших точек "
                    "в заданном радиусе; вне радиуса ячейки не строятся.")
        if self._grid_intervals:
            text += (" Кровля и подошва интерполируются в общих узлах; слои не смешиваются."
                     if interpolate else " Высота берётся из кровли и подошвы; слои не смешиваются.")
        self.grid_hint.setText(text)

    def _apply_grid(self):
        if not self._loading and self._object_id is not None:
            self.displayGridChanged.emit(self._object_id, {
                "method": self.grid_method.currentData(),
                "cell_size": tuple(spin.value() for spin in self.grid_size_spins),
                "dimensions": tuple(spin.value() for spin in self.grid_dimension_spins),
                "z_direction": self.grid_z_direction.currentData(),
                "interpolation_radius": self.grid_radius.value(),
            })

    def _apply_z_direction(self):
        if not self._loading and self._object_id is not None:
            self.displayGridChanged.emit(self._object_id, {
                "z_direction": self.grid_z_direction.currentData(),
            })

    def _changed(self, *args):
        if self._loading or self._object_id is None:
            return
        self._sync_controls()
        changes = {
            "mode": self.mode_combo.currentData(),
            "point_shape": self.shape_combo.currentData(),
            "color": self.color_button.property("color"),
            "point_size": self.size_spin.value(),
            "outline_color": self.outline_color_button.property("color"),
            "line_width": self.width_spin.value(),
            "opacity": 1 - self.transparency_spin.value() / 100,
        }
        changes["prism_outline" if changes["mode"] in ("cells", "corner_grid") else "outline"] = self.outline_check.isChecked()
        self.appearanceChanged.emit(self._object_id, changes)

    def _sync_label_controls(self):
        enabled = self.label_visible_check.isChecked()
        for widget in (self.label_color_button, self.label_font_combo, self.label_size_spin):
            widget.setEnabled(enabled)

    def _label_changed(self, *args):
        if self._loading or self._object_id is None:
            return
        self._sync_label_controls()
        self.appearanceChanged.emit(self._object_id, {
            "label_visible": self.label_visible_check.isChecked(),
            "label_color": self.label_color_button.property("color"),
            "label_font": self.label_font_combo.currentData(),
            "label_size": self.label_size_spin.value(),
        })

    def _choose_color(self, button, title, on_change=None):
        color = QColorDialog.getColor(QColor(button.property("color")), self, title)
        if color.isValid():
            self._set_color(button, color.name())
            (on_change or self._changed)()

    def _reset(self):
        if self._object_id is not None:
            appearance = (Appearance(mode="surface", outline=True)
                          if self._object_type == "cube" and self.mode_combo.findData("surface") >= 0
                          else Appearance.default(self._object_type))
            self.appearanceChanged.emit(self._object_id, appearance.to_dict())

    def _clear_palette(self):
        if self._object_id is not None:
            self.appearanceChanged.emit(self._object_id, {"color_map": None})
