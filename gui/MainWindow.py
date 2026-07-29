from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout

from gui.Viewer3D import Viewer3D
from models.points import Points
from models.surface import Surface
from renderers.points_renderer import PointsRenderer
from renderers.surface_renderer import SurfaceRenderer
from scene.project import SceneProject


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

        project_path = (
            Path(__file__).resolve().parents[1]
            / "projects"
            / "example_project.json"
        )
        self.open_project(project_path)

    def open_project(self, project_path):

        self.project = SceneProject.from_file(project_path)
        self.scene = self.project.to_scene()

        for obj in self.scene.objects:
            self.add_scene_object(obj)

        self.viewer.focus_on_scene()
        self.scene.camera = self.viewer.camera
        self.project.camera = self.viewer.camera

    def add_scene_object(self, obj):

        if isinstance(obj, Surface):
            renderer = SurfaceRenderer()
            mesh = renderer.render(obj)
            self.viewer.add_mesh(mesh)
            return

        if isinstance(obj, Points):
            renderer = PointsRenderer()
            mesh = renderer.render(obj)
            self.viewer.add_points(mesh, color="red")
            return

        raise ValueError(f"Unsupported scene object class: {obj.__class__.__name__}")

    def save_project(self, project_path=None):

        self.viewer.camera.save_from_plotter(self.viewer.plotter)
        self.project.camera = self.viewer.camera
        self.project.save(project_path)
