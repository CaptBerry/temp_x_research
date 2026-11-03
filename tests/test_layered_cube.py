import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from gui.MainWindow import MainWindow
from gui.dialogs.ImportDialog import ImportDialog
from importers.DatLayerImporter import load_layer_intervals
from importers.ObjectFactory import build_table_object
from models.LayeredCube import LayeredCube
from models.project.Project import Project
from renderers.corner_point_renderer import render_corner_point_grid
from tests.test_gui_lifecycle import FakeViewer


def sample_table():
    return pd.DataFrame({
        "X": [0., 1., 0., 1.], "Y": [0.] * 4,
        "abs_osl": [-150., -150., -250., -250.],
        "AbsRoof": [-100., -100., -200., -200.],
        "AbsBase": [-200., -200., -300., -300.],
        "layer": [30, 30, 31, 31], "УЭС": [10., 20., 30., 40.],
    })


class LayeredCubeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_layers_are_child_cubes_with_roof_base_geometry_and_values(self):
        collection = build_table_object(
            "cube", sample_table(), "layers.txt", ("X", "Y", "abs_osl"),
            ("abs_osl", "УЭС"), cube_geometry="layered", layer_column="layer",
            roof_column="AbsRoof", base_column="AbsBase")
        self.assertIsInstance(collection, LayeredCube)
        self.assertEqual([child.metadata["layer_index"] for child in collection.layers], [1, 2])
        self.assertEqual([child.metadata["layer_name"] for child in collection.layers], ["30", "31"])
        self.assertEqual([child.name for child in collection.layers], ["1. 30", "2. 31"])
        self.assertTrue(all(child.parent is collection for child in collection.layers))
        first = collection.get_layer(30)
        self.assertEqual(first.grid_shape, (2, 1, 1))
        self.assertEqual(first.corner_grid.active_count, 2)
        np.testing.assert_allclose(first.corner_grid.cell_corners()[:, :, 2].min(axis=1), [-200, -200])
        np.testing.assert_allclose(first.corner_grid.cell_corners()[:, :, 2].max(axis=1), [-100, -100])
        np.testing.assert_allclose(first.color_values("УЭС"), [10, 20])
        np.testing.assert_allclose(first.color_values("LAYER_INDEX"), [1, 1])
        np.testing.assert_allclose(first.color_values("abs_osl"), [-150, -150])
        self.assertEqual(render_corner_point_grid(first.corner_grid).extract_surface(
            algorithm="dataset_surface").n_cells, 10)

    def test_layered_cube_survives_save_and_reopen_without_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "layers.tsv"
            sample_table().to_csv(source, sep="\t", index=False)
            collection = build_table_object(
                "cube", sample_table(), source, ("X", "Y", "abs_osl"), ("УЭС",),
                cube_geometry="layered", layer_column="layer",
                roof_column="AbsRoof", base_column="AbsBase")
            project = Project.create(directory / "project")
            project.import_file(collection)
            project.set_visible(collection.get_layer(31), False)
            project.save()
            source.unlink()
            reopened = Project.open(project.project_file)
            loaded = next(obj for obj in reopened.walk() if isinstance(obj, LayeredCube))
            self.assertEqual(len(loaded.layers), 2)
            self.assertEqual(loaded.layer_column, "layer")
            self.assertEqual([layer.metadata["layer_index"] for layer in loaded.layers], [1, 2])
            self.assertEqual([layer.metadata["layer_name"] for layer in loaded.layers], ["30", "31"])
            self.assertFalse(loaded.get_layer(31).visible)
            np.testing.assert_allclose(loaded.get_layer(30).color_values("УЭС"), [10, 20])
            np.testing.assert_allclose(loaded.get_layer(31).corner_grid.cell_corners(),
                                       collection.get_layer(31).corner_grid.cell_corners())

    def test_import_dialog_selects_layer_roof_and_base_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "layers.tsv"
            sample_table().to_csv(source, sep="\t", index=False)
            dialog = ImportDialog()
            dialog.comboBoxObjectType.setCurrentIndex(dialog.comboBoxObjectType.findData("cube"))
            dialog.comboBoxCubeGeometry.setCurrentIndex(dialog.comboBoxCubeGeometry.findData("layered"))
            dialog.lineEditPathFile.setText(str(source))
            dialog.load_preview()
            self.assertEqual(dialog.comboBoxLayer.currentText(), "layer")
            self.assertEqual(dialog.comboBoxRoof.currentText(), "AbsRoof")
            self.assertEqual(dialog.comboBoxBase.currentText(), "AbsBase")
            self.assertIn("abs_osl", dialog.selected_parameters())
            dialog.import_data()
            self.assertEqual(dialog.result(), 1)
            self.assertIsInstance(dialog.import_object, LayeredCube)
            self.assertEqual(len(dialog.import_object.layers), 2)

    def test_dat_intervals_are_read_once_and_ranked_by_absolute_height(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "all.dat"
            rows = pd.DataFrame({
                "PKX": [0, 0, 0, 1, 1, 1, 1],
                "PKY": [0] * 7,
                "H": [95, 93, 85, 115, 113, 105, 103],
                "lid": ["upper", "upper", "lower", "upper", "upper", "lower", "lower"],
                "layer_id": [None, "upper", "lower", None, "upper", "lower", "lower"],
                "layer_AbsRoof": [None, 100, 90, None, 120, 110, 110],
                "layer_AbsBase": [None, 90, 80, None, 110, 100, 100],
                "layer_Rho": [None, 10, 20, None, 30, 40, 40],
                "X": [0] * 7,
                "AbsRoof": [1] * 7,
                "AbsBase": [0] * 7,
            })
            rows.to_csv(source, sep="\t", index=False)
            intervals = load_layer_intervals(
                source, ("PKX", "PKY"), "layer_id", "layer_AbsRoof",
                "layer_AbsBase", ("layer_Rho",), chunksize=2)
            self.assertEqual(len(intervals), 4)
            cube = build_table_object(
                "cube", intervals.iloc[::-1], source, ("PKX", "PKY", "H"), ("layer_Rho",),
                cube_geometry="layered", layer_column="layer_id",
                roof_column="layer_AbsRoof", base_column="layer_AbsBase")
            self.assertEqual([(layer.metadata["layer_index"], layer.metadata["layer_name"])
                              for layer in cube.layers], [(1, "upper"), (2, "lower")])
            self.assertEqual(cube.get_layer(1).metadata["median_roof"], 110)
            self.assertEqual(cube.get_layer("lower").metadata["median_height"], 95)
            np.testing.assert_allclose(cube.get_layer(2).color_values("LAYER_INDEX"), [2, 2])

            dialog = ImportDialog()
            dialog.lineEditPathFile.setText(str(source))
            dialog.load_preview()
            self.assertEqual(dialog.object_type, "cube")
            self.assertEqual(dialog.comboBoxCubeGeometry.currentData(), "layered")
            self.assertEqual(dialog.comboBoxMapX.currentText(), "PKX")
            self.assertEqual(dialog.comboBoxMapY.currentText(), "PKY")
            self.assertEqual(dialog.comboBoxLayer.currentText(), "layer_id")
            self.assertEqual(dialog.comboBoxRoof.currentText(), "layer_AbsRoof")
            self.assertEqual(dialog.comboBoxBase.currentText(), "layer_AbsBase")
            dialog.import_data()
            self.assertEqual(dialog.result(), 1)
            self.assertEqual(len(dialog.import_object.layers), 2)

    def test_invalid_layer_geometry_is_rejected(self):
        table = sample_table()
        table.loc[0, "AbsBase"] = table.loc[0, "AbsRoof"]
        with self.assertRaisesRegex(ValueError, "не должны совпадать"):
            build_table_object("cube", table, "bad.tsv", ("X", "Y", "abs_osl"),
                               cube_geometry="layered", layer_column="layer",
                               roof_column="AbsRoof", base_column="AbsBase")

    def test_tree_visibility_controls_layer_actors(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = QSettings(str(Path(temporary) / "settings.ini"), QSettings.Format.IniFormat)
            with patch("gui.MainWindow.Viewer3D", FakeViewer):
                window = MainWindow(settings=settings, restore_session=False)
            try:
                project = Project()
                collection = project.import_file(build_table_object(
                    "cube", sample_table(), "layers.tsv", ("X", "Y", "abs_osl"),
                    ("УЭС",), cube_geometry="layered", layer_column="layer",
                    roof_column="AbsRoof", base_column="AbsBase"))
                window.set_project(project)
                self.assertNotIn(collection.uuid, window.viewer.actors)
                self.assertEqual(len(collection.layers), 2)
                self.assertTrue(all(layer.uuid in window.viewer.actors for layer in collection.layers))
                project.set_visible(collection, False)
                window.update_3d_viewer()
                self.assertTrue(all(layer.uuid not in window.viewer.actors
                                    for layer in collection.layers))
                project.set_visible(collection, True)
                project.set_visible(collection.get_layer(31), False)
                window.update_3d_viewer()
                self.assertIn(collection.get_layer(30).uuid, window.viewer.actors)
                self.assertNotIn(collection.get_layer(31).uuid, window.viewer.actors)
            finally:
                window.project.modified = False
                window.close()


if __name__ == "__main__":
    unittest.main()
