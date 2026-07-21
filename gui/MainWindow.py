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

        points_csv = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "example_points.csv"
        )
        points = Points.from_csv(
            points_csv,
            x_column=0,
            y_column=1,
            z_column=2,
            name="CSV test points",
            skip_header=1
        )

        points_renderer = PointsRenderer()
        points_mesh = points_renderer.render(points)

        self.viewer.add_points(points_mesh, color="red")
        self.viewer.focus_on_scene()

