import numpy as np

from models.points import Points
from models.surface import Surface
from renderers.points_renderer import PointsRenderer
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

        points = Points(
            [
                [0.0, 0.0, 0.3],
                [0.4, 0.2, 0.6],
                [0.8, 0.7, 0.4],
                [0.2, 0.9, 0.7],
            ],
            "Test points"
        )

        points_renderer = PointsRenderer()
        points_mesh = points_renderer.render(points)

        self.viewer.add_points(points_mesh, color="red")

