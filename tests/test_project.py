import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from importers.CsvImporter import CsvImporter
from models.PointCloud import PointCloud
from models.Surface import Surface
from models.project.Folder import Folder
from models.project.Project import Project
from models.project.ProjectStorage import ProjectStorage
from models.project.TableStorage import TableStorage


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.project = Project.create(self.directory / "project", "Исследование")

    def cloud(self, name="Точки"):
        source = self.directory / "points.csv"
        source.write_text("x;y;z;label\n1.25;2;3;A\n4.5;5;6;B\n", encoding="utf-8")
        cloud = PointCloud(name, source, CsvImporter().load(source))
        cloud.set_mapping("x", "y", "z", ["label"])
        return cloud

    def test_create_and_reopen_empty_project(self):
        reopened = Project.open(self.project.project_file)
        self.assertEqual(reopened.name, "Исследование")
        self.assertEqual(reopened.root.uuid, self.project.root.uuid)
        self.assertFalse(reopened.modified)
        self.assertTrue(reopened.validate())

    def test_axis_scale_is_project_wide_and_persists(self):
        cloud = self.project.import_file(self.cloud())
        self.assertTrue(self.project.set_axis_scale(2, 0.5, 4))
        self.assertTrue(self.project.modified)
        self.assertEqual(cloud.appearance.opacity, 1)
        self.project.save()
        reopened = Project.open(self.project.project_file)
        self.assertEqual(reopened.axis_scale, (2, 0.5, 4))
        self.assertFalse(reopened.modified)
        self.assertFalse(reopened.set_axis_scale(2, 0.5, 4))
        for scale in ((0, 1, 1), (1, -1, 1), (1, float("inf"), 1), (True, 1, 1)):
            with self.assertRaises(ValueError):
                reopened.set_axis_scale(*scale)
            self.assertEqual(reopened.axis_scale, (2, 0.5, 4))
            self.assertFalse(reopened.modified)

    def test_old_per_object_scale_migrates_to_axes(self):
        cloud = self.project.import_file(self.cloud())
        self.project.save()
        manifest = json.loads(self.project.project_file.read_text(encoding="utf-8"))
        manifest.pop("axis_scale")
        manifest["tree"]["children"][0]["appearance"].update(
            scale_x=2, scale_y=0.5, scale_z=4)
        self.project.project_file.write_text(json.dumps(manifest), encoding="utf-8")
        reopened = Project.open(self.project.project_file)
        self.assertEqual(reopened.axis_scale, (2, 0.5, 4))
        self.assertTrue(reopened.modified)
        self.assertFalse(hasattr(reopened.find_by_id(cloud.uuid).appearance, "scale_x"))

    def test_data_tree_and_flags_survive_restart_without_source(self):
        parent = self.project.add(Folder("Папка"))
        nested = self.project.add(Folder("Вложенная"), parent)
        cloud = self.project.import_file(self.cloud(), nested)
        cloud.metadata = {"units": "м", "enabled": True}
        cloud.locked = True
        self.project.rename(cloud, "Новое имя")
        self.project.set_visible(parent, False)
        self.project.save()
        (self.directory / "points.csv").unlink()
        expected = cloud.dataframe.copy()
        object_id, folder_id = cloud.uuid, parent.uuid
        self.project.close()
        reopened = Project.open(self.directory / "project")
        loaded = reopened.find_by_id(object_id)
        pd.testing.assert_frame_equal(loaded.dataframe, expected, check_exact=True)
        self.assertEqual(loaded.name, "Новое имя")
        self.assertEqual(loaded.parameters, ["label"])
        self.assertTrue(loaded.locked)
        self.assertEqual(loaded.metadata["units"], "м")
        self.assertEqual(loaded.parent.parent.uuid, folder_id)
        self.assertIs(loaded.root, reopened.root)
        self.assertFalse(reopened.is_visible(loaded))
        self.assertTrue(Path(loaded.file_path).is_relative_to(reopened.project_path))

    def test_container_visibility_changes_whole_subtree_and_survives_reopen(self):
        parent = self.project.add(Folder("Контейнер"))
        nested = self.project.add(Folder("Вложенная"), parent)
        cloud = self.project.import_file(self.cloud(), nested)
        self.assertTrue(self.project.set_subtree_visible(parent, False))
        self.assertTrue(all(not node.visible for node in (parent, nested, cloud)))
        self.project.save()
        reopened = Project.open(self.project.project_file)
        loaded = reopened.find_by_id(parent.uuid)
        self.assertFalse(reopened.modified)
        self.assertFalse(reopened.set_subtree_visible(loaded, False))
        self.assertFalse(reopened.modified)
        self.assertTrue(reopened.set_subtree_visible(loaded, True))
        self.assertTrue(all(node.visible for node in reopened.walk(loaded)))
        with self.assertRaisesRegex(ValueError, "контейнеру"):
            reopened.set_subtree_visible(reopened.find_by_id(cloud.uuid), False)

    def test_save_as_and_move_are_independent(self):
        cloud = self.project.import_file(self.cloud())
        self.project.save()
        original = self.project.project_path
        self.project.rename(cloud, "Копия")
        self.project.save_as(self.directory / "copy")
        self.assertEqual(Project.open(original).pointclouds()[0].name, "Точки")
        moved = self.directory / "moved"
        # Copy only the project directory, then make the previous paths unavailable.
        shutil.copytree(self.project.project_path, moved)
        original.rename(self.directory / "original-renamed")
        self.project.project_path.rename(self.directory / "copy-renamed")
        (self.directory / "points.csv").unlink()
        reopened = Project.open(moved)
        self.assertEqual(reopened.pointclouds()[0].name, "Копия")
        pd.testing.assert_frame_equal(reopened.pointclouds()[0].dataframe, cloud.dataframe)
        self.assertTrue(Path(reopened.pointclouds()[0].file_path).is_file())

    def test_failed_commit_keeps_old_manifest_and_dirty_state(self):
        cloud = self.project.import_file(self.cloud())
        self.project.save()
        before = self.project.project_file.read_bytes()
        saved_at = self.project.last_saved
        cloud.dataframe.loc[0, "x"] = 42.0
        self.project.mark_modified()
        with patch("models.project.ProjectStorage.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.project.save()
        self.assertEqual(self.project.project_file.read_bytes(), before)
        self.assertEqual(self.project.last_saved, saved_at)
        self.assertTrue(self.project.modified)
        self.assertEqual(Project.open(self.project.project_file).pointclouds()[0].dataframe.loc[0, "x"], 1.25)
        self.assertFalse(list(self.project.project_path.rglob(".saving-*")))

    def test_failure_after_assets_does_not_replace_manifest(self):
        cloud = self.project.import_file(self.cloud())
        self.project.save()
        before = self.project.project_file.read_bytes()
        self.project.rename(cloud, "Unsaved")
        write = ProjectStorage._write_atomic

        def fail_manifest(path, content):
            if Path(path).name == "project.json":
                raise OSError("manifest write failed")
            return write(path, content)

        with patch.object(ProjectStorage, "_write_atomic", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                self.project.save()
        self.assertEqual(self.project.project_file.read_bytes(), before)
        self.assertTrue(self.project.modified)

    def test_failed_save_as_does_not_change_current_path(self):
        cloud = self.project.import_file(self.cloud())
        self.project.save()
        original, source = self.project.project_path, cloud.file_path
        self.project.rename_project("Changed")
        with patch.object(ProjectStorage, "_write_atomic", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                self.project.save_as(self.directory / "copy")
        self.assertEqual(self.project.project_path, original)
        self.assertEqual(cloud.file_path, source)
        self.assertTrue(self.project.modified)
        self.assertFalse((self.directory / "copy").exists())
        self.project.save_as(self.directory / "copy")
        self.assertEqual(Project.open(self.directory / "copy").name, "Changed")

    def test_failed_initial_save_can_be_retried_in_empty_directory(self):
        destination = self.directory / "new"
        destination.mkdir()
        with patch.object(ProjectStorage, "_write_atomic", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                Project.create(destination)
        self.assertEqual(list(destination.iterdir()), [])
        self.assertTrue(Project.create(destination).validate())
        self.assertFalse(list(self.directory.glob(".xsearch-*")))

    def test_existing_destination_is_not_overwritten(self):
        before = self.project.project_file.read_bytes()
        with self.assertRaises(FileExistsError):
            Project.create(self.project.project_path)
        other = Project()
        with self.assertRaises(FileExistsError):
            other.save_as(self.project.project_path)
        self.assertEqual(before, self.project.project_file.read_bytes())

    def test_move_and_delete_persist_and_cycles_are_rejected(self):
        parent = self.project.add(Folder("Parent"))
        child = self.project.add(Folder("Child"), parent)
        cloud = self.project.import_file(self.cloud(), child)
        with self.assertRaises(ValueError):
            self.project.move(parent, child)
        with self.assertRaises(ValueError):
            self.project.add(self.project.root, child)
        with self.assertRaises(ValueError):
            self.project.move(cloud, Project().root)
        self.project.move(cloud, self.project.root)
        self.project.remove(parent)
        self.project.save()
        reopened = Project.open(self.project.project_file)
        self.assertIsNone(reopened.find_by_id(parent.uuid))
        self.assertIs(reopened.find_by_id(cloud.uuid).parent, reopened.root)

    def test_duplicate_names_have_independent_identity(self):
        first = self.project.add(Folder("Same"))
        second = self.project.add(Folder("Same"))
        self.project.rename(first, "First")
        self.project.remove(second)
        self.project.save()
        reopened = Project.open(self.project.project_file)
        self.assertEqual(reopened.find_by_id(first.uuid).name, "First")
        self.assertIsNone(reopened.find_by_id(second.uuid))

    def test_surface_geometry_roundtrip(self):
        surface = Surface("Surface")
        surface.vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        surface.faces = np.array([3, 0, 1, 2])
        surface.normals = np.array([[0., 0., 1.]] * 3)
        surface.visible = False
        surface.locked = True
        self.project.add(surface)
        self.project.save()
        reopened = Project.open(self.project.project_file).surfaces()[0]
        np.testing.assert_array_equal(reopened.vertices, surface.vertices)
        np.testing.assert_array_equal(reopened.faces, surface.faces)
        np.testing.assert_array_equal(reopened.normals, surface.normals)
        self.assertEqual(reopened.uuid, surface.uuid)
        self.assertFalse(reopened.visible)
        self.assertTrue(reopened.locked)

    def test_corrupt_version_missing_asset_and_path_traversal(self):
        self.project.import_file(self.cloud())
        self.project.save()
        valid = json.loads(self.project.project_file.read_text(encoding="utf-8"))
        for version, asset in [(999, None), (3, "../outside.npz"), (3, "work/missing.npz")]:
            data = json.loads(json.dumps(valid))
            data["version"] = version
            if asset:
                data["tree"]["children"][0]["data_file"] = asset
            self.project.project_file.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(version=version, asset=asset), self.assertRaises((ValueError, OSError)):
                Project.open(self.project.project_file)

    def test_invalid_surface_does_not_replace_saved_project(self):
        before = self.project.project_file.read_bytes()
        surface = Surface()
        surface.vertices = [[0, 0, 0]]
        surface.faces = [3, 0, 1, 2]
        self.project.add(surface)
        with self.assertRaises(ValueError):
            self.project.save()
        self.assertEqual(self.project.project_file.read_bytes(), before)

    def test_legacy_project_recovers_csv_then_upgrades(self):
        cloud = self.project.import_file(self.cloud())
        data = self.project._serialize()
        data["version"] = 2
        self.project.project_file.write_text(json.dumps(data), encoding="utf-8")
        reopened = Project.open(self.project.project_file)
        self.assertTrue(reopened.modified)
        pd.testing.assert_frame_equal(reopened.pointclouds()[0].dataframe, cloud.dataframe)
        reopened.save()
        (self.directory / "points.csv").unlink()
        self.assertFalse(Project.open(reopened.project_file).modified)

    def test_legacy_missing_source_reports_error(self):
        cloud = self.project.import_file(self.cloud())
        data = self.project._serialize()
        data["version"] = 2
        self.project.project_file.write_text(json.dumps(data), encoding="utf-8")
        Path(cloud.file_path).unlink()
        with self.assertRaisesRegex(ValueError, "исходный файл"):
            Project.open(self.project.project_file)

    def test_invalid_coordinates_rejected_before_import(self):
        for values in ([float("nan"), 2], [float("inf"), 2], ["bad", "2"]):
            cloud = self.cloud()
            cloud.dataframe["x"] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.project.import_file(cloud)
        self.assertEqual(self.project.pointclouds(), [])

    def test_numeric_precision_nulls_and_types_are_preserved(self):
        frame = pd.DataFrame({
            "x": [1.2345678901234567, 1e-50], "y": [2.0, 3.0], "z": [4.0, 5.0],
            "float": [float("inf"), float("nan")], "string": ["", None],
            "int": pd.Series([1, None], dtype="Int64"),
            "bool": pd.Series([True, None], dtype="boolean"),
            "text": pd.Series(["Привет", None], dtype="string"),
        })
        cloud = PointCloud(dataframe=frame)
        cloud.set_mapping("x", "y", "z", list(frame.columns[3:]))
        self.project.add(cloud)
        self.project.save()
        loaded = Project.open(self.project.project_file).pointclouds()[0].dataframe
        pd.testing.assert_frame_equal(loaded, frame, check_exact=True)

    def test_headerless_csv_and_index_named_column(self):
        source = self.directory / "no-header.txt"
        source.write_text("1;2;3\n4;5;6\n", encoding="utf-8")
        frame = CsvImporter().load(source, header=False)
        self.assertEqual(list(frame.columns), ["0", "1", "2"])
        frame["index"] = [7, 8]
        cloud = PointCloud(dataframe=frame)
        cloud.set_mapping("0", "1", "2", ["index"])
        self.project.add(cloud)
        self.project.save()
        pd.testing.assert_frame_equal(Project.open(self.project.project_file).pointclouds()[0].dataframe, frame)

    def test_table_preserves_custom_index_and_integer_column_labels(self):
        frame = pd.DataFrame({0: [0.5, 1.5], 1: [2, 3], 2: [4, 5]}, index=pd.Index(["A", "B"], name="row"))
        path = self.directory / "table.npz"
        path.write_bytes(TableStorage.dumps(frame))
        pd.testing.assert_frame_equal(TableStorage.load(path), frame, check_exact=True)


if __name__ == "__main__":
    unittest.main()
