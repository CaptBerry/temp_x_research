"""Render two crossing translucent palette surfaces on the Windows desktop."""

import os
os.environ["QT_QPA_PLATFORM"] = "windows"

import numpy as np
import pandas as pd
import pyvista as pv
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
import tempfile
from pathlib import Path

from gui.MainWindow import MainWindow
from models.ColorMap import ColorMap, ColorStop
from models.Surface import Surface
from models.PointCloud import PointCloud
from models.project.Project import Project


def surface(name, color, ascending):
    obj = Surface(name)
    obj.vertices = np.asarray([
        [-1, -1, -0.5 if ascending else 0.5],
        [1, -1, 0.5 if ascending else -0.5],
        [1, 1, 0.5 if ascending else -0.5],
        [-1, 1, -0.5 if ascending else 0.5],
    ], dtype=float)
    obj.faces = np.array([3, 0, 1, 2, 3, 0, 2, 3])
    stops = (ColorStop(0, color), ColorStop(100, color))
    obj.appearance = obj.appearance.updated("surface", opacity=0.5, outline=False,
                                            color_map=ColorMap("z", -1, 1, stops))
    return obj


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
        window = MainWindow(settings=settings, restore_session=False)
        window.resize(1100, 750)
        window.show()
        app.processEvents()
        project = Project()
        project.add(surface("Синяя", "#0000ff", True))
        project.add(surface("Красная", "#ff0000", False))
        window.set_project(project)
        plotter = window.viewer.plotter
        plotter.camera.parallel_projection = True
        plotter.view_xy()
        plotter.reset_camera()
        plotter.render()
        image = plotter.screenshot(return_img=True)
        h, w = image.shape[:2]
        left = image[h // 2, int(w * 0.43), :3]
        right = image[h // 2, int(w * 0.57), :3]
        print("depth peeling", plotter.renderer.GetUseDepthPeeling(), "last used", plotter.renderer.GetLastRenderingUsedDepthPeeling())
        print("crossing surfaces left/right", left.tolist(), right.tolist())
        assert left[0] > left[2] + 20, (left, right)
        assert right[2] > right[0] + 20, (left, right)

        # A point cloud inside a translucent closed surface must still use its
        # own palette; the enclosing palette contributes only via alpha blend.
        nested = Project()
        outer = Surface("Оболочка")
        cube = pv.Cube(bounds=(-1, 1, -1, 1, -1, 1)).triangulate()
        outer.vertices = cube.points
        outer.faces = cube.faces
        outer.appearance = outer.appearance.updated("surface", opacity=0.25, outline=False,
            color_map=ColorMap("z", -1, 1, (ColorStop(0, "#0000ff"), ColorStop(100, "#0000ff"))))
        inner = PointCloud("Внутренние точки", dataframe=pd.DataFrame(
            {"x": [0.], "y": [0.], "z": [0.], "grade": [0.]}))
        inner.set_mapping("x", "y", "z", ["grade"])
        inner.appearance = inner.appearance.updated("pointcloud", point_size=64,
            color_map=ColorMap("grade", 0, 1, (ColorStop(0, "#ff0000"), ColorStop(100, "#ff0000"))))
        nested.add(outer)
        nested.add(inner)
        window.set_project(nested)
        plotter.view_xy()
        plotter.reset_camera()
        plotter.render()
        nested_image = plotter.screenshot(return_img=True)
        h, w = nested_image.shape[:2]
        center = nested_image[h // 2, w // 2, :3]
        print("nested point", center.tolist())
        assert center[0] > center[2] + 50, center
        assert window.viewer.actors[outer.uuid].mapper.lookup_table.values[0, 2] == 255
        assert window.viewer.actors[inner.uuid].mapper.lookup_table.values[0, 0] == 255
        nested.modified = False
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()
