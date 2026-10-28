import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest

import numpy as np
from PyQt6.QtWidgets import QApplication

from gui.dialogs.ImportDialog import ImportDialog
from importers.GrdeclImporter import load_grdecl
from importers.ObjectFactory import build_corner_point_cube
from models.project.Project import Project
from renderers.corner_point_renderer import render_corner_point_grid


def write_fixture(directory):
    directory = Path(directory)
    path = directory / "faulted.grdecl"
    pillars = []
    for y in (0, 1):
        for x in (0, 1, 2):
            pillars.extend((x, y, 0, x + 2, y, 20))
    # Logical (2K, 2J, 2I): cell 2 begins two units deeper across
    # the shared pillar. The second cell in the top layer is inactive.
    zcorn = np.empty((4, 2, 4))
    for k in (0, 1):
        for j in (0, 1):
            zcorn[2 * k, j] = (10 * k, 10 * k, 10 * k + 2, 10 * k + 2)
            zcorn[2 * k + 1, j] = (10 * k + 10, 10 * k + 10,
                                   10 * k + 12, 10 * k + 12)
    path.write_text("SPECGRID\n2 1 2 1 F /\nMETRIC\nCOORD\n" +
                    " ".join(map(str, pillars)) + " /\nZCORN\n" +
                    " ".join(map(str, zcorn.ravel())) +
                    " /\nACTNUM\n1 0 2*1 /\nINCLUDE 'properties.inc' /\n",
                    encoding="utf-8")
    (directory / "properties.inc").write_text("PORO\n0.1 0.2 0.3 4.0D-1 /\n",
                                               encoding="utf-8")
    return path


class CornerPointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_geometry_faults_mask_properties_and_vtk_cells(self):
        with tempfile.TemporaryDirectory() as temporary:
            grid = load_grdecl(write_fixture(temporary))
            self.assertEqual(grid.dimensions, (2, 1, 2))
            self.assertEqual(grid.active_count, 3)
            np.testing.assert_array_equal(grid.active_indices,
                                          [[0, 0, 0], [1, 0, 0], [1, 0, 1]])
            corners = grid.cell_corners()
            np.testing.assert_allclose(corners[0, 0], [0, 0, 0])
            np.testing.assert_allclose(corners[0, 4], [1, 0, 10])
            np.testing.assert_allclose(corners[2, 0], [2.2, 0, 12])
            self.assertAlmostEqual(corners[2, 0, 2] - corners[1, 1, 2], 2)
            mesh = render_corner_point_grid(grid)
            self.assertEqual(mesh.n_cells, 3)
            self.assertLess(mesh.n_points, 24)
            self.assertEqual(mesh.extract_surface(algorithm="dataset_surface").n_cells, 16)
            np.testing.assert_allclose(mesh.get_cell(2).points[0], corners[2, 0])
            np.testing.assert_allclose(mesh.cell_data["PORO"], [0.1, 0.3, 0.4])
            np.testing.assert_array_equal(mesh.cell_data["K"], [1, 2, 2])

    def test_project_roundtrip_without_grdecl_or_include(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = write_fixture(directory)
            cube = build_corner_point_cube(source)
            self.assertTrue(cube.is_corner_point)
            self.assertEqual(cube.appearance.mode, "surface")
            self.assertEqual(cube.grid_shape, (2, 1, 2))
            self.assertEqual(len(cube.section("z", 15, tolerance=10)), 3)
            project = Project.create(directory / "project")
            project.import_file(cube)
            project.set_appearance(cube, color="#ff0000", opacity=0.5)
            project.save()
            source.unlink()
            (directory / "properties.inc").unlink()
            reopened = Project.open(project.project_file)
            loaded = reopened.cubes()[0]
            self.assertEqual(loaded.point_count, 3)
            self.assertEqual(loaded.appearance.color, "#ff0000")
            self.assertEqual(loaded.appearance.opacity, 0.5)
            np.testing.assert_allclose(loaded.corner_grid.cell_corners(), cube.corner_grid.cell_corners())
            np.testing.assert_allclose(loaded.color_values("PORO"), [0.1, 0.3, 0.4])
            reopened.save_as(directory / "copy")
            copied = Project.open(directory / "copy")
            self.assertEqual(copied.cubes()[0].corner_grid.active_count, 3)

    def test_dialog_imports_grdecl_as_cube(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = write_fixture(temporary)
            dialog = ImportDialog()
            dialog.comboBoxObjectType.setCurrentIndex(dialog.comboBoxObjectType.findData("cube"))
            dialog.lineEditPathFile.setText(str(source))
            dialog.load_preview()
            self.assertTrue(dialog.buttonImport.isEnabled())
            self.assertFalse(dialog.comboBoxMapX.isEnabled())
            dialog.import_data()
            self.assertEqual(dialog.result(), 1)
            self.assertTrue(dialog.import_object.is_corner_point)
            self.assertEqual(dialog.import_object.point_count, 3)

    def test_invalid_and_unsupported_decks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = write_fixture(temporary)
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("ACTNUM\n1 0 2*1 /\n", ""), encoding="utf-8")
            self.assertEqual(load_grdecl(path).active_count, 4)
            path.write_text(text.replace("1 0 2*1", "1 2 2*1"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ACTNUM"):
                load_grdecl(path)
            path.write_text(text + "MAPAXES\n0 1 0 0 1 0 /\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "MAPAXES"):
                load_grdecl(path)
            path.write_text(text.replace("2 1 2 1 F", "3 1 2 1 F"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "COORD"):
                load_grdecl(path)


if __name__ == "__main__":
    unittest.main()
