from contextlib import contextmanager
from itertools import product

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from pyvistaqt import QtInteractor
import logging

import numpy as np
import pyvista as pv
from vtkmodules.vtkCommonCore import vtkStringArray

from scene.camera import SceneCamera
from scene.axis_ticks import readable_axis_labels, rounded_axis_range
from models.PointCloud import PointCloud
from models.DataCube import DataCube
from models.Surface import Surface
from models.Well import Well
from renderers.surface_renderer import SurfaceRenderer
from renderers.corner_point_renderer import render_corner_point_grid
from renderers.appearance import (apply_appearance, apply_color_map,
                                  filtered_palette_mesh, set_point_viewport)


logger = logging.getLogger(__name__)


class Viewer3D(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        # словарь акторов
        self.actors = {}
        self._source_meshes = {}
        self.well_label_actors = {}
        self._visible_wells = {}

        self.camera = SceneCamera()
        self.scene_bounds = None
        self.axis_scale = (1.0, 1.0, 1.0)
        self.axes_visible = True
        self.axes_grid_visible = False
        self.axes_label_decimals = 2
        self.axes_round_grid = False
        self.axes_color = "#30343a"
        self.bounds_axes_actor = None
        self._axis_base_labels = ()
        self._axis_visible_labels = [None, None, None]

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

    def set_theme(self, background):
        self.plotter.set_background(background)
        self.axes_color = ("#edf1f7" if np.mean(pv.Color(background).float_rgb) < 0.5
                           else "#30343a")
        with self.scene_update():
            self.update_coordinate_axes()

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
        self._source_meshes.clear()
        self.well_label_actors.clear()
        self._visible_wells.clear()
        self.scene_bounds = None
        self.bounds_axes_actor = None
        self._axis_base_labels = ()
        self._axis_visible_labels = [None, None, None]

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
            mesh = self._display_mesh(obj, mesh)
            if mesh is None:
                return None
            actor = self.add_mesh(mesh, name=obj.uuid)
            apply_appearance(actor, obj.appearance, self._point_viewport())
            apply_color_map(actor, obj)
            self._apply_axis_scale(actor)
            self.actors[obj.uuid] = actor
            self._recompute_scene_bounds()
            return actor

    def add_corner_point_cube(self, cube):
        mesh = render_corner_point_grid(cube.corner_grid)
        mesh = self._display_mesh(cube, mesh)
        if mesh is None:
            return None
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
        # Independent segments allow a value filter to hide only the excluded
        # part of a well instead of dropping its entire polyline.
        mesh.verts = np.empty(0, dtype=np.int64)
        segments = np.column_stack((np.full(len(coordinates) - 1, 2),
                                    np.arange(len(coordinates) - 1),
                                    np.arange(1, len(coordinates))))
        mesh.lines = segments.ravel()
        self._visible_wells[well.uuid] = well
        mesh = self._display_mesh(well, mesh)
        if mesh is None:
            return None
        actor = self.plotter.add_mesh(
            mesh, name=well.uuid, reset_camera=False, render=False,
            show_scalar_bar=False,
        )
        apply_appearance(actor, well.appearance, self._point_viewport())
        apply_color_map(actor, well)
        self._apply_axis_scale(actor)
        self.actors[well.uuid] = actor
        self._sync_well_label(well)
        self._recompute_scene_bounds()
        return actor

    def _sync_well_label(self, well):
        previous = self.well_label_actors.pop(well.uuid, None)
        if previous is not None:
            self.plotter.remove_actor(previous, reset_camera=False, render=False)
        if well.uuid not in self.actors or not well.appearance.label_visible:
            return
        first_visible = self.actors[well.uuid].mapper.dataset.points[0]
        position = np.asarray(first_visible, dtype=float) * np.asarray(self.axis_scale)
        label = self.plotter.add_point_labels(
            np.asarray([position]), [well.well_id], name=f"well-{well.uuid}",
            text_color=well.appearance.label_color,
            font_family=well.appearance.label_font,
            font_size=well.appearance.label_size,
            shadow=True, show_points=False, shape=None, always_visible=True,
            reset_camera=False, render=False,
        )
        self.well_label_actors[well.uuid] = label

    def add_point_cloud(self, point_cloud):
        coordinates = point_cloud.coordinates

        if coordinates is None or len(coordinates) == 0:
            return None

        mesh = pv.PolyData(coordinates)
        mesh = self._display_mesh(point_cloud, mesh)
        if mesh is None:
            return None
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

    def _display_mesh(self, obj, source):
        self._source_meshes[obj.uuid] = source
        filtered = filtered_palette_mesh(source, obj)
        return filtered if filtered.n_cells else None

    def update_object_appearance(self, obj):
        self.update_object_appearances((obj,))

    def rebuild_palette_actors(self, objects):
        """Replace VTK mappers after a palette edit so cached GPU colors are discarded."""
        with self.scene_update():
            viewport = self._point_viewport()
            for obj in objects:
                previous = self.actors.get(obj.uuid)
                source = self._source_meshes.get(obj.uuid)
                if source is None:
                    continue
                if previous is not None:
                    self.plotter.remove_actor(previous, reset_camera=False, render=False)
                mesh = filtered_palette_mesh(source, obj)
                if not mesh.n_cells:
                    self.actors.pop(obj.uuid, None)
                    if isinstance(obj, Well):
                        self._sync_well_label(obj)
                    continue
                actor = self.add_mesh(mesh, name=obj.uuid)
                apply_appearance(actor, obj.appearance, viewport)
                apply_color_map(actor, obj)
                self._apply_axis_scale(actor)
                self.actors[obj.uuid] = actor
                if isinstance(obj, Well):
                    self._sync_well_label(obj)
            self._recompute_scene_bounds()
            self.update_coordinate_axes()
            self.plotter.renderer.ResetCameraClippingRange()

    def update_well_labels(self, objects):
        with self.scene_update():
            for obj in objects:
                if isinstance(obj, Well) and obj.uuid in self.actors:
                    self._sync_well_label(obj)

    def update_object_appearances(self, objects):
        updated = False
        viewport = self._point_viewport()
        for obj in objects:
            actor = self.actors.get(obj.uuid)
            if actor is None:
                continue
            apply_appearance(actor, obj.appearance, viewport)
            apply_color_map(actor, obj)
            if isinstance(obj, Well):
                self._sync_well_label(obj)
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
        with self.scene_update():
            self.axis_scale = tuple(scale)
            axes = self.plotter.renderer.axes_actor
            if axes is not None:
                largest = max(self.axis_scale)
                axes.SetTotalLength(*(value / largest for value in self.axis_scale))
            for actor in self.actors.values():
                self._apply_axis_scale(actor)
            for well in self._visible_wells.values():
                self._sync_well_label(well)
            self._recompute_scene_bounds()
            self.update_coordinate_axes()
            self.plotter.renderer.ResetCameraClippingRange()

    def set_axes_display(self, visible, grid_visible):
        with self.scene_update():
            self.axes_visible = visible
            self.axes_grid_visible = grid_visible
            self.update_coordinate_axes()

    def set_axes_format(self, decimals, round_grid):
        with self.scene_update():
            self.axes_label_decimals = decimals
            self.axes_round_grid = round_grid
            self.update_coordinate_axes()

    def update_coordinate_axes(self):
        if self.bounds_axes_actor is not None:
            self.plotter.remove_bounds_axes()
            self.bounds_axes_actor = None
        if not self.axes_visible or self.scene_bounds is None:
            return
        coordinate_bounds = [
            value / self.axis_scale[index // 2]
            for index, value in enumerate(self.scene_bounds)]
        display_bounds = list(self.scene_bounds)
        label_counts = [5, 5, 5]
        if self.axes_round_grid:
            for axis in range(3):
                start = 2 * axis
                (lower, upper), label_counts[axis] = rounded_axis_range(
                    coordinate_bounds[start], coordinate_bounds[start + 1],
                    self.axes_label_decimals)
                coordinate_bounds[start:start + 2] = (lower, upper)
                display_bounds[start:start + 2] = (
                    lower * self.axis_scale[axis], upper * self.axis_scale[axis])
        self.bounds_axes_actor = self.plotter.show_bounds(
            bounds=display_bounds, axes_ranges=coordinate_bounds,
            xtitle="X", ytitle="Y", ztitle="Z",
            n_xlabels=label_counts[0], n_ylabels=label_counts[1],
            n_zlabels=label_counts[2],
            grid="back" if self.axes_grid_visible else None,
            location="outer", ticks="outside", color=self.axes_color,
            font_size=14, bold=False, fmt=f"%.{self.axes_label_decimals}f",
            use_3d_text=False,
            render=False)
        original_labels = []
        for axis in range(3):
            labels = self.bounds_axes_actor.GetAxisLabels(axis)
            original_labels.append(tuple(labels.GetValue(i)
                                         for i in range(labels.GetNumberOfValues())))
        self._axis_base_labels = tuple(original_labels)
        self._axis_visible_labels = [None, None, None]

    def _axis_screen_length(self, axis):
        bounds = self.bounds_axes_actor.GetBounds()
        other_axes = [index for index in range(3) if index != axis]
        renderer = self.plotter.renderer
        lengths = []
        for corners in product((0, 1), repeat=2):
            points = []
            for endpoint in (0, 1):
                choices = {axis: endpoint, **dict(zip(other_axes, corners))}
                world = [bounds[2 * index + choices[index]] for index in range(3)]
                renderer.SetWorldPoint(*world, 1.0)
                renderer.WorldToDisplay()
                points.append(renderer.GetDisplayPoint()[:2])
            lengths.append(float(np.linalg.norm(np.asarray(points[1]) - points[0])))
        return min((length for length in lengths if np.isfinite(length)), default=0.0)

    def _update_axis_label_visibility(self):
        if self.bounds_axes_actor is None or not self._axis_base_labels:
            return
        for axis, labels in enumerate(self._axis_base_labels):
            visible = readable_axis_labels(labels, self._axis_screen_length(axis))
            if visible == self._axis_visible_labels[axis]:
                continue
            strings = vtkStringArray()
            for label in visible:
                strings.InsertNextValue(label)
            self.bounds_axes_actor.SetAxisLabels(axis, strings)
            self._axis_visible_labels[axis] = visible

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
        self._update_axis_label_visibility()

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
