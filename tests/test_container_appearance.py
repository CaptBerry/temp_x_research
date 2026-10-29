import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from gui.MainWindow import MainWindow
from gui.dialogs.PaletteDialog import PaletteDialog
from importers.ObjectFactory import build_table_object
from models.ColorMap import ColorMap
from models.LayeredCube import LayeredCube
from models.WellFile import WellFile
from models.project.Project import Project
from tests.test_gui_lifecycle import FakeViewer
from tests.test_layered_cube import sample_table


def wells_table():
    return pd.DataFrame({"id": ["A", "A", "B", "B"],
                         "x": [0., 0., 1., 1.], "y": [0.] * 4,
                         "z": [0., -1., 0., -1.], "grade": [1., 2., 3., 4.]})


class ContainerAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_wellfile_palette_and_style_apply_to_every_well_and_survive_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "wells.csv"
            wells_table().to_csv(source, index=False)
            project = Project.create(directory / "project")
            collection = project.import_file(build_table_object(
                "wellfile", wells_table(), source, ("x", "y", "z"), ("grade",), "id"))
            palette = ColorMap.default("grade", 1, 4)
            project.set_appearance(collection, color_map=palette, color="#334455",
                                   mode="points", point_size=9, opacity=0.6,
                                   label_visible=False, label_color="#123456",
                                   label_font="times", label_size=22)
            self.assertEqual(collection.numeric_fields(), ["x", "y", "z", "grade"])
            self.assertTrue(all(well.appearance == collection.appearance for well in collection.wells))
            project.save()
            source.unlink()
            reopened = Project.open(project.project_file)
            loaded = reopened.well_files()[0]
            self.assertIsInstance(loaded, WellFile)
            self.assertEqual(loaded.appearance.color_map, palette)
            self.assertFalse(loaded.appearance.label_visible)
            self.assertEqual((loaded.appearance.label_color, loaded.appearance.label_font,
                              loaded.appearance.label_size), ("#123456", "times", 22))
            self.assertTrue(all(well.appearance == loaded.appearance for well in loaded.wells))

    def test_container_palette_dialog_defaults_to_common_parameter(self):
        wells = build_table_object("wellfile", wells_table(), "wells.csv",
                                   ("x", "y", "z"), ("grade",), "id")
        self.assertEqual(PaletteDialog(wells).palette.field, "grade")
        layers = build_table_object("cube", sample_table(), "layers.tsv",
                                    ("X", "Y", "abs_osl"), ("УЭС",),
                                    cube_geometry="layered", layer_column="layer",
                                    roof_column="AbsRoof", base_column="AbsBase")
        self.assertEqual(PaletteDialog(layers).palette.field, "УЭС")

    def test_layered_container_updates_visible_and_hidden_layers(self):
        project = Project()
        collection = project.import_file(build_table_object(
            "cube", sample_table(), "layers.tsv", ("X", "Y", "abs_osl"), ("УЭС",),
            cube_geometry="layered", layer_column="layer", roof_column="AbsRoof",
            base_column="AbsBase"))
        self.assertIsInstance(collection, LayeredCube)
        project.set_visible(collection.get_layer(31), False)
        palette = ColorMap.default("УЭС", 10, 40)
        project.set_appearance(collection, color_map=palette, mode="wireframe",
                               color="#ff6600", line_width=3)
        self.assertEqual(collection.appearance.color_map, palette)
        self.assertTrue(all(layer.appearance == collection.appearance for layer in collection.layers))
        self.assertFalse(project.is_visible(collection.get_layer(31)))

    def test_invalid_shared_palette_leaves_every_appearance_unchanged(self):
        table = wells_table()
        table["first_only"] = [1., 2., float("nan"), float("nan")]
        table["second_only"] = [float("nan"), float("nan"), 3., 4.]
        project = Project()
        collection = project.import_file(build_table_object(
            "wellfile", table, "wells.csv", ("x", "y", "z"),
            ("first_only", "second_only"), "id"))
        project.modified = False
        before = [collection.appearance, *(well.appearance for well in collection.wells)]
        with self.assertRaisesRegex(ValueError, "всех"):
            project.set_appearance(collection, color_map=ColorMap.default("first_only", 0, 4))
        self.assertEqual(before, [collection.appearance,
                                  *(well.appearance for well in collection.wells)])
        self.assertFalse(project.modified)
        self.assertNotIn("first_only", collection.numeric_fields())

    def test_new_well_inherits_container_style(self):
        project = Project()
        collection = project.import_file(build_table_object(
            "wellfile", wells_table(), "wells.csv", ("x", "y", "z"), ("grade",), "id"))
        project.set_appearance(collection, color_map=ColorMap.default("grade", 1, 6),
                               color="#345678")
        new_rows = pd.DataFrame({"id": ["C", "C"], "x": [2., 2.], "y": [0., 0.],
                                 "z": [0., -1.], "grade": [5., 6.]})
        well = build_table_object("well", new_rows, "new.csv", ("x", "y", "z"),
                                  ("grade",), "id")
        project.add(well, collection)
        self.assertEqual(well.appearance, collection.appearance)

    def test_older_container_nodes_without_style_still_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Project.create(Path(temporary) / "project")
            project.import_file(build_table_object(
                "wellfile", wells_table(), "wells.csv", ("x", "y", "z"),
                ("grade",), "id"))
            project.import_file(build_table_object(
                "cube", sample_table(), "layers.tsv", ("X", "Y", "abs_osl"),
                ("УЭС",), cube_geometry="layered", layer_column="layer",
                roof_column="AbsRoof", base_column="AbsBase"))
            project.save()
            manifest = json.loads(project.project_file.read_text(encoding="utf-8"))
            for node in manifest["tree"]["children"]:
                node.pop("appearance")
            project.project_file.write_text(json.dumps(manifest), encoding="utf-8")
            reopened = Project.open(project.project_file)
            self.assertEqual(reopened.well_files()[0].appearance.mode, "wireframe")
            layered = next(obj for obj in reopened.walk() if isinstance(obj, LayeredCube))
            self.assertEqual(layered.appearance.mode, "surface")

    def test_properties_change_refreshes_all_child_actors_without_toggling_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = QSettings(str(Path(temporary) / "settings.ini"), QSettings.Format.IniFormat)
            with patch("gui.MainWindow.Viewer3D", FakeViewer):
                window = MainWindow(settings=settings, restore_session=False)
            try:
                project = Project()
                collection = project.import_file(build_table_object(
                    "wellfile", wells_table(), "wells.csv", ("x", "y", "z"),
                    ("grade",), "id"))
                window.set_project(project)
                window.select_object(collection.uuid)
                self.assertTrue(window.appearance_editor.fields.isEnabled())
                window._change_appearance(collection.uuid, {
                    "color_map": ColorMap.default("grade", 1, 4), "opacity": 0.4})
                self.assertEqual(set(window.viewer.appearances),
                                 {well.uuid for well in collection.wells})
                self.assertTrue(all(window.viewer.appearances[well.uuid] == collection.appearance
                                    for well in collection.wells))
            finally:
                window.project.modified = False
                window.close()


if __name__ == "__main__":
    unittest.main()
