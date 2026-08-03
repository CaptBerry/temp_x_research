import numpy as np

from scene.scene_object import SceneObject


class Surface(SceneObject):

    def __init__(
            self,
            vertices,
            faces,
            name="Surface"
    ):

        super().__init__(name)

        self.vertices = np.asarray(
            vertices,
            dtype=np.float32
        )

        self.faces = np.asarray(
            faces,
            dtype=np.int32
        )

