"""Project-wide coordinate axes and scale settings."""

from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QLabel, QPushButton, QSpinBox, QVBoxLayout,
)


class AxisSettingsDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка осей")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Деления показывают исходные координаты. Множители меняют "
            "пропорции всей 3D-сцены, не изменяя данные.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        display_group = QGroupBox("Координатные оси")
        display_layout = QVBoxLayout(display_group)
        self.axes_check = QCheckBox("Показывать оси и числовые деления")
        self.grid_check = QCheckBox("Показывать координатную сетку")
        self.axes_check.setChecked(project.axes_visible)
        self.grid_check.setChecked(project.axes_grid_visible)
        self.grid_check.setEnabled(project.axes_visible)
        self.axes_check.toggled.connect(self.grid_check.setEnabled)
        display_layout.addWidget(self.axes_check)
        display_layout.addWidget(self.grid_check)
        self.round_grid_check = QCheckBox("Округлять границы до круглых чисел")
        self.round_grid_check.setChecked(project.axes_round_grid)
        self.round_grid_check.setToolTip(
            "Границы и шаг делений подбираются как 1, 2 или 5 × 10ⁿ; данные не меняются.")
        display_layout.addWidget(self.round_grid_check)
        rounding_form = QFormLayout()
        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(0, 9)
        self.decimals_spin.setValue(project.axes_label_decimals)
        rounding_form.addRow("Знаков после запятой", self.decimals_spin)
        display_layout.addLayout(rounding_form)
        layout.addWidget(display_group)

        scale_group = QGroupBox("Множители масштаба")
        scale_form = QFormLayout(scale_group)
        self.spins = {}
        for axis, value in zip("xyz", project.axis_scale):
            spin = QDoubleSpinBox()
            spin.setRange(0.001, 10000)
            spin.setDecimals(3)
            spin.setSingleStep(0.1)
            spin.setSuffix(" ×")
            spin.setKeyboardTracking(False)
            spin.setValue(value)
            self.spins[axis] = spin
            scale_form.addRow(axis.upper(), spin)
        reset_button = QPushButton("Сбросить множители")
        reset_button.clicked.connect(self._reset_scale)
        scale_form.addRow(reset_button)
        layout.addWidget(scale_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def axis_scale(self):
        return tuple(self.spins[axis].value() for axis in "xyz")

    def _reset_scale(self):
        for spin in self.spins.values():
            spin.setValue(1)
