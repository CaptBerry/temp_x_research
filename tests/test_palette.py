import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from dataclasses import replace
import math
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtWidgets import QApplication, QDialog

from gui.dialogs.PaletteDialog import PaletteDialog
from models.ColorMap import ColorMap, ColorStop, load_surfer_clr
from models.PointCloud import PointCloud
from models.project.Project import Project


class PaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_load_edit_limits_and_accept(self):
        cloud = PointCloud(dataframe=pd.DataFrame({"x": [0, 1], "y": [0, 0], "z": [0, 1], "grade": [5, 10]}))
        cloud.set_mapping("x", "y", "z", ["grade"])
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "test.clr"
            file.write_text("ColorMap 3 0 2 0\n0 0 0 255 255\n100 255 0 0 255\n", encoding="utf-8")
            dialog = PaletteDialog(cloud)
            dialog.field_combo.setCurrentIndex(dialog.field_combo.findData("grade"))
            with patch("gui.dialogs.PaletteDialog.QFileDialog.getOpenFileName", return_value=(str(file), "")):
                dialog._load()
            dialog.minimum_spin.setValue(2)
            dialog.maximum_spin.setValue(12)
            dialog._add()
            dialog.position_spin.setValue(40)
            dialog._accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.palette.field, "grade")
            self.assertEqual((dialog.palette.minimum, dialog.palette.maximum), (2, 12))
            self.assertEqual(len(dialog.palette.stops), 3)

    def test_surfer_versions_and_opacity(self):
        samples = (
            ("ColorMap 1 1\n0 0 0 255\n50 0 255 0\n100 255 255 0\n", 3, 255),
            ("ColorMap 2 1\n0 0 0 255 200\n50 0 255 0 20\n100 255 255 0 255\n", 3, 200),
            ("ColorMap 3 0 3 2\n0 0 0 255 255\n50 0 255 0 255\n100 255 255 0 255\n0 50\n100 100\n", 3, 128),
        )
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "palette.clr"
            for contents, count, first_alpha in samples:
                file.write_text(contents, encoding="utf-8")
                palette = load_surfer_clr(file, "grade", 2, 20)
                self.assertEqual(len(palette.stops), count)
                self.assertEqual(palette.rgba()[0, 3], first_alpha)
                self.assertEqual(palette.rgba()[-1, :3].tolist(), [255, 255, 0])

    def test_logarithmic_values_and_validation(self):
        palette = ColorMap("grade", 1, 100,
                           (ColorStop(0, "#0000ff"), ColorStop(50, "#00ff00"),
                            ColorStop(100, "#ff0000")), value_scale="log")
        palette.validate()
        self.assertAlmostEqual(palette.value_at(50), 10)
        self.assertAlmostEqual(palette.position_of(10), 50)
        self.assertEqual(ColorMap.from_dict(palette.to_dict()), palette)
        legacy = palette.to_dict()
        legacy.pop("value_scale")
        self.assertEqual(ColorMap.from_dict(legacy).value_scale, "linear")
        with self.assertRaisesRegex(ValueError, "положительными"):
            replace(palette, minimum=0).validate()
        with self.assertRaisesRegex(ValueError, "Неизвестная шкала"):
            replace(palette, value_scale="sqrt").validate()

    def test_dialog_log_scale_uses_positive_range_and_geometric_values(self):
        cloud = PointCloud(dataframe=pd.DataFrame({
            "x": [0, 1, 2, 3], "y": [0] * 4, "z": [0] * 4,
            "grade": [0, 1, 10, 100],
        }))
        cloud.set_mapping("x", "y", "z", ["grade"])
        dialog = PaletteDialog(cloud)
        dialog.field_combo.setCurrentIndex(dialog.field_combo.findData("grade"))
        dialog.scale_combo.setCurrentIndex(dialog.scale_combo.findData("log"))
        self.assertEqual((dialog.palette.minimum, dialog.palette.maximum), (1, 100))
        self.assertEqual(dialog._slider_index(10), 500)
        dialog.stop_list.setCurrentRow(1)
        self.assertAlmostEqual(dialog.value_spin.value(), 10)
        dialog.value_spin.setValue(20)
        self.assertAlmostEqual(dialog.palette.stops[1].position, 100 * math.log10(20) / 2)
        dialog._accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_log_scale_requires_positive_samples(self):
        cloud = PointCloud(dataframe=pd.DataFrame({
            "x": [0, 1], "y": [0, 0], "z": [0, 0], "grade": [-1, 0],
        }))
        cloud.set_mapping("x", "y", "z", ["grade"])
        dialog = PaletteDialog(cloud)
        dialog.field_combo.setCurrentIndex(dialog.field_combo.findData("grade"))
        with patch("gui.dialogs.PaletteDialog.QMessageBox.warning") as warning:
            dialog.scale_combo.setCurrentIndex(dialog.scale_combo.findData("log"))
        self.assertEqual(dialog.palette.value_scale, "linear")
        self.assertEqual(dialog.scale_combo.currentData(), "linear")
        warning.assert_called_once()

    def test_palette_project_roundtrip_and_missing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "palette.clr"
            file.write_text("ColorMap 3 0 2 0\n0 0 0 255 255\n100 255 0 0 255\n", encoding="utf-8")
            cloud = PointCloud(dataframe=pd.DataFrame({"x": [0, 1], "y": [0, 0], "z": [0, 1], "grade": [5, 10]}))
            cloud.set_mapping("x", "y", "z", ["grade"])
            project = Project.create(root / "project")
            project.add(cloud)
            palette = replace(load_surfer_clr(file, "grade", 3, 12), value_scale="log")
            project.set_appearance(cloud, color_map=palette)
            project.save()
            file.unlink()
            restored = Project.open(root / "project")
            other = restored.find_by_id(cloud.uuid)
            self.assertEqual(other.appearance.color_map, palette)
            self.assertEqual(other.color_values("grade").tolist(), [5, 10])
            restored.set_appearance(other, color_map=None)
            self.assertIsNone(other.appearance.color_map)

    def test_invalid_field_does_not_change_project(self):
        cloud = PointCloud(dataframe=pd.DataFrame({"x": [1], "y": [2], "z": [3]}))
        cloud.set_mapping("x", "y", "z")
        project = Project()
        project.add(cloud)
        project.modified = False
        with self.assertRaises(ValueError):
            project.set_appearance(cloud, color_map=ColorMap.default("missing", 0, 1))
        self.assertIsNone(cloud.appearance.color_map)
        self.assertFalse(project.modified)


if __name__ == "__main__":
    unittest.main()
