import numpy as np

from models.surface import Surface
from renderers.surface_renderer import SurfaceRenderer

from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout

from gui.Viewer3D import Viewer3D


class MainWindow(QMainWindow):

    viewerWidget: QWidget

    def __init__(self):
        super().__init__()

        ui = Path(__file__).with_name("MainWindow.ui")
        uic.loadUi(ui, self)

        self.viewer = Viewer3D()

        layout = QVBoxLayout(self.viewerWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewer)

        vertices = np.array([
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
        ])

        faces = np.array([
            4, 0, 1, 2, 3
        ])

        surface = Surface(
            vertices,
            faces,
            "Test surface"
        )

        renderer = SurfaceRenderer()

        mesh = renderer.render(surface)

        self.viewer.add_mesh(mesh)

