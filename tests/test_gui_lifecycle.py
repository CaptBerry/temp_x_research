import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor, QCloseEvent, QPalette
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from gui.MainWindow import MainWindow
from gui.dialogs.ImportDialog import ImportDialog
from models.PointCloud import PointCloud
from models.Appearance import Appearance
from models.Surface import Surface
from models.project.Folder import Folder
from models.project.Project import Project
from importers.ObjectFactory import build_table_object


class FakeViewer(QWidget):
    """Use actual Qt widgets while isolating OpenGL in lifecycle tests."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actors = {}
        self.closed = False
        self.appearances = {}
        self.axis_scale = (1, 1, 1)
        self.background = None

    def clear_scene(self):
        self.actors.clear()

    def scene_update(self):
        return nullcontext()

    def add_object(self, obj):
        if isinstance(obj, PointCloud):
            self.actors[obj.uuid] = obj.coordinates

    def focus_on_scene(self):
        pass

    def set_axis_scale(self, scale):
        self.axis_scale = tuple(scale)

    def set_theme(self, background):
        self.background = background

    def update_object_appearance(self, obj):
        self.appearances[obj.uuid] = obj.appearance

    def closeEvent(self, event):
        self.closed = True
        super().closeEvent(event)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.settings = QSettings(str(self.directory / "settings.ini"), QSettings.Format.IniFormat)
        viewer_patch = patch("gui.MainWindow.Viewer3D", FakeViewer)
        viewer_patch.start()
        self.addCleanup(viewer_patch.stop)
        self.window = MainWindow(settings=self.settings, restore_session=False)
        self.addCleanup(self.close_window, self.window)

    @staticmethod
    def close_window(window):
        if window.project is not None:
            window.project.modified = False
        window.close()
        window.deleteLater()

    def attach_project(self):
        project = Project.create(self.directory / "project")
        self.window.set_project(project)
        return project

    def add_cloud(self, project, parent=None):
        cloud = PointCloud("Points", dataframe=pd.DataFrame({"x": [1.], "y": [2.], "z": [3.]}))
        cloud.set_mapping("x", "y", "z")
        project.import_file(cloud, parent)
        self.window.update_project_tree()
        self.window.update_3d_viewer()
        self.window.update_window_state()
        return cloud

    def test_create_import_save_exit_and_restore_last_project(self):
        with patch("gui.MainWindow.QFileDialog.getExistingDirectory", return_value=str(self.directory)), \
                patch("gui.MainWindow.QInputDialog.getText", return_value=("New", True)):
            self.assertTrue(self.window.new_project())
        source = self.directory / "points.csv"
        source.write_text("x,y,z\n1,2,3\n4,5,6\n", encoding="utf-8")
        with patch("gui.MainWindow.ImportDialog") as dialog_class:
            dialog = dialog_class.return_value
            dialog.exec.return_value = 1
            dialog.lineEditPathFile.text.return_value = str(source)
            dialog.dataframe = pd.read_csv(source)
            dialog.coordinate_columns = ("x", "y", "z")
            dialog.parameter_columns = []
            dialog.import_object = PointCloud(source.stem, source, dialog.dataframe)
            dialog.import_object.set_mapping(*dialog.coordinate_columns)
            self.window.show_import_dialog()
        cloud = self.window.project.pointclouds()[0]
        self.assertIn(cloud.uuid, self.window.viewer.actors)
        self.assertTrue(self.window.isWindowModified())
        self.assertTrue(self.window.save_project())
        source.unlink()
        self.assertFalse(self.window.isWindowModified())
        self.window.close()
        reopened = MainWindow(settings=self.settings)
        self.addCleanup(self.close_window, reopened)
        self.assertEqual(reopened.project.name, "New")
        self.assertIn(cloud.uuid, reopened.viewer.actors)
        pd.testing.assert_frame_equal(reopened.project.pointclouds()[0].dataframe, cloud.dataframe)

    def test_tree_edits_update_model_and_visibility_including_parents(self):
        project = self.attach_project()
        folder = project.add(Folder("Folder"))
        cloud = self.add_cloud(project, folder)
        work_item = self.window.projectTree.model().item(0).child(0)
        folder_item = work_item.child(0)
        cloud_item = folder_item.child(0)
        cloud_item.setText("Renamed")
        self.assertEqual(cloud.name, "Renamed")
        folder_item.setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(folder.visible)
        self.assertNotIn(cloud.uuid, self.window.viewer.actors)
        self.assertTrue(self.window.isWindowModified())
        self.window.save_project()
        loaded = Project.open(project.project_file)
        self.assertEqual(loaded.pointclouds()[0].name, "Renamed")
        self.assertFalse(loaded.is_visible(loaded.pointclouds()[0]))

    def test_container_select_all_and_clear_selection(self):
        project = self.attach_project()
        folder = project.add(Folder("Группа"))
        nested = project.add(Folder("Вложенная"), folder)
        cloud = self.add_cloud(project, nested)
        self.window.set_container_visibility(folder, False)
        self.assertTrue(all(not node.visible for node in (folder, nested, cloud)))
        self.assertNotIn(cloud.uuid, self.window.viewer.actors)
        group_item = self.window.projectTree.model().item(0).child(0).child(0)
        self.assertEqual(group_item.checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(group_item.child(0).child(0).checkState(), Qt.CheckState.Unchecked)
        self.window.set_container_visibility(folder, True)
        self.assertTrue(all(node.visible for node in (folder, nested, cloud)))
        self.assertIn(cloud.uuid, self.window.viewer.actors)
        group_item = self.window.projectTree.model().item(0).child(0).child(0)
        self.assertEqual(group_item.checkState(), Qt.CheckState.Checked)
        self.window.save_project()
        restored = Project.open(project.project_file)
        self.assertTrue(all(node.visible for node in restored.walk(restored.find_by_id(folder.uuid))))

    def test_theme_dialog_applies_and_persists_application_theme(self):
        self.assertIn(self.window.action_theme, self.window.menuTools.actions())
        self.assertEqual(self.window.theme, "light")

        def choose_dark(dialog):
            dialog.dark_radio.setChecked(True)
            return QDialog.DialogCode.Accepted

        with patch("gui.MainWindow.ThemeDialog.exec", new=choose_dark):
            self.window.action_theme.trigger()
        self.assertEqual(self.window.theme, "dark")
        self.assertEqual(self.settings.value("theme"), "dark")
        self.assertEqual(self.window.viewer.background, "#1a2028")
        self.assertEqual(self.app.palette().color(QPalette.ColorRole.Window).name(), "#20252d")
        with patch("gui.MainWindow.ThemeDialog.exec", return_value=QDialog.DialogCode.Rejected):
            self.window.action_theme.trigger()
        self.assertEqual(self.window.theme, "dark")
        reopened = MainWindow(settings=self.settings, restore_session=False)
        self.addCleanup(self.close_window, reopened)
        self.assertEqual(reopened.theme, "dark")
        self.assertEqual(reopened.viewer.background, "#1a2028")

    def test_import_well_file_through_main_window(self):
        project = self.attach_project()
        source = self.directory / "wells.csv"
        data = pd.DataFrame({"id": ["A", "A", "B", "B"], "x": [0, 0, 10, 10],
                             "y": [0, 0, 0, 0], "z": [0, -1, 0, -2],
                             "gamma": [1, 2, 3, 4]})
        data.to_csv(source, index=False)
        with patch("gui.MainWindow.ImportDialog") as dialog_class:
            dialog = dialog_class.return_value
            dialog.exec.return_value = 1
            dialog.lineEditPathFile.text.return_value = str(source)
            dialog.import_object = build_table_object("wellfile", data, source,
                ("x", "y", "z"), ("gamma",), "id")
            self.window.show_import_dialog()
        self.assertEqual(len(project.well_files()), 1)
        self.assertEqual(len(project.wells()), 2)
        self.assertEqual(len(self.window.viewer.actors), 2)
        editor = self.window.appearance_editor
        self.assertFalse(editor.label_group.isHidden())
        editor.label_font_combo.setCurrentIndex(editor.label_font_combo.findData("courier"))
        editor.label_size_spin.setValue(24)
        with patch("gui.custom_widgets.AppearanceEditor.QColorDialog.getColor",
                   return_value=QColor("#345678")):
            editor.label_color_button.click()
        editor.label_visible_check.setChecked(False)
        self.assertTrue(all(not well.appearance.label_visible and
                            well.appearance.label_font == "courier" and
                            well.appearance.label_size == 24 and
                            well.appearance.label_color == "#345678"
                            for well in project.wells()))
        self.window.save_project()
        loaded = Project.open(project.project_file).well_files()[0]
        self.assertEqual(loaded.well_ids, ("A", "B"))
        self.assertFalse(loaded.appearance.label_visible)

    def test_delete_changes_domain_and_clears_view(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        with patch("gui.MainWindow.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.delete_object(cloud)
        self.assertEqual(project.pointclouds(), [])
        self.assertEqual(self.window.viewer.actors, {})
        self.window.save_project()
        self.assertEqual(Project.open(project.project_file).pointclouds(), [])

    def test_cancel_close_leaves_window_and_project_open(self):
        project = self.attach_project()
        self.add_cloud(project)
        event = QCloseEvent()
        with patch("gui.MainWindow.QMessageBox.warning", return_value=QMessageBox.StandardButton.Cancel):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertIs(self.window.project, project)
        self.assertFalse(self.window.viewer.closed)

    def test_failed_save_prevents_closing(self):
        project = self.attach_project()
        self.add_cloud(project)
        event = QCloseEvent()
        with patch("gui.MainWindow.QMessageBox.warning", return_value=QMessageBox.StandardButton.Save), \
                patch.object(project, "save", side_effect=OSError("disk full")), \
                patch.object(self.window, "_report_error") as report:
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(project.modified)
        report.assert_called_once()

    def test_save_on_exit_and_discard_close_project(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        event = QCloseEvent()
        with patch("gui.MainWindow.QMessageBox.warning", return_value=QMessageBox.StandardButton.Save):
            self.window.closeEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertIsNotNone(Project.open(project.project_file).find_by_id(cloud.uuid))
        project.rename(cloud, "Discarded")
        with patch("gui.MainWindow.QMessageBox.warning", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.window.close_project())
        self.assertIsNone(self.window.project)
        self.assertEqual(self.window.projectTree.model().rowCount(), 0)
        self.assertEqual(self.window.viewer.actors, {})
        self.assertFalse(self.settings.contains("last_project"))
        self.assertEqual(Project.open(project.project_file).pointclouds()[0].name, "Points")

    def test_cancel_save_as_during_close(self):
        project = Project()
        project.add(Folder("Unsaved"))
        self.window.set_project(project)
        with patch("gui.MainWindow.QMessageBox.warning", return_value=QMessageBox.StandardButton.Save), \
                patch("gui.MainWindow.QFileDialog.getExistingDirectory", return_value=""):
            self.assertFalse(self.window.close_project())
        self.assertIs(self.window.project, project)

    def test_invalid_open_does_not_replace_current_project(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        invalid = self.directory / "bad.json"
        invalid.write_text("{broken", encoding="utf-8")
        with patch("gui.MainWindow.QFileDialog.getOpenFileName", return_value=(str(invalid), "")), \
                patch.object(self.window, "_report_error") as report:
            self.assertFalse(self.window.open_project())
        self.assertIs(self.window.project, project)
        self.assertIn(cloud.uuid, self.window.viewer.actors)
        report.assert_called_once()

    def test_open_same_file_after_save_uses_new_data(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        with patch("gui.MainWindow.QFileDialog.getOpenFileName", return_value=(str(project.project_file), "")), \
                patch("gui.MainWindow.QMessageBox.warning", return_value=QMessageBox.StandardButton.Save):
            self.assertTrue(self.window.open_project())
        self.assertIn(cloud.uuid, self.window.viewer.actors)
        self.assertEqual(len(self.window.project.pointclouds()), 1)

    def test_new_project_cancel_keeps_previous_scene(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        with patch("gui.MainWindow.QFileDialog.getExistingDirectory", return_value=str(self.directory)), \
                patch("gui.MainWindow.QInputDialog.getText", return_value=("Other", True)), \
                patch("gui.MainWindow.QMessageBox.warning", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.window.new_project())
        self.assertIs(self.window.project, project)
        self.assertIn(cloud.uuid, self.window.viewer.actors)
        self.assertFalse((self.directory / "Other").exists())

    def test_save_as_action_creates_independent_copy(self):
        project = self.attach_project()
        self.add_cloud(project)
        destination = self.directory / "copy"
        with patch("gui.MainWindow.QFileDialog.getExistingDirectory", return_value=str(destination)):
            self.window.action_save_as_project.trigger()
        self.assertEqual(project.project_path, destination)
        self.assertEqual(len(Project.open(destination).pointclouds()), 1)
        self.assertEqual(len(Project.open(self.directory / "project").pointclouds()), 0)

    def test_import_dialog_headerless_and_invalid_mapping(self):
        source = self.directory / "headerless.csv"
        source.write_text("1;2;3;5\n4;5;6;7\n", encoding="utf-8")
        dialog = ImportDialog(self.window)
        dialog.checkBox_Header.setChecked(False)
        dialog.lineEditPathFile.setText(str(source))
        dialog.load_preview()
        self.assertTrue(dialog.buttonImport.isEnabled())
        self.assertEqual(dialog.comboBoxMapX.currentText(), "0")
        self.assertEqual(dialog.comboBoxMapY.currentText(), "1")
        self.assertEqual(dialog.comboBoxMapZ.currentText(), "2")
        dialog.comboBoxMapY.setCurrentIndex(0)
        with patch("gui.dialogs.ImportDialog.QMessageBox.warning") as warning:
            dialog.import_data()
        warning.assert_called_once()
        self.assertEqual(dialog.result(), 0)
        dialog.comboBoxMapY.setCurrentIndex(1)
        dialog.import_data()
        self.assertEqual(dialog.result(), 1)
        self.assertEqual(dialog.parameter_columns, ["3"])

    def test_missing_import_file_shows_error_and_disables_import(self):
        dialog = ImportDialog(self.window)
        dialog.lineEditPathFile.setText(str(self.directory / "missing.csv"))
        with patch("gui.dialogs.ImportDialog.QMessageBox.warning") as warning:
            dialog.load_preview()
        warning.assert_called_once()
        self.assertFalse(dialog.buttonImport.isEnabled())

    def test_selecting_object_does_not_modify_project(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        project.save()
        self.window.select_object(cloud.uuid)
        self.assertFalse(project.modified)
        self.assertEqual(self.window.appearance_editor.mode_combo.currentData(), "points")
        self.assertTrue(self.window.appearance_editor.fields.isEnabled())
        self.window.select_object(project.root.uuid)
        self.assertFalse(self.window.appearance_editor.fields.isEnabled())
        self.assertFalse(project.modified)

    def test_edit_appearance_updates_selected_object_and_persists(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        other = self.add_cloud(project)
        project.save()
        self.window.select_object(cloud.uuid)
        editor = self.window.appearance_editor
        editor.size_spin.setValue(16)
        editor.outline_check.setChecked(True)
        editor.width_spin.setValue(3)
        editor.transparency_spin.setValue(40)
        editor.shape_combo.setCurrentIndex(editor.shape_combo.findData("square"))
        from PyQt6.QtGui import QColor
        with patch("gui.custom_widgets.AppearanceEditor.QColorDialog.getColor", return_value=QColor("#e11d48")):
            editor.color_button.click()
        self.assertEqual(cloud.appearance.color, "#e11d48")
        self.assertEqual(cloud.appearance.point_size, 16)
        self.assertEqual(cloud.appearance.point_shape, "square")
        self.assertTrue(cloud.appearance.outline)
        self.assertEqual(cloud.appearance.line_width, 3)
        self.assertAlmostEqual(cloud.appearance.opacity, 0.6)
        self.assertEqual(other.appearance, Appearance())
        self.assertEqual(self.window.viewer.appearances[cloud.uuid], cloud.appearance)
        self.assertTrue(self.window.isWindowModified())
        self.window.update_project_tree()
        self.assertEqual(self.window.appearance_editor._object_id, cloud.uuid)
        self.window.save_project()
        self.assertEqual(Project.open(project.project_file).find_by_id(cloud.uuid).appearance, cloud.appearance)

    def test_mode_controls_and_reset(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        self.window.select_object(cloud.uuid)
        editor = self.window.appearance_editor
        editor.outline_check.setChecked(True)
        editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("spheres"))
        self.assertEqual(cloud.appearance.mode, "spheres")
        self.assertFalse(editor.outline_check.isEnabled())
        self.assertFalse(editor.width_spin.isEnabled())
        self.assertTrue(editor.size_spin.isEnabled())
        editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("points"))
        self.assertTrue(editor.outline_check.isChecked())
        self.assertTrue(editor.width_spin.isEnabled())
        editor.reset_button.click()
        self.assertEqual(cloud.appearance, Appearance())
        surface = project.add(Surface())
        self.window.update_project_tree()
        self.window.select_object(surface.uuid)
        editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("wireframe"))
        self.assertFalse(editor.size_spin.isEnabled())
        self.assertTrue(editor.width_spin.isEnabled())
        self.assertFalse(editor.outline_color_button.isEnabled())

    def test_axis_scale_is_available_without_object_selection(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        other = self.add_cloud(project)
        project.save()
        self.window.select_object(project.root.uuid)
        self.assertFalse(self.window.appearance_editor.fields.isEnabled())
        axes = self.window.axis_scale_editor
        self.assertTrue(axes.isEnabled())
        axes.spins["x"].setValue(2)
        axes.spins["y"].setValue(0.5)
        axes.spins["z"].setValue(4)
        self.assertEqual(project.axis_scale, (2, 0.5, 4))
        self.assertEqual(self.window.viewer.axis_scale, (2, 0.5, 4))
        self.assertFalse(hasattr(cloud.appearance, "scale_x"))
        self.assertEqual(other.appearance, Appearance())
        self.window.save_project()
        self.assertEqual(Project.open(project.project_file).axis_scale, (2, 0.5, 4))
        axes.reset_button.click()
        self.assertEqual(project.axis_scale, (1, 1, 1))

    def test_cancel_color_dialog_does_not_dirty_project(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        project.save()
        self.window.select_object(cloud.uuid)
        from PyQt6.QtGui import QColor
        with patch("gui.custom_widgets.AppearanceEditor.QColorDialog.getColor", return_value=QColor()):
            self.window.appearance_editor.color_button.click()
        self.assertFalse(project.modified)
        self.assertEqual(cloud.appearance, Appearance())

    def test_failed_appearance_update_restores_model_and_editor(self):
        project = self.attach_project()
        cloud = self.add_cloud(project)
        project.save()
        self.window.select_object(cloud.uuid)
        with patch.object(self.window.viewer, "update_object_appearance", side_effect=[RuntimeError("render failed"), None]), \
                patch.object(self.window, "_report_error") as report:
            self.window.appearance_editor.size_spin.setValue(20)
        self.assertFalse(project.modified)
        self.assertEqual(cloud.appearance, Appearance())
        self.assertEqual(self.window.appearance_editor.size_spin.value(), 6)
        report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
