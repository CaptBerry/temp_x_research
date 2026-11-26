from contextlib import contextmanager
from dataclasses import replace
from itertools import product

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from pyvistaqt import QtInteractor
import logging

import numpy as np
import pyvista as pv
from vtkmodules.vtkCommonCore import vtkStringArray
from vtkmodules.vtkCommonDataModel import vtkPlane

from scene.camera import SceneCamera
from scene.axis_ticks import readable_axis_labels, rounded_axis_range
from scene.clipping import plane_basis, rotation_for_normal, validate_clipping
from models.PointCloud import PointCloud
from models.DataCube import DataCube
from models.DisplayPoints import DisplayPoints
from models.Surface import Surface
from models.Well import Well
from models.CalculationArtifact import CatalogWell
from models.catalog_geometry import catalog_geometry
from models.duplicates import supports_duplicates, duplicate_root, duplicate_info, duplicate_batch
from renderers.surface_renderer import SurfaceRenderer
from renderers.corner_point_renderer import render_corner_point_grid
from renderers.point_cells import render_point_cells
from renderers.display_points import render_display_points
from renderers.interpolated_grid import interpolation_batch
from renderers.appearance import (apply_appearance, apply_color_map,
                                  filtered_palette_mesh, set_point_viewport)


logger = logging.getLogger(__name__)


class Viewer3D(QWidget):
    clippingMoved = pyqtSignal(tuple, tuple)

    def __init__(self, parent=None):
        super().__init__(parent)

        # словарь акторов
        self.actors = {}
        self._hidden_actors = {}
        self._hidden_ids = set()
        self._source_meshes = {}
        self._display_objects = {}
        self._duplicate_actors = {}
        self._duplicate_signatures = {}
        self.well_label_actors = {}
        self._well_label_anchor_indices = {}
        self._visible_wells = {}
        self._catalog_actors = {}

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
        self.clip_enabled = False
        self.clip_origin = (0.0, 0.0, 0.0)
        self.clip_rotation = (0.0, 0.0, 0.0)
        self.clip_invert = False
        self._clip_plane = vtkPlane()
        self._clip_visual = None
        self._clip_mesh = None
        self._clip_widget = None

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
        self._remove_clipping_visuals()
        self.plotter.clear()
        self.plotter.show_axes()
        self.actors.clear()
        self._hidden_actors.clear()
        self._hidden_ids.clear()
        self._source_meshes.clear()
        self._display_objects.clear()
        self._duplicate_actors.clear()
        self._duplicate_signatures.clear()
        self.well_label_actors.clear()
        self._well_label_anchor_indices.clear()
        self._visible_wells.clear()
        self._catalog_actors.clear()
        self.scene_bounds = None
        self.bounds_axes_actor = None
        self._axis_base_labels = ()
        self._axis_visible_labels = [None, None, None]
        self.clip_enabled = False

    def highlight_sample(self, sample, cube=None, shape=(1, 1, 1), neighbor_coordinates=None):
        """Transient sample and patch selection, outside the project object tree."""
        self.plotter.remove_actor("canvas_sample", render=False)
        self.plotter.remove_actor("canvas_patch", render=False)
        self.plotter.remove_actor("canvas_patch_bounds", render=False)
        self.plotter.remove_actor("canvas_well", render=False)
        point = np.array([sample.x, sample.y, sample.z], dtype=float)
        actor = self.plotter.add_points(point.reshape(1, 3), color="#ff5577", point_size=16,
                                       render_points_as_spheres=True, name="canvas_sample", render=False)
        self._apply_axis_scale(actor)
        points = np.empty((0, 3))
        if neighbor_coordinates is not None:
            points = np.asarray(neighbor_coordinates)
            points = points[np.isfinite(points).all(axis=1)]
        elif isinstance(cube, DataCube) and sample.get("cell_id", -1) >= 0:
            if cube.is_corner_point:
                logical = cube.corner_grid.active_indices
                center = logical[int(sample.cell_id)]
                selected = np.all(np.abs(logical - center) <= np.array(shape) // 2, axis=1)
                points = cube.corner_grid.cell_corners()[selected].reshape(-1, 3)
            else:
                axes = [np.unique(cube.coordinates[:, a]) for a in range(3)]
                center = cube.coordinates[int(sample.cell_id)]
                limits = np.array([(axis[max(0, np.searchsorted(axis, v) - radius)],
                                    axis[min(len(axis) - 1, np.searchsorted(axis, v) + radius)])
                                   for axis, v, radius in zip(axes, center, np.array(shape)[::-1] // 2)])
                selected = np.all((cube.coordinates >= limits[:, 0]) & (cube.coordinates <= limits[:, 1]), axis=1)
                points = cube.coordinates[selected]
        if len(points):
            actor = self.plotter.add_points(points, color="#ffcc66", point_size=9,
                                           name="canvas_patch", render_points_as_spheres=True, render=False)
            self._apply_axis_scale(actor)
            lo, hi = points.min(axis=0), points.max(axis=0)
            padding = np.maximum((hi - lo) * .02, 1e-4)
            bounds = np.column_stack([lo - padding, hi + padding]).ravel()
            actor = self.plotter.add_mesh(pv.Box(bounds=bounds), style="wireframe", color="#ffcc66",
                                         line_width=3, name="canvas_patch_bounds", render=False)
            self._apply_axis_scale(actor)
            self.camera.focus_on_bounds(self.plotter, actor.bounds)
        self.plotter.render()

    def highlight_catalog_well(self, catalog):
        columns = ["source_x", "source_y", "source_z"] if "source_x" in catalog else ["x", "y", "z"]
        points = catalog.sort_values("source_row")[columns].drop_duplicates().to_numpy(float)
        self.plotter.remove_actor("canvas_well", render=False)
        if len(points) > 1:
            actor = self.plotter.add_mesh(pv.lines_from_points(points), color="#f6a94b", line_width=4,
                                         name="canvas_well", render=False)
            self._apply_axis_scale(actor)
        self.plotter.render()

    def focus_on_object(self, obj):
        objects = [obj]
        for current in objects:
            objects.extend(current.children)
        bounds = [actor.bounds for o in objects for actor in self._catalog_actors.get(o.uuid, ())
                  if actor.visibility]
        bounds.extend(self.actors[o.uuid].bounds for o in objects
                      if o.uuid in self.actors and o.uuid not in self._catalog_actors)
        bounds.extend(self._duplicate_actors[o.uuid].bounds for o in objects
                      if o.uuid in self._duplicate_actors and self._duplicate_actors[o.uuid].visibility)
        if bounds:
            bounds = np.array(bounds)
            combined = tuple(v for axis in range(3) for v in (bounds[:, axis * 2].min(), bounds[:, axis * 2 + 1].max()))
            self.camera.focus_on_bounds(self.plotter, combined)

    @contextmanager
    def scene_update(self):
        """Keep the previous frame visible until the whole scene is ready."""
        was_suppressed = self.plotter.suppress_rendering
        updates_enabled = self.plotter.updatesEnabled()
        self.plotter.suppress_rendering = True
        self.plotter.setUpdatesEnabled(False)
        completed = False
        try:
            with interpolation_batch(), duplicate_batch():
                yield
                had_markers = bool(self._duplicate_actors)
                self._sync_duplicate_markers()
                if had_markers or self._duplicate_actors:
                    self._recompute_scene_bounds()
                    self.update_coordinate_axes()
            completed = True
        finally:
            self.plotter.suppress_rendering = was_suppressed
            self.plotter.setUpdatesEnabled(updates_enabled)
            if completed and not was_suppressed and updates_enabled:
                self.plotter.render()


    def add_object(self, obj):
        if isinstance(obj, CatalogWell):
            return self.add_catalog(obj)
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
            self._attach_clipping(actor)
            self.actors[obj.uuid] = actor
            self._recompute_scene_bounds()
            return actor

    def add_catalog(self, well):
        """One catalog well with its trace, sample marks and exact source links."""
        geometry = catalog_geometry(well.parent, well.well_uuid)
        actors = []

        def lines(points, edges, color, width, suffix, opacity=1.0):
            if not len(edges):
                return
            mesh = pv.PolyData(points)
            mesh.lines = np.column_stack((np.full(len(edges), 2), edges)).ravel()
            actors.append(self.plotter.add_mesh(
                mesh, color=color, line_width=width, opacity=opacity,
                name=f"{well.uuid}:{suffix}", show_scalar_bar=False,
                reset_camera=False, render=False, pickable=False))

        lines(geometry.trajectory_points, geometry.trajectory_lines, "#f6a94b", 3, "well")
        if len(geometry.sample_points):
            actors.append(self.plotter.add_points(
                geometry.sample_points, color="#ff5577", point_size=9,
                render_points_as_spheres=True, name=f"{well.uuid}:samples",
                reset_camera=False, render=False, show_scalar_bar=False, pickable=False))
        if len(geometry.source_points):
            actors.append(self.plotter.add_points(
                geometry.source_points, color="#49c5d6", point_size=6,
                render_points_as_spheres=True, name=f"{well.uuid}:sources",
                reset_camera=False, render=False, show_scalar_bar=False, pickable=False))
            lines(np.vstack((geometry.sample_points, geometry.source_points)),
                  geometry.links, "#9ca8b6", 1, "links", opacity=.55)
        if not actors:
            return None
        for actor in actors:
            self._apply_axis_scale(actor)
            self._attach_clipping(actor)
        self._catalog_actors[well.uuid] = actors
        self.actors[well.uuid] = actors[0]
        self._recompute_scene_bounds()
        return actors[0]

    def add_corner_point_cube(self, cube):
        mesh = render_corner_point_grid(cube.corner_grid)
        mesh = self._display_mesh(cube, mesh)
        if mesh is None:
            return None
        actor = self.add_mesh(mesh, name=cube.uuid)
        apply_appearance(actor, cube.appearance, self._point_viewport())
        apply_color_map(actor, cube)
        self._apply_axis_scale(actor)
        self._attach_clipping(actor)
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
        self._attach_clipping(actor)
        self.actors[well.uuid] = actor
        self._sync_well_label(well)
        self._recompute_scene_bounds()
        return actor

    def _sync_well_label(self, well):
        previous = self.well_label_actors.pop(well.uuid, None)
        self._well_label_anchor_indices.pop(well.uuid, None)
        if previous is not None:
            self.plotter.remove_actor(previous, reset_camera=False, render=False)
        if well.uuid not in self.actors or not well.appearance.label_visible:
            return
        points = np.asarray(self.actors[well.uuid].mapper.dataset.points, dtype=float)
        if not len(points):
            return
        if self.clip_enabled:
            world_points = points * self.axis_scale
            origin = np.asarray(self._clip_plane.GetOrigin())
            normal = np.asarray(self._clip_plane.GetNormal())
            kept = np.flatnonzero((world_points - origin) @ normal >= 0)
            if not len(kept):
                return
            anchor_index = int(kept[0])
        else:
            anchor_index = 0
        position = points[anchor_index] * np.asarray(self.axis_scale)
        label = self.plotter.add_point_labels(
            np.asarray([position]), [well.well_id], name=f"well-{well.uuid}",
            text_color=well.appearance.label_color,
            font_family=well.appearance.label_font,
            font_size=well.appearance.label_size,
            shadow=True, show_points=False, shape=None, always_visible=True,
            reset_camera=False, render=False,
        )
        self.well_label_actors[well.uuid] = label
        self._well_label_anchor_indices[well.uuid] = anchor_index

    def _refresh_clipped_well_labels(self):
        origin = np.asarray(self._clip_plane.GetOrigin())
        normal = np.asarray(self._clip_plane.GetNormal())
        for well in self._visible_wells.values():
            actor = self.actors.get(well.uuid)
            if actor is None or not well.appearance.label_visible:
                continue
            points = np.asarray(actor.mapper.dataset.points, dtype=float)
            if self.clip_enabled:
                kept = np.flatnonzero((points * self.axis_scale - origin) @ normal >= 0)
                anchor_index = int(kept[0]) if len(kept) else None
            else:
                anchor_index = 0 if len(points) else None
            if anchor_index != self._well_label_anchor_indices.get(well.uuid):
                self._sync_well_label(well)

    def add_point_cloud(self, point_cloud, *, force_points=False):
        coordinates = point_cloud.coordinates

        if coordinates is None or len(coordinates) == 0:
            return None

        grid_display = (not force_points and isinstance(point_cloud, DisplayPoints)
                        and point_cloud.appearance.mode in ("corner_grid", "grid_wireframe"))
        mesh = (render_display_points(point_cloud) if grid_display else
                render_point_cells(point_cloud) if point_cloud.appearance.mode == "cells"
                else pv.PolyData(coordinates))
        mesh = self._display_mesh(point_cloud, mesh)
        if mesh is None:
            self._update_duplicate_marker(point_cloud)
            return None
        if grid_display or point_cloud.appearance.mode == "cells":
            actor = self.add_mesh(mesh, name=point_cloud.uuid)
        else:
            actor = self.plotter.add_points(
                mesh, name=point_cloud.uuid, render_points_as_spheres=False,
                color=point_cloud.appearance.color, reset_camera=False,
                render=False, show_scalar_bar=False,
            )
        appearance = replace(point_cloud.appearance, mode="points") if force_points else point_cloud.appearance
        apply_appearance(actor, appearance, self._point_viewport())
        apply_color_map(actor, point_cloud)
        self._apply_object_transform(actor, point_cloud)
        self._attach_clipping(actor)
        self.actors[point_cloud.uuid] = actor
        self._update_duplicate_marker(point_cloud)
        self._recompute_scene_bounds()

        return actor

    def _display_mesh(self, obj, source):
        self._source_meshes[obj.uuid] = source
        self._display_objects[obj.uuid] = obj
        filtered = filtered_palette_mesh(source, obj)
        return filtered if filtered.n_cells else None

    def _update_duplicate_marker(self, obj):
        palette = getattr(getattr(obj, "appearance", None), "color_map", None)
        enabled = palette is not None and palette.highlight_duplicates and supports_duplicates(obj)
        if not enabled:
            previous = self._duplicate_actors.pop(obj.uuid, None)
            self._duplicate_signatures.pop(obj.uuid, None)
            if previous is not None:
                self.plotter.remove_actor(previous, reset_camera=False, render=False)
            return
        root = duplicate_root(obj)
        layers = getattr(root, "layers", (root,))
        signature = tuple((layer.uuid, id(layer.dataframe), len(layer.dataframe),
                           layer.x_column, layer.y_column, layer.z_column,
                           id(self._source_meshes.get(layer.uuid))) for layer in layers)
        actor = self._duplicate_actors.get(obj.uuid)
        if signature != self._duplicate_signatures.get(obj.uuid):
            if actor is not None:
                self.plotter.remove_actor(actor, reset_camera=False, render=False)
                self._duplicate_actors.pop(obj.uuid, None)
            info = duplicate_info(obj)
            self._duplicate_signatures[obj.uuid] = signature
            actor = None
            if info["groups"]:
                actor = self.plotter.add_points(info["coordinates"], name="duplicates:" + obj.uuid,
                                               color="#ff0000", reset_camera=False, render=False,
                                               show_scalar_bar=False, pickable=False)
                self._duplicate_actors[obj.uuid] = actor
        if actor is not None:
            appearance = replace(obj.appearance, mode="points", color="#ff0000", color_map=None,
                                 point_size=min(64, max(10, obj.appearance.point_size + 4)),
                                 outline=False, opacity=1.)
            apply_appearance(actor, appearance, self._point_viewport())
            actor.mapper.scalar_visibility = False
            actor.mapper.SetResolveCoincidentTopologyToPolygonOffset()
            actor.mapper.SetRelativeCoincidentTopologyPointOffsetParameter(-10)
            actor.visibility = obj.uuid not in self._hidden_ids
            self._apply_object_transform(actor, obj)
            if self.clip_enabled:
                if actor.mapper.GetNumberOfClippingPlanes() == 0:
                    self._attach_clipping(actor)
            else:
                actor.mapper.RemoveAllClippingPlanes()

    def _sync_duplicate_markers(self):
        with duplicate_batch():
            for obj in self._display_objects.values():
                self._update_duplicate_marker(obj)

    def _store_actor_visibility(self, obj, actor):
        if obj.uuid in self._hidden_ids:
            actor.visibility = False
            self.actors.pop(obj.uuid, None)
            self._hidden_actors[obj.uuid] = actor
        else:
            actor.visibility = True
            self._hidden_actors.pop(obj.uuid, None)
            self.actors[obj.uuid] = actor

    def _restore_source_actor(self, obj, source):
        mesh = filtered_palette_mesh(source, obj)
        if not mesh.n_cells:
            return None
        actor = self.add_mesh(mesh, name=obj.uuid)
        apply_appearance(actor, obj.appearance, self._point_viewport())
        apply_color_map(actor, obj)
        self._apply_object_transform(actor, obj)
        self._attach_clipping(actor)
        self._store_actor_visibility(obj, actor)
        if isinstance(obj, Well):
            self._sync_well_label(obj)
        return actor

    def sync_object_visibility(self, project, roots):
        """Toggle just affected actors, retaining hidden geometry for reuse."""
        with self.scene_update():
            seen = set()
            for root in roots:
                for obj in project.walk(root):
                    if obj.uuid in seen or not isinstance(obj, (PointCloud, Surface, CatalogWell)):
                        continue
                    seen.add(obj.uuid)
                    visible = project.is_visible(obj)
                    actor = self.actors.get(obj.uuid)
                    if not visible:
                        self._hidden_ids.add(obj.uuid)
                        for part in self._catalog_actors.get(obj.uuid, ()):
                            part.visibility = False
                        if actor is not None:
                            actor.visibility = False
                            self._hidden_actors[obj.uuid] = self.actors.pop(obj.uuid)
                            if isinstance(obj, Well):
                                self._sync_well_label(obj)
                        continue
                    self._hidden_ids.discard(obj.uuid)
                    if actor is not None:
                        continue
                    actor = self._hidden_actors.pop(obj.uuid, None)
                    if actor is not None:
                        actor.visibility = True
                        for part in self._catalog_actors.get(obj.uuid, ()):
                            part.visibility = True
                        self.actors[obj.uuid] = actor
                        if isinstance(obj, Well):
                            self._sync_well_label(obj)
                    elif obj.uuid in self._source_meshes:
                        self._restore_source_actor(obj, self._source_meshes[obj.uuid])
                    else:
                        self.add_object(obj)
            self._recompute_scene_bounds()
            self.update_coordinate_axes()
            self.plotter.renderer.ResetCameraClippingRange()

    def remove_objects(self, objects):
        """Remove deleted objects without rebuilding the rest of the scene."""
        with self.scene_update():
            for obj in objects:
                catalog_parts = self._catalog_actors.pop(obj.uuid, ())
                for part in catalog_parts:
                    self.plotter.remove_actor(part, reset_camera=False, render=False)
                actor = self.actors.pop(obj.uuid, None)
                if actor is None:
                    actor = self._hidden_actors.pop(obj.uuid, None)
                if actor is not None and not catalog_parts:
                    self.plotter.remove_actor(actor, reset_camera=False, render=False)
                self._source_meshes.pop(obj.uuid, None)
                self._display_objects.pop(obj.uuid, None)
                duplicate_actor = self._duplicate_actors.pop(obj.uuid, None)
                self._duplicate_signatures.pop(obj.uuid, None)
                if duplicate_actor is not None:
                    self.plotter.remove_actor(duplicate_actor, reset_camera=False, render=False)
                self._hidden_ids.discard(obj.uuid)
                if isinstance(obj, Well):
                    self._visible_wells.pop(obj.uuid, None)
                    self._sync_well_label(obj)
            self._recompute_scene_bounds()
            self.update_coordinate_axes()
            self.plotter.renderer.ResetCameraClippingRange()

    def replace_source_meshes(self, sources):
        """Install completed data on the GUI thread without touching other actors."""
        with self.scene_update():
            for obj, source in sources:
                self._display_objects[obj.uuid] = obj
                previous = self.actors.pop(obj.uuid, None)
                if previous is None:
                    previous = self._hidden_actors.pop(obj.uuid, None)
                if previous is not None:
                    self.plotter.remove_actor(previous, reset_camera=False, render=False)
                self._source_meshes[obj.uuid] = source
                self._restore_source_actor(obj, source)
            self._recompute_scene_bounds()
            self.update_coordinate_axes()
            self.plotter.renderer.ResetCameraClippingRange()

    def update_object_appearance(self, obj):
        self.update_object_appearances((obj,))

    def rebuild_geometry_actors(self, objects):
        """Recreate actors when the selected representation changes geometry."""
        with self.scene_update():
            for obj in objects:
                if obj.uuid not in self._source_meshes:
                    continue
                self.plotter.remove_actor(obj.uuid, reset_camera=False, render=False)
                self.actors.pop(obj.uuid, None)
                self._hidden_actors.pop(obj.uuid, None)
                if isinstance(obj, DataCube) and obj.is_corner_point:
                    actor = self.add_corner_point_cube(obj)
                elif isinstance(obj, PointCloud) and not isinstance(obj, Well):
                    actor = self.add_point_cloud(obj)
                else:
                    actor = None
                if actor is not None:
                    self._store_actor_visibility(obj, actor)
            self._recompute_scene_bounds()
            self.update_coordinate_axes()
            self.plotter.renderer.ResetCameraClippingRange()

    def rebuild_palette_actors(self, objects):
        """Replace VTK mappers after a palette edit so cached GPU colors are discarded."""
        with self.scene_update():
            viewport = self._point_viewport()
            for obj in objects:
                previous = self.actors.pop(obj.uuid, None)
                if previous is None:
                    previous = self._hidden_actors.pop(obj.uuid, None)
                source = self._source_meshes.get(obj.uuid)
                if source is None:
                    continue
                if previous is not None:
                    self.plotter.remove_actor(previous, reset_camera=False, render=False)
                mesh = filtered_palette_mesh(source, obj)
                if not mesh.n_cells:
                    if isinstance(obj, Well):
                        self._sync_well_label(obj)
                    continue
                actor = self.add_mesh(mesh, name=obj.uuid)
                apply_appearance(actor, obj.appearance, viewport)
                apply_color_map(actor, obj)
                self._apply_object_transform(actor, obj)
                self._attach_clipping(actor)
                self._store_actor_visibility(obj, actor)
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

    def update_object_transforms(self, objects):
        """Apply a changed Z direction to cached actors without rebuilding meshes."""
        with self.scene_update():
            for obj in objects:
                actor = self.actors.get(obj.uuid) or self._hidden_actors.get(obj.uuid)
                if actor is not None:
                    self._apply_object_transform(actor, obj)
            self._recompute_scene_bounds()
            self.update_coordinate_axes()
            self.plotter.renderer.ResetCameraClippingRange()

    def update_object_appearances(self, objects):
        updated = False
        viewport = self._point_viewport()
        for obj in objects:
            actor = self.actors.get(obj.uuid) or self._hidden_actors.get(obj.uuid)
            if actor is None:
                continue
            apply_appearance(actor, obj.appearance, viewport)
            apply_color_map(actor, obj)
            if isinstance(obj, Well):
                self._sync_well_label(obj)
            updated = True
        if updated:
            self._sync_duplicate_markers()
            self._recompute_scene_bounds()
            self.plotter.renderer.ResetCameraClippingRange()
            self.plotter.render()

    def _recompute_scene_bounds(self):
        self.scene_bounds = None
        for actor in (*self.actors.values(), *self._duplicate_actors.values()):
            if actor.visibility:
                self.include_bounds(actor.bounds)
        for parts in self._catalog_actors.values():
            for actor in parts[1:]:
                if actor.visibility:
                    self.include_bounds(actor.bounds)
        if self.clip_enabled:
            if self.scene_bounds is None:
                self._remove_clipping_visuals()
            else:
                self._sync_clipping_visuals()

    def _attach_clipping(self, actor):
        if self.clip_enabled:
            actor.mapper.AddClippingPlane(self._clip_plane)

    def _remove_clipping_visuals(self):
        if self._clip_widget is not None:
            self.plotter.clear_plane_widgets()
            self._clip_widget = None
        if self._clip_visual is not None:
            self.plotter.remove_actor(self._clip_visual, reset_camera=False, render=False)
            self._clip_visual = None
            self._clip_mesh = None

    def set_clipping_settings(self, enabled, origin, rotation, invert=False, *,
                              sync_widget=True):
        enabled, origin, rotation, invert = validate_clipping(enabled, origin, rotation, invert)
        with self.scene_update():
            self.clip_enabled = enabled
            self.clip_origin = origin
            self.clip_rotation = rotation
            self.clip_invert = invert
            if not enabled:
                for actor in (*self.actors.values(), *self._hidden_actors.values(), *self._duplicate_actors.values(),
                              *(part for parts in self._catalog_actors.values() for part in parts[1:])):
                    actor.mapper.RemoveAllClippingPlanes()
                self._remove_clipping_visuals()
                self._refresh_clipped_well_labels()
                return
            world_origin = np.asarray(origin) * self.axis_scale
            normal = plane_basis(rotation)[2]
            self._clip_plane.SetOrigin(*world_origin)
            self._clip_plane.SetNormal(*(normal * (-1 if invert else 1)))
            self._clip_plane.Modified()
            for actor in (*self.actors.values(), *self._hidden_actors.values(), *self._duplicate_actors.values(),
                          *(part for parts in self._catalog_actors.values() for part in parts[1:])):
                if actor.mapper.GetNumberOfClippingPlanes() == 0:
                    self._attach_clipping(actor)
                actor.mapper.Modified()
            self._sync_clipping_visuals(sync_widget=sync_widget)
            self._refresh_clipped_well_labels()

    def _sync_clipping_visuals(self, *, sync_widget=True):
        if not self.clip_enabled or self.scene_bounds is None:
            return
        bounds = np.asarray(self.scene_bounds, dtype=float)
        spans = bounds[[1, 3, 5]] - bounds[[0, 2, 4]]
        radius = max(float(np.linalg.norm(spans)) * 0.7, 1.0)
        origin = np.asarray(self.clip_origin) * self.axis_scale
        u, v, normal = plane_basis(self.clip_rotation)
        points = np.asarray([origin - radius * u - radius * v,
                             origin + radius * u - radius * v,
                             origin + radius * u + radius * v,
                             origin - radius * u + radius * v])
        if self._clip_mesh is None:
            self._clip_mesh = pv.PolyData(points, faces=[4, 0, 1, 2, 3])
            self._clip_visual = self.plotter.add_mesh(
                self._clip_mesh, name="__clipping_plane__", color="#38bdf8",
                edge_color="#0ea5e9", show_edges=True, line_width=2,
                opacity=0.16, lighting=False, pickable=False,
                reset_camera=False, render=False, show_scalar_bar=False)
        else:
            self._clip_mesh.points = points
            self._clip_mesh.Modified()
        if self._clip_widget is None:
            widget_bounds = bounds.copy()
            for axis in range(3):
                low, high = 2 * axis, 2 * axis + 1
                if widget_bounds[high] - widget_bounds[low] < radius * 0.1:
                    center = (widget_bounds[low] + widget_bounds[high]) / 2
                    widget_bounds[low], widget_bounds[high] = center - radius * 0.05, center + radius * 0.05
            self._clip_widget = self.plotter.add_plane_widget(
                self._plane_widget_changed, normal=normal, origin=origin,
                bounds=tuple(widget_bounds), color="#0ea5e9",
                implicit=True, outline_translation=True,
                interaction_event="always", test_callback=False)
        elif sync_widget:
            self._clip_widget.SetOrigin(origin)
            self._clip_widget.SetNormal(normal)
            self._clip_widget.Modified()
            self._clip_widget.UpdatePlacement()

    def _plane_widget_changed(self, normal, origin):
        origin = tuple(float(value) for value in np.asarray(origin) / self.axis_scale)
        rotation = rotation_for_normal(normal, self.clip_rotation[2])
        if (np.allclose(origin, self.clip_origin, rtol=0, atol=1e-6)
                and np.allclose(rotation, self.clip_rotation, rtol=0, atol=1e-6)):
            return
        self.clippingMoved.emit(origin, rotation)

    def _apply_axis_scale(self, actor):
        # One world-coordinate transform for every data actor. In particular,
        # do not scale around each object's center.
        actor.origin = (0, 0, 0)
        actor.scale = self.axis_scale

    def _apply_object_transform(self, actor, obj):
        if isinstance(obj, DisplayPoints):
            # Keep the source tables and meshes in their original coordinates.
            # This transform also survives mapper replacement on palette edits.
            transform = np.eye(4)
            if obj.display_grid.z_direction == "down":
                transform[2, 2] = -1
            actor.user_matrix = transform
        self._apply_axis_scale(actor)

    def set_axis_scale(self, scale):
        with self.scene_update():
            self.axis_scale = tuple(scale)
            axes = self.plotter.renderer.axes_actor
            if axes is not None:
                largest = max(self.axis_scale)
                axes.SetTotalLength(*(value / largest for value in self.axis_scale))
            for actor in (*self.actors.values(), *self._hidden_actors.values(), *self._duplicate_actors.values(),
                          *(part for parts in self._catalog_actors.values() for part in parts[1:])):
                self._apply_axis_scale(actor)
            if self.clip_enabled:
                self.set_clipping_settings(True, self.clip_origin,
                                           self.clip_rotation, self.clip_invert)
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
            for actor in (*self.actors.values(), *self._hidden_actors.values(), *self._duplicate_actors.values(),
                          *(part for parts in self._catalog_actors.values() for part in parts[1:])):
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
        self._remove_clipping_visuals()
        if self.plotter.render_window is not None:
            self.plotter.render_window.RemoveObserver(self._render_observer)
        self.plotter.close()
        super().closeEvent(event)
