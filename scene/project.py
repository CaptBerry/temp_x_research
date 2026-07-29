import json
from pathlib import Path

from models.points import Points
from models.surface import Surface
from scene.camera import SceneCamera
from scene.scene import Scene


class SceneProject:

    def __init__(self, name="Project", objects=None, camera=None, path=None):

        self.name = name
        self.objects = objects or []
        self.camera = camera or SceneCamera()
        self.path = path

    @classmethod
    def from_file(cls, file_path):

        path = Path(file_path)

        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        project = cls(
            name=data.get("name", path.stem),
            camera=SceneCamera.from_dict(data.get("camera", {})),
            path=path
        )

        for object_data in data.get("objects", []):
            project.objects.append(
                cls._object_from_dict(object_data, path.parent)
            )

        return project

    @staticmethod
    def _object_from_dict(data, base_path):

        object_type = data.get("type")
        name = data.get("name", "Object")

        if object_type == "surface":
            return Surface(
                data["vertices"],
                data["faces"],
                name
            )

        if object_type == "points":
            source = data.get("source", {})

            if source.get("type") == "csv":
                csv_path = base_path / source["path"]

                return Points.from_csv(
                    csv_path,
                    x_column=source.get("x_column", 0),
                    y_column=source.get("y_column", 1),
                    z_column=source.get("z_column", 2),
                    name=name,
                    delimiter=source.get("delimiter", ","),
                    skip_header=source.get("skip_header", 0)
                )

            return Points(
                data["coordinates"],
                name
            )

        raise ValueError(f"Unsupported project object type: {object_type}")

    def to_scene(self):

        scene = Scene()

        for obj in self.objects:
            scene.add(obj)

        scene.camera = self.camera

        return scene

    def save(self, file_path=None):

        path = Path(file_path) if file_path is not None else self.path

        if path is None:
            raise ValueError("Project file path is not set")

        with path.open("w", encoding="utf-8") as file:
            json.dump(
                self.to_dict(path.parent),
                file,
                indent=2
            )

        self.path = path

    def to_dict(self, base_path=None):

        return {
            "name": self.name,
            "camera": self.camera.to_dict(),
            "objects": [
                self._object_to_dict(obj, base_path)
                for obj in self.objects
            ]
        }

    @staticmethod
    def _object_to_dict(obj, base_path=None):

        if isinstance(obj, Surface):
            return {
                "type": "surface",
                "name": obj.name,
                "vertices": obj.vertices.tolist(),
                "faces": obj.faces.tolist()
            }

        if isinstance(obj, Points):
            return {
                "type": "points",
                "name": obj.name,
                "coordinates": obj.coordinates.tolist()
            }

        raise ValueError(f"Unsupported scene object class: {obj.__class__.__name__}")
