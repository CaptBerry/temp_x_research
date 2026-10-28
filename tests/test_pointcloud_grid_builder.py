import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication

from gui.dialogs.ImportDialog import ImportDialog
from importers.ObjectFactory import build_table_object
from importers.PointCloudGridBuilder import build_grid_from_centres
from models.project.Project import Project
from renderers.corner_point_renderer import render_corner_point_grid


class PointCloudGridBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def centres():
        return pd.DataFrame([(x, y, z, x + y + z) for z in (10., 20.)
                             for y in (0., 2.) for x in (0., 3.)],
                            columns=["Xcoord", "Ycoord", "Zcoord", "grade"])

    def test_rows_create_one_cell_per_centre_and_keep_holes_inactive(self):
        table = self.centres().drop(index=3).reset_index(drop=True)
        grid, method = build_grid_from_centres(table, ("Xcoord", "Ycoord", "Zcoord"),
                                               ("grade",), method="auto")
        self.assertEqual(method, "rows")
        self.assertEqual(grid.dimensions, (2, 2, 2))
        self.assertEqual(grid.active_count, 7)
        self.assertFalse(grid.actnum[0, 1, 1])
        np.testing.assert_allclose(grid.coord[0, 0, 0], [-1.5, -1, 5])
        self.assertEqual(grid.properties["grade"][1, 1, 1], 25)
        self.assertEqual(grid.properties["CENTER_X"][1, 1, 1], 3)
        self.assertEqual(grid.properties["N_POINTS"].sum(), 7)
        self.assertEqual(render_corner_point_grid(grid).n_cells, 7)

    def test_scattered_centres_use_uniform_grid_and_average_samples(self):
        table = pd.DataFrame({"x": [0., 0., 3., 6., 8.],
                              "y": [0., 0., 2., 7., 9.],
                              "z": [0., 0., 4., 2., 8.],
                              "value": [2., 4., 7., 8., 9.]})
        grid, method = build_grid_from_centres(table, ("x", "y", "z"), ("value",),
                                               method="auto", dimensions=(4, 3, 2))
        self.assertEqual(method, "uniform")
        self.assertEqual(grid.dimensions, (4, 3, 2))
        self.assertEqual(grid.properties["N_POINTS"].sum(), len(table))
        self.assertEqual(grid.properties["N_POINTS"].max(), 2)
        self.assertEqual(grid.properties["value"][0, 0, 0], 3)
        self.assertEqual(grid.properties["CENTER_X"][0, 0, 0], 0)
        self.assertLess(grid.active_count, np.prod(grid.dimensions))
        with self.assertRaisesRegex(ValueError, "ряды"):
            build_grid_from_centres(table, ("x", "y", "z"), ("value",), method="rows")

    def test_existing_cells_expand_across_empty_bin_without_adding_cells(self):
        table = pd.DataFrame({"x": [0., 2.], "y": [0., 0.], "z": [0., 0.],
                              "value": [10., 20.]})
        kwargs = dict(method="uniform", dimensions=(3, 1, 1))
        joined, _ = build_grid_from_centres(table, ("x", "y", "z"), ("value",),
                                            connect_existing=True, **kwargs)
        separate, _ = build_grid_from_centres(table, ("x", "y", "z"), ("value",),
                                              connect_existing=False, **kwargs)
        self.assertEqual(joined.active_count, separate.active_count)
        self.assertFalse(joined.actnum[0, 0, 1])
        self.assertIsNotNone(joined.explicit_corners)
        self.assertIsNone(separate.explicit_corners)
        self.assertAlmostEqual(joined.cell_corners()[0, :, 0].max(), 1)
        self.assertAlmostEqual(joined.cell_corners()[1, :, 0].min(), 1)
        self.assertLess(separate.cell_corners()[0, :, 0].max(),
                        separate.cell_corners()[1, :, 0].min())
        mesh = render_corner_point_grid(joined)
        self.assertEqual(mesh.n_cells, 2)
        self.assertEqual(mesh.extract_surface(algorithm="dataset_surface").n_cells, 10)
        np.testing.assert_allclose(mesh.cell_data["value"], [10, 20])
        np.testing.assert_allclose(mesh.cell_data["N_POINTS"], [1, 1])

    def test_joined_geometry_survives_project_restart(self):
        table = pd.DataFrame({"x": [0., 2.], "y": [0., 0.], "z": [0., 0.],
                              "value": [10., 20.]})
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "gap.csv"
            table.to_csv(source, index=False)
            cube = build_table_object("cube", table, source, ("x", "y", "z"), ("value",),
                                      cube_geometry="uniform", grid_dimensions=(3, 1, 1))
            project = Project.create(directory / "project")
            project.import_file(cube)
            project.save()
            source.unlink()
            loaded = Project.open(project.project_file).cubes()[0]
            np.testing.assert_allclose(loaded.corner_grid.cell_corners(),
                                       cube.corner_grid.cell_corners())
            self.assertEqual(loaded.corner_grid.active_count, 2)
            self.assertTrue(loaded.metadata["connect_existing_cells"])

    def test_vertical_columns_share_faces_across_empty_x_column(self):
        table = pd.DataFrame({"x": [0., 2., 0., 2.], "y": [0.] * 4,
                              "z": [0., 0., 1., 1.], "value": [1., 2., 3., 4.]})
        grid, _ = build_grid_from_centres(table, ("x", "y", "z"), ("value",),
                                          method="uniform", dimensions=(3, 1, 2))
        self.assertEqual(grid.active_count, 4)
        self.assertFalse(grid.actnum[:, 0, 1].any())
        mesh = render_corner_point_grid(grid)
        self.assertEqual(mesh.n_cells, 4)
        self.assertEqual(mesh.extract_surface(algorithm="dataset_surface").n_cells, 16)

    def test_cells_join_across_empty_y_row(self):
        table = pd.DataFrame({"x": [0., 0.], "y": [0., 2.], "z": [0., 0.]})
        grid, _ = build_grid_from_centres(table, ("x", "y", "z"),
                                          method="uniform", dimensions=(1, 3, 1))
        self.assertEqual(grid.active_count, 2)
        self.assertFalse(grid.actnum[0, 1, 0])
        corners = grid.cell_corners()
        self.assertAlmostEqual(corners[0, :, 1].max(), corners[1, :, 1].min())
        self.assertEqual(render_corner_point_grid(grid).extract_surface(
            algorithm="dataset_surface").n_cells, 10)

    def test_sparse_stretching_does_not_overlap_cells(self):
        rng = np.random.default_rng(7)
        for _ in range(40):
            samples = np.argwhere(rng.random((3, 4, 4)) < 0.35)
            table = pd.DataFrame({"x": samples[:, 2].astype(float),
                                  "y": samples[:, 1].astype(float),
                                  "z": samples[:, 0].astype(float)})
            grid, _ = build_grid_from_centres(table, ("x", "y", "z"),
                                              method="uniform", dimensions=(4, 4, 3))
            corners = grid.cell_corners()
            lower, upper = corners.min(axis=1), corners.max(axis=1)
            overlap = np.minimum(upper[:, None, :], upper[None, :, :]) - np.maximum(
                lower[:, None, :], lower[None, :, :])
            positive_volume = np.all(overlap > 1e-8, axis=2)
            np.fill_diagonal(positive_volume, False)
            self.assertFalse(positive_volume.any())

    def test_singleton_axes_and_project_roundtrip(self):
        table = pd.DataFrame({"east": [0., 2., 4.], "north": [100.] * 3,
                              "depth": [50.] * 3, "poro": [0.1, 0.2, 0.3]})
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "centres.csv"
            table.to_csv(source, index=False)
            cube = build_table_object("cube", table, source, ("east", "north", "depth"),
                                      ("poro",), cube_geometry="auto", singleton_size=4)
            self.assertTrue(cube.is_corner_point)
            self.assertEqual(cube.grid_shape, (3, 1, 1))
            np.testing.assert_allclose(cube.coordinates[:, 0], [0, 2, 4])
            self.assertAlmostEqual(cube.corner_grid.coord[0, 0, 1, 2] -
                                   cube.corner_grid.coord[0, 0, 0, 2], 4)
            project = Project.create(directory / "project")
            project.import_file(cube)
            project.save()
            source.unlink()
            reopened = Project.open(project.project_file).cubes()[0]
            self.assertTrue(reopened.is_corner_point)
            self.assertEqual(reopened.metadata["source_point_count"], 3)
            self.assertEqual(reopened.corner_grid.active_count, 3)
            np.testing.assert_allclose(reopened.color_values("poro"), [0.1, 0.2, 0.3])
            np.testing.assert_allclose(reopened.color_values("CENTER_X"), [0, 2, 4])

    def test_import_dialog_defaults_to_corner_point_from_csv_centres(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "centres.csv"
            self.centres().to_csv(source, index=False)
            dialog = ImportDialog()
            dialog.comboBoxObjectType.setCurrentIndex(dialog.comboBoxObjectType.findData("cube"))
            dialog.lineEditPathFile.setText(str(source))
            dialog.load_preview()
            self.assertEqual(dialog.comboBoxCubeGeometry.currentData(), "auto")
            self.assertTrue(dialog.buttonImport.isEnabled())
            dialog.import_data()
            self.assertEqual(dialog.result(), 1)
            self.assertTrue(dialog.import_object.is_corner_point)
            self.assertEqual(dialog.import_object.grid_shape, (2, 2, 2))
            self.assertEqual(dialog.import_object.color_values("grade").size, 8)

    def test_import_dialog_uses_selected_uniform_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "scattered.csv"
            pd.DataFrame({"x": [0., 3., 6., 8.], "y": [0., 2., 7., 9.],
                          "z": [0., 4., 2., 8.], "value": [2., 7., 8., 9.]}).to_csv(source, index=False)
            dialog = ImportDialog()
            dialog.comboBoxObjectType.setCurrentIndex(dialog.comboBoxObjectType.findData("cube"))
            dialog.comboBoxCubeGeometry.setCurrentIndex(dialog.comboBoxCubeGeometry.findData("uniform"))
            for spin, count in zip(dialog.cube_dimension_spins, (4, 3, 2)):
                spin.setValue(count)
            dialog.lineEditPathFile.setText(str(source))
            dialog.load_preview()
            dialog.import_data()
            self.assertEqual(dialog.result(), 1)
            self.assertEqual(dialog.import_object.grid_shape, (4, 3, 2))
            self.assertEqual(dialog.import_object.corner_grid.properties["N_POINTS"].sum(), 4)

    def test_import_dialog_can_leave_empty_intervals_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "gap.csv"
            pd.DataFrame({"x": [0., 2.], "y": [0., 0.], "z": [0., 0.]}).to_csv(
                source, index=False)
            dialog = ImportDialog()
            dialog.comboBoxObjectType.setCurrentIndex(dialog.comboBoxObjectType.findData("cube"))
            dialog.comboBoxCubeGeometry.setCurrentIndex(dialog.comboBoxCubeGeometry.findData("uniform"))
            for spin, count in zip(dialog.cube_dimension_spins, (3, 1, 1)):
                spin.setValue(count)
            dialog.cubeConnectCheck.setChecked(False)
            dialog.lineEditPathFile.setText(str(source))
            dialog.load_preview()
            dialog.import_data()
            self.assertEqual(dialog.result(), 1)
            self.assertIsNone(dialog.import_object.corner_grid.explicit_corners)
            self.assertFalse(dialog.import_object.metadata["connect_existing_cells"])


if __name__ == "__main__":
    unittest.main()
