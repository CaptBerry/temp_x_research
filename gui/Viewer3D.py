from PyQt6.QtWidgets import QWidget, QVBoxLayout
from pyvistaqt import QtInteractor

import numpy as np
import pyvista as pv


class Viewer3D(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        # словарь акторов
        self.actors = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plotter = QtInteractor(self)

        layout.addWidget(self.plotter)

        self.init_view()

    def init_view(self):
        self.plotter.set_background("black")

        self.plotter.show_axes()

        self.plotter.enable_anti_aliasing()

        # self.demo()

    def demo(self):

        x = np.linspace(-10, 10, 80)
        y = np.linspace(-10, 10, 80)

        x, y = np.meshgrid(x, y)

        z = np.sin(x) * np.cos(y)

        mesh = pv.StructuredGrid(x, y, z)

        self.plotter.add_mesh(
            mesh,
            show_edges=True,
            smooth_shading=True,
        )

        self.plotter.reset_camera()

    def add_object(self, obj):
        if hasattr(obj, "mesh"):
            self.plotter.add_mesh(obj.mesh)

    def add_mesh(self, mesh):
        self.plotter.add_mesh(
            mesh,
            show_edges=True
        )
