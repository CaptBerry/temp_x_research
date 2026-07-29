from PyQt6.QtWidgets import QWidget, QVBoxLayout
from pyvistaqt import QtInteractor

import numpy as np
import pyvista as pv

from scene.camera import SceneCamera


class Viewer3D(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        # словарь акторов
        self.actors = {}

        self.camera = SceneCamera()
        self.scene_bounds = None

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

    def add_mesh(self, mesh, **kwargs):
        actor = self.plotter.add_mesh(
            mesh,
            show_edges=True,
            **kwargs
        )
        self.include_bounds(mesh.bounds)

        return actor

    def add_points(self, points, radius=0.03, **kwargs):
        spheres = points.glyph(
            geom=pv.Sphere(radius=radius),
            scale=False,
            orient=False
        )

        actor = self.plotter.add_mesh(
            spheres,
            smooth_shading=True,
            **kwargs
        )
        self.include_bounds(spheres.bounds)

        return actor

    def include_bounds(self, bounds):

        if self.scene_bounds is None:
            self.scene_bounds = tuple(bounds)
            return

        self.scene_bounds = (
            min(self.scene_bounds[0], bounds[0]),
            max(self.scene_bounds[1], bounds[1]),
            min(self.scene_bounds[2], bounds[2]),
            max(self.scene_bounds[3], bounds[3]),
            min(self.scene_bounds[4], bounds[4]),
            max(self.scene_bounds[5], bounds[5])
        )

    def focus_on_scene(self):

        self.camera.focus_on_bounds(
            self.plotter,
            self.scene_bounds
        )
