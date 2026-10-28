"""Pixel and camera checks on Windows: python -B -m tests.vtk_appearance_smoke.

An optional output PNG path captures the finished properties panel for review.
"""

import os
os.environ["QT_QPA_PLATFORM"] = "windows"

from pathlib import Path
import sys
import tempfile

import numpy as np
import pandas as pd
import pyvista as pv
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from gui.MainWindow import MainWindow
from models.PointCloud import PointCloud
from models.Surface import Surface
from models.project.Project import Project
from models.ColorMap import ColorMap, ColorStop


def color_pixels(image, color):
    difference = np.abs(image[:, :, :3].astype(int) - pv.Color(color).int_rgb)
    return int(np.count_nonzero(np.max(difference, axis=2) < 3))


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as temporary:
        settings = QSettings(str(Path(temporary) / "settings.ini"), QSettings.Format.IniFormat)
        window = MainWindow(settings=settings, restore_session=False)
        window.resize(1200, 780)
        window.show()
        app.processEvents()
        project = Project()
        project.name = "Настройки отображения"
        cloud = PointCloud("Облако точек", dataframe=pd.DataFrame({"x": [0.], "y": [0.], "z": [0.], "grade": [0.]}))
        cloud.set_mapping("x", "y", "z")
        project.add(cloud)
        window.set_project(project)
        window.select_object(cloud.uuid)
        plotter = window.viewer.plotter
        plotter.view_xy()
        plotter.reset_camera()
        actor = window.viewer.actors[cloud.uuid]
        geometry = actor.mapper.dataset
        original_camera = np.asarray(plotter.camera_position)

        def change(obj, **values):
            window._change_appearance(obj.uuid, values)
            app.processEvents()
            return plotter.screenshot(return_img=True)

        try:
            image = change(cloud, point_size=44, outline=True, line_width=7,
                           color="#e11d48", outline_color="#182b49")
            fill = color_pixels(image, "#e11d48")
            border = color_pixels(image, "#182b49")
            assert fill > 1000 and border > 500, (fill, border)
            np.testing.assert_array_equal(plotter.camera_position, original_camera)
            assert window.viewer.actors[cloud.uuid] is actor
            assert actor.mapper.dataset is geometry

            translucent = change(cloud, opacity=0.5)
            assert actor.prop.opacity == 0.5
            assert color_pixels(translucent, "#e11d48") < fill / 2
            change(cloud, opacity=1)

            thinner = change(cloud, line_width=2)
            assert color_pixels(thinner, "#182b49") < border
            assert abs(color_pixels(thinner, "#e11d48") - fill) < 100
            square = change(cloud, point_shape="square")
            assert color_pixels(square, "#e11d48") > fill
            no_border = change(cloud, outline=False)
            assert color_pixels(no_border, "#182b49") == 0

            spheres = change(cloud, mode="spheres")
            # Sphere shading varies by pixel; detect the red hue, not exact RGB.
            red = (spheres[:, :, 0] > spheres[:, :, 1].astype(int) + 50)
            assert np.count_nonzero(red) > 500
            circle = change(cloud, mode="points", point_shape="circle", outline=True, line_width=7)
            assert color_pixels(circle, "#182b49") > 500

            palette = ColorMap("grade", 0, 1, (ColorStop(0, "#0000ff"), ColorStop(100, "#ff0000")))
            colored = change(cloud, color_map=palette)
            assert color_pixels(colored, "#0000ff") > 500
            assert color_pixels(colored, "#182b49") > 500
            edited_palette = ColorMap("grade", 0, 1, (ColorStop(0, "#00ff00"), ColorStop(100, "#ff0000")))
            recolored = change(cloud, color_map=edited_palette)
            assert color_pixels(recolored, "#00ff00") > 500
            change(cloud, color_map=palette)
            mapped_translucent = change(cloud, opacity=0.5)
            assert color_pixels(mapped_translucent, "#0000ff") < color_pixels(colored, "#0000ff") / 2
            change(cloud, opacity=1)
            assert window.viewer.actors[cloud.uuid] is actor
            assert actor.mapper.dataset is geometry
            sphere_palette = change(cloud, mode="spheres")
            blue = (sphere_palette[:, :, 2].astype(int) > sphere_palette[:, :, 0].astype(int) + 50)
            assert np.count_nonzero(blue) > 500
            change(cloud, mode="points", color_map=None)

            window.resize(1350, 850)
            app.processEvents()
            resized = plotter.screenshot(return_img=True)
            assert color_pixels(resized, "#e11d48") > 1000
            assert color_pixels(resized, "#182b49") > 500
            plotter.camera.zoom(1.5)
            zoomed = plotter.screenshot(return_img=True)
            assert abs(color_pixels(zoomed, "#e11d48") - fill) < 100

            # The same actor must switch from point shaders back to triangles.
            project.set_visible(cloud, False)
            surface = Surface("Поверхность")
            surface.vertices = np.array([[-1., -1., 0.], [1., -1., 0.], [0., 1., 0.]])
            surface.faces = np.array([3, 0, 1, 2])
            project.import_file(surface)
            window.update_3d_viewer()
            plotter.view_xy()
            for mode in ("surface", "points", "spheres", "wireframe", "surface"):
                result = change(surface, mode=mode, color="#00a040", point_size=30, line_width=3)
                green = (result[:, :, 1].astype(int) > result[:, :, 0].astype(int) + 30)
                assert np.count_nonzero(green) > 80, mode

            surface_palette = ColorMap("z", -1, 1, (ColorStop(0, "#0000ff"), ColorStop(100, "#ff0000")))
            mapped = change(surface, color_map=surface_palette)
            assert np.count_nonzero((mapped[:, :, 0] > 70) & (mapped[:, :, 2] > 70)) > 80
            change(surface, color_map=None)

            surface_actor = window.viewer.actors[surface.uuid]
            surface_mesh = surface_actor.mapper.dataset
            old_bounds = tuple(surface_actor.bounds)
            camera_before_scale = np.asarray(plotter.camera_position)
            window._change_axis_scale(2, 0.5, 3)
            app.processEvents()
            assert project.axis_scale == (2, 0.5, 3)
            np.testing.assert_allclose(plotter.renderer.axes_actor.GetTotalLength(), (2 / 3, 0.5 / 3, 1))
            assert surface_actor.scale == (2, 0.5, 3)
            assert surface_actor.origin == (0, 0, 0)
            assert tuple(surface_actor.bounds) != old_bounds
            assert surface_actor.mapper.dataset is surface_mesh
            np.testing.assert_array_equal(plotter.camera_position, camera_before_scale)
            assert window.viewer.scene_bounds == tuple(surface_actor.bounds)
            project.set_visible(cloud, True)
            window.update_3d_viewer()
            assert window.viewer.actors[cloud.uuid].scale == (2, 0.5, 3)
            assert window.viewer.actors[surface.uuid].scale == (2, 0.5, 3)

            if len(sys.argv) > 1:
                project.set_visible(cloud, True)
                project.set_visible(surface, False)
                window.update_project_tree()
                window.update_3d_viewer()
                window.select_object(cloud.uuid)
                app.processEvents()
                destination = Path(sys.argv[1]).resolve()
                destination.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(destination))

            offset = Surface("Смещение от начала координат")
            offset.vertices = np.array([[10., 20., 30.], [12., 20., 30.], [10., 22., 32.]])
            offset.faces = np.array([3, 0, 1, 2])
            project.import_file(offset)
            offset_actor = window.viewer.add_object(offset)
            np.testing.assert_allclose(tuple(offset_actor.bounds), (20, 24, 10, 11, 90, 96))
            np.testing.assert_array_equal(offset_actor.mapper.dataset.points, offset.vertices)
            print("Appearance pixels OK: colors, opacity, outline, shape, palette, scale and camera")
        finally:
            project.modified = False
            window.close()
            app.processEvents()


if __name__ == "__main__":
    main()
