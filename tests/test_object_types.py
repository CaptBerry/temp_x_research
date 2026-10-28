import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import pyvista as pv
from PyQt6.QtWidgets import QApplication

from gui.dialogs.ImportDialog import ImportDialog
from importers.ObjectFactory import build_table_object, build_mesh_surface
from models.DataCube import DataCube
from models.PointCloud import PointCloud
from models.Surface import Surface
from models.Well import Well
from models.WellFile import WellFile
from models.project.Project import Project


class ObjectTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def wells_table():
        return pd.DataFrame({
            "id": ["A", "A", "B", "B"],
            "x": [0, 0, 10, 10], "y": [0, 0, 0, 0], "z": [0, -10, 0, -20],
            "gamma": [12, 14, 30, 32],
        })

    def test_well_file_groups_samples_and_survives_missing_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "wells.csv"
            table = self.wells_table()
            table.to_csv(source, index=False)
            collection = build_table_object("wellfile", table, source,
                                            ("x", "y", "z"), ("id", "gamma"), "id")
            self.assertIsInstance(collection, WellFile)
            self.assertEqual(collection.well_ids, ("A", "B"))
            self.assertEqual(collection.get_well("A").trajectory_length, 10)
            self.assertEqual(collection.get_well("B").parameter_values("gamma").tolist(), [30, 32])
            self.assertEqual(collection.parameters, ("gamma",))
            project = Project.create(directory / "project")
            project.import_file(collection)
            project.save()
            source.unlink()
            reopened = Project.open(project.project_file)
            loaded = reopened.well_files()[0]
            self.assertEqual(loaded.well_ids, ("A", "B"))
            self.assertEqual(loaded.get_well("A").well_id, "A")
            self.assertEqual(loaded.get_well("B").trajectory_length, 20)
            self.assertEqual(len(reopened.wells()), 2)

    def test_single_well_rejects_multiple_ids_and_incomplete_samples(self):
        table = self.wells_table()
        with self.assertRaises(ValueError):
            build_table_object("well", table, "well.csv", ("x", "y", "z"), ("gamma",), "id")
        one = table.iloc[:2].copy()
        well = build_table_object("well", one, "well.csv", ("x", "y", "z"), ("gamma",), "id")
        self.assertIsInstance(well, Well)
        self.assertEqual(well.appearance.mode, "wireframe")
        one.loc[1, "gamma"] = np.nan
        with self.assertRaises(ValueError):
            build_table_object("well", one, "well.csv", ("x", "y", "z"), ("gamma",), "id")

    def test_well_file_rejects_other_object_without_detaching_it(self):
        project = Project()
        collection = project.import_file(build_table_object(
            "wellfile", self.wells_table(), "wells.csv", ("x", "y", "z"), ("gamma",), "id"))
        cloud = project.import_file(build_table_object(
            "pointcloud", self.wells_table(), "points.csv", ("x", "y", "z")))
        with self.assertRaises(ValueError):
            project.move(cloud, collection)
        self.assertIs(cloud.parent, project.root)
        self.assertEqual(len(collection.wells), 2)

    def test_cube_regular_grid_sections_and_roundtrip(self):
        table = pd.DataFrame([(x, y, z, x + y + z) for x in (0, 1) for y in (0, 1)
                              for z in (0, 1)], columns=["x", "y", "z", "value"])
        cube = build_table_object("cube", table, "cube.csv", ("x", "y", "z"), ("value",))
        self.assertIsInstance(cube, DataCube)
        self.assertEqual(cube.grid_shape, (2, 2, 2))
        self.assertTrue(cube.is_regular_grid)
        self.assertEqual(len(cube.section("z", 0)), 4)
        axes, dense = cube.dense_values("value")
        self.assertEqual(dense.shape, (2, 2, 2))
        self.assertEqual(dense[1, 1, 1], 3)
        with tempfile.TemporaryDirectory() as temporary:
            project = Project.create(Path(temporary) / "project")
            project.import_file(cube)
            project.save()
            loaded = Project.open(project.project_file).cubes()[0]
            self.assertTrue(loaded.is_regular_grid)
            self.assertEqual(loaded.dense_values("value")[1][1, 1, 1], 3)
        duplicate = pd.concat([table, table.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            build_table_object("cube", duplicate, "cube.csv", ("x", "y", "z"), ("value",))
        categorical = table.rename(columns={"value": "class"}).assign(**{"class": "A"})
        with self.assertRaises(ValueError):
            build_table_object("cube", categorical, "cube.csv", ("x", "y", "z"), ("class",))

    def test_surface_and_pointcloud_import_types(self):
        table = pd.DataFrame({"x": [0, 1, 0], "y": [0, 0, 1], "z": [0, 0, 0]})
        surface = build_table_object("surface", table, "surface.csv", ("x", "y", "z"))
        cloud = build_table_object("pointcloud", table, "points.csv", ("x", "y", "z"))
        self.assertIsInstance(surface, Surface)
        self.assertGreater(len(surface.faces), 0)
        self.assertIs(type(cloud), PointCloud)
        fault_points = pd.DataFrame({"x": [0, 0, 0, 0], "y": [0, 1, 1, 0], "z": [0, 0, 1, 1]})
        fault = build_table_object("surface", fault_points, "fault.csv", ("x", "y", "z"),
                                   surface_kind="fault")
        self.assertEqual(fault.surface_kind, "fault")
        self.assertEqual(fault.face_count, 2)
        self.assertAlmostEqual(fault.area, 1)
        with tempfile.TemporaryDirectory() as temporary:
            project = Project.create(Path(temporary) / "project")
            project.import_file(fault)
            project.save()
            self.assertEqual(Project.open(project.project_file).surfaces()[0].surface_kind, "fault")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "surface.vtp"
            pv.PolyData(np.asarray(surface.vertices), np.asarray(surface.faces)).save(path)
            loaded = build_mesh_surface(path)
            self.assertIsInstance(loaded, Surface)
            self.assertGreater(len(loaded.faces), 0)

    def test_import_dialog_type_selector_creates_well_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wells.csv"
            self.wells_table().to_csv(path, index=False)
            dialog = ImportDialog()
            dialog.comboBoxObjectType.setCurrentIndex(dialog.comboBoxObjectType.findData("wellfile"))
            dialog.lineEditPathFile.setText(str(path))
            dialog.load_preview()
            self.assertEqual(dialog.comboBoxWellId.currentText(), "id")
            self.assertTrue(dialog.buttonImport.isEnabled())
            dialog.import_data()
            self.assertEqual(dialog.result(), 1)
            self.assertIsInstance(dialog.import_object, WellFile)
            self.assertEqual(len(dialog.import_object.wells), 2)

    def test_import_dialog_surface_kind_and_mesh_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "section.vtp"
            pv.Plane().triangulate().save(path)
            dialog = ImportDialog()
            dialog.comboBoxObjectType.setCurrentIndex(dialog.comboBoxObjectType.findData("surface"))
            dialog.comboBoxSurfaceKind.setCurrentIndex(dialog.comboBoxSurfaceKind.findData("section"))
            dialog.lineEditPathFile.setText(str(path))
            dialog.load_preview()
            self.assertTrue(dialog.buttonImport.isEnabled())
            dialog.import_data()
            self.assertEqual(dialog.result(), 1)
            self.assertIsInstance(dialog.import_object, Surface)
            self.assertEqual(dialog.import_object.surface_kind, "section")


if __name__ == "__main__":
    unittest.main()
