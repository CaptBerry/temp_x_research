from contextlib import contextmanager

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from pyvistaqt import QtInteractor
import logging

import numpy as np
import pyvista as pv

from scene.camera import SceneCamera
from models.PointCloud import PointCloud
from models.DataCube import DataCube
from models.Surface import Surface
from models.Well import Well
from renderers.surface_renderer import SurfaceRenderer
from renderers.corner_point_renderer import render_corner_point_grid
from renderers.appearance import apply_appearance, apply_color_map, set_point_viewport


logger = logging.getLogger(__name__)


class Viewer3D(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        # словарь акторов
        self.actors = {}

        self.camera = SceneCamera()
        self.scene_bounds = None
        self.axis_scale = (1.0, 1.0, 1.0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plotter = QtInteractor(self)
        self._last_viewport = None
        self._render_observer = self.plotter.render_window.AddObserver("StartEvent", self._update_point_viewport)

        layout.addWidget(self.plotter)

        self.init_view()

    def init_view(self):
        self.plotter.set_background("white")

        self.plotter.show_axes()

        # FXAA keeps the render viewport in screen pixels, as used by the
        # marker size/outline shader. SSAA renders to a larger intermediate FBO.
        self.plotter.enable_anti_aliasing("fxaa")

        # Intersecting translucent meshes cannot be composited correctly by
        # actor draw order. Depth peeling sorts the fragments at each pixel.
        if not self.plotter.enable_depth_peeling(number_of_peels=16, occlusion_ratio=0):
            logger.warning("Глубинная сортировка прозрачности недоступна для текущего OpenGL-контекста")

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

    def clear_scene(self):
        self.plotter.clear()
        self.plotter.show_axes()
        self.actors.clear()
        self.scene_bounds = None

    @contextmanager
    def scene_update(self):
        """Keep the previous frame visible until the whole scene is ready."""
        was_suppressed = self.plotter.suppress_rendering
        updates_enabled = self.plotter.updatesEnabled()
        self.plotter.suppress_rendering = True
        self.plotter.setUpdatesEnabled(False)
        completed = False
        try:
            yield
            completed = True
        finally:
            self.plotter.suppress_rendering = was_suppressed
            self.plotter.setUpdatesEnabled(updates_enabled)
            if completed and not was_suppressed and updates_enabled:
                self.plotter.render()


    def add_object(self, obj):
        if isinstance(obj, Well):
            return self.add_well(obj)
        if isinstance(obj, DataCube) and obj.is_corner_point:
            return self.add_corner_point_cube(obj)
        if isinstance(obj, PointCloud):
            return self.add_point_cloud(obj)
        if isinstance(obj, Surface) and len(obj.vertices):
            mesh = SurfaceRenderer().render(obj)
            actor = self.add_mesh(mesh, name=obj.uuid)
            apply_appearance(actor, obj.appearance, self._point_viewport())
            apply_color_map(actor, obj)
            self._apply_axis_scale(actor)
            self.actors[obj.uuid] = actor
            self._recompute_scene_bounds()
            return actor

    def add_corner_point_cube(self, cube):
        mesh = render_corner_point_grid(cube.corner_grid)
        actor = self.add_mesh(mesh, name=cube.uuid)
        apply_appearance(actor, cube.appearance, self._point_viewport())
        apply_color_map(actor, cube)
        self._apply_axis_scale(actor)
        self.actors[cube.uuid] = actor
        self._recompute_scene_bounds()
        return actor

    def add_well(self, well):
        coordinates = well.coordinates
        if coordinates is None or len(coordinates) < 2:
            return None
        mesh = pv.PolyData(coordinates)
        mesh.lines = np.r_[len(coordinates), np.arange(len(coordinates))]
        actor = self.plotter.add_mesh(
            mesh, name=well.uuid, reset_camera=False, render=False,
            show_scalar_bar=False,
        )
        apply_appearance(actor, well.appearance, self._point_viewport())
        apply_color_map(actor, well)
        self._apply_axis_scale(actor)
        self.actors[well.uuid] = actor
        self._recompute_scene_bounds()
        return actor

    def add_point_cloud(self, point_cloud):
        coordinates = point_cloud.coordinates

        if coordinates is None or len(coordinates) == 0:
            return None

        mesh = pv.PolyData(coordinates)
        actor = self.plotter.add_points(
            mesh,
            name=point_cloud.uuid,
            render_points_as_spheres=False,
            color=point_cloud.appearance.color,
            reset_camera=False,
            render=False,
            show_scalar_bar=False,
        )
        apply_appearance(actor, point_cloud.appearance, self._point_viewport())
        apply_color_map(actor, point_cloud)
        self._apply_axis_scale(actor)
        self.actors[point_cloud.uuid] = actor
        self._recompute_scene_bounds()

        return actor

    def update_object_appearance(self, obj):
        self.update_object_appearances((obj,))

    def update_object_appearances(self, objects):
        updated = False
        viewport = self._point_viewport()
        for obj in objects:
            actor = self.actors.get(obj.uuid)
            if actor is None:
                continue
            apply_appearance(actor, obj.appearance, viewport)
            apply_color_map(actor, obj)
            updated = True
        if updated:
            self._recompute_scene_bounds()
            self.plotter.renderer.ResetCameraClippingRange()
            self.plotter.render()

    def _recompute_scene_bounds(self):
        self.scene_bounds = None
        for actor in self.actors.values():
            self.include_bounds(actor.bounds)

    def _apply_axis_scale(self, actor):
        # One world-coordinate transform for every data actor. In particular,
        # do not scale around each object's center.
        actor.origin = (0, 0, 0)
        actor.scale = self.axis_scale

    def set_axis_scale(self, scale):
        self.axis_scale = tuple(scale)
        axes = self.plotter.renderer.axes_actor
        if axes is not None:
            largest = max(self.axis_scale)
            axes.SetTotalLength(*(value / largest for value in self.axis_scale))
        for actor in self.actors.values():
            self._apply_axis_scale(actor)
        self._recompute_scene_bounds()
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()

    def _point_viewport(self):
        renderer = self.plotter.renderer
        return (*renderer.GetOrigin(), *renderer.GetSize())

    def _update_point_viewport(self, *args):
        viewport = self._point_viewport()
        if viewport != self._last_viewport:
            for actor in self.actors.values():
                if actor.prop.style == "Points":
                    set_point_viewport(actor, viewport)
            self._last_viewport = viewport

    def add_mesh(self, mesh, **kwargs):
        kwargs.setdefault("show_scalar_bar", False)
        actor = self.plotter.add_mesh(
            mesh,
            show_edges=True,
            reset_camera=False,
            render=False,
            **kwargs
        )
        self.include_bounds(mesh.bounds)

        return actor

    def add_points(self, points, radius=0.03, **kwargs):
        kwargs.setdefault("show_scalar_bar", False)
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
        if self.scene_bounds is None:
            return

        self.camera.focus_on_bounds(
            self.plotter,
            self.scene_bounds
        )

    def closeEvent(self, event):
        if self.plotter.render_window is not None:
            self.plotter.render_window.RemoveObserver(self._render_observer)
        self.plotter.close()
        super().closeEvent(event)
