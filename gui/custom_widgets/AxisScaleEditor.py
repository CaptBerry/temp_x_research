"""Project-wide coordinate axis scale controls."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDoubleSpinBox, QFormLayout, QGroupBox, QPushButton


class AxisScaleEditor(QGroupBox):
    scaleChanged = pyqtSignal(float, float, float)

    def __init__(self, parent=None):
        super().__init__("Масштаб осей проекта", parent)
        self._loading = False
        layout = QFormLayout(self)
        self.spins = {}
        for axis in "xyz":
            spin = QDoubleSpinBox()
            spin.setRange(0.001, 10000)
            spin.setDecimals(3)
            spin.setSingleStep(0.1)
            spin.setSuffix(" ×")
            spin.setKeyboardTracking(False)
            spin.setToolTip("1× — исходный масштаб координатной оси.")
            spin.valueChanged.connect(self._changed)
            self.spins[axis] = spin
            layout.addRow(axis.upper(), spin)
        self.reset_button = QPushButton("Сбросить масштаб осей")
        self.reset_button.clicked.connect(lambda: self.scaleChanged.emit(1, 1, 1))
        layout.addRow(self.reset_button)
        self.set_project(None)

    def set_project(self, project):
        self._loading = True
        try:
            self.setEnabled(project is not None)
            scale = project.axis_scale if project is not None else (1, 1, 1)
            for axis, value in zip("xyz", scale):
                self.spins[axis].setValue(value)
        finally:
            self._loading = False

    def _changed(self, *args):
        if not self._loading:
            self.scaleChanged.emit(*(self.spins[axis].value() for axis in "xyz"))
