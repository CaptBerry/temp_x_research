import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from models.Appearance import Appearance
from models.PointCloud import PointCloud
from models.Surface import Surface
from models.project.Folder import Folder
from models.project.Project import Project


class AppearanceTests(unittest.TestCase):
    def cloud(self):
        cloud = PointCloud(dataframe=pd.DataFrame({"x": [1.], "y": [2.], "z": [3.]}))
        cloud.set_mapping("x", "y", "z")
        return cloud

    def test_style_roundtrip_save_as_and_unchanged_data_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            project = Project.create(directory / "project")
            cloud = project.add(self.cloud())
            surface = project.add(Surface())
            project.save()
            assets = list(project.work_path.iterdir())
            project.set_appearance(cloud, mode="points", point_shape="square", color="#aabbcc",
                                   point_size=14, outline=True, outline_color="#112233", line_width=2.5,
                                   opacity=0.35)
            project.set_appearance(surface, mode="wireframe", color="#ff0000", line_width=4,
                                   opacity=0.7)
            project.save()
            self.assertEqual(list(project.work_path.iterdir()), assets)
            project.save_as(directory / "copy")
            restored = Project.open(directory / "copy")
            self.assertEqual(restored.find_by_id(cloud.uuid).appearance, cloud.appearance)
            self.assertEqual(restored.find_by_id(surface.uuid).appearance, surface.appearance)
            self.assertFalse(restored.modified)

    def test_projects_without_appearance_use_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Project.create(Path(temporary) / "project")
            project.add(self.cloud())
            project.add(Surface())
            project.save()
            data = json.loads(project.project_file.read_text(encoding="utf-8"))
            for node in data["tree"]["children"]:
                del node["appearance"]
            project.project_file.write_text(json.dumps(data), encoding="utf-8")
            reopened = Project.open(project.project_file)
            self.assertEqual(reopened.pointclouds()[0].appearance, Appearance())
            self.assertEqual(reopened.surfaces()[0].appearance.mode, "surface")

    def test_invalid_changes_are_atomic(self):
        project = Project()
        cloud = project.add(self.cloud())
        project.modified = False
        for change in ({"color": "red"}, {"color": None}, {"mode": "surface"},
                       {"point_size": float("nan")}, {"line_width": float("inf")},
                       {"point_size": 0}, {"line_width": -1}, {"point_size": True},
                       {"outline": "yes"}, {"point_shape": "unknown"}, {"typo": 1},
                       {"opacity": -0.1}, {"opacity": 1.1}, {"opacity": float("nan")},
                       {"label_visible": "yes"}, {"label_color": "orange"},
                       {"label_font": "unknown"}, {"label_size": 7},
                       {"scale_x": 2}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                project.set_appearance(cloud, **change)
            self.assertEqual(cloud.appearance, Appearance())
            self.assertFalse(project.modified)

    def test_membership_and_noop(self):
        project = Project()
        cloud = project.add(self.cloud())
        project.modified = False
        self.assertFalse(project.set_appearance(cloud, color=cloud.appearance.color))
        self.assertFalse(project.modified)
        with self.assertRaises(ValueError):
            project.set_appearance(self.cloud(), color="#ffffff")
        with self.assertRaises(ValueError):
            project.set_appearance(project.root, color="#ffffff")

    def test_hidden_object_style_can_change_without_visibility_change(self):
        project = Project()
        folder = project.add(Folder())
        cloud = project.add(self.cloud(), folder)
        project.set_visible(folder, False)
        project.set_appearance(cloud, color="#ff0000")
        self.assertFalse(project.is_visible(cloud))
        self.assertTrue(cloud.visible)


if __name__ == "__main__":
    unittest.main()
