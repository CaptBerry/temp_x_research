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

    MODE_LABELS = {
        "points": "Точки", "spheres": "Сферы",
        "surface": "Поверхность", "wireframe": "Каркас",
    }

    def __init__(self, parent=None):
        super().__init__("Отображение", parent)
        self._loading = False
        self._object_id = None
        self._object_type = None
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
        form.addRow("Обводка", self.outline_check)
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
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.mode_combo.currentIndexChanged.connect(self._changed)
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
            self.selection_label.setText(obj.name if supported else "Выберите объект в дереве.")
            self.mode_combo.clear()
            if not supported:
                self.hint.clear()
                return
            modes = Appearance.modes(obj.TYPE)
            if obj.TYPE == "cube" and not obj.is_corner_point:
                modes = ("points", "spheres")
            for mode in modes:
                label = "Траектория" if obj.TYPE in ("well", "wellfile") and mode == "wireframe" else self.MODE_LABELS[mode]
                self.mode_combo.addItem(label, mode)
            appearance = obj.appearance
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(appearance.mode))
            self.shape_combo.setCurrentIndex(self.shape_combo.findData(appearance.point_shape))
            self.size_spin.setValue(appearance.point_size)
            self.outline_check.setChecked(appearance.outline)
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
        self.shape_combo.setEnabled(mode == "points")
        self.size_spin.setEnabled(mode in ("points", "spheres"))
        supports_outline = mode in ("points", "surface")
        self.outline_check.setEnabled(supports_outline)
        outlined = supports_outline and self.outline_check.isChecked()
        self.outline_color_button.setEnabled(outlined)
        self.width_spin.setEnabled(outlined or mode == "wireframe")
        self.width_label.setText("Толщина линий" if mode == "wireframe" else "Толщина обводки")
        self.hint.setText("Обводка доступна в режиме «Точки»." if mode == "spheres" else "")

    def _changed(self, *args):
        if self._loading or self._object_id is None:
            return
        self._sync_controls()
        self.appearanceChanged.emit(self._object_id, {
            "mode": self.mode_combo.currentData(),
            "point_shape": self.shape_combo.currentData(),
            "color": self.color_button.property("color"),
            "point_size": self.size_spin.value(),
            "outline": self.outline_check.isChecked(),
            "outline_color": self.outline_color_button.property("color"),
            "line_width": self.width_spin.value(),
            "opacity": 1 - self.transparency_spin.value() / 100,
        })

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
