import numpy as np

from scene.scene_object import SceneObject


class Points(SceneObject):

    def __init__(
            self,
            coordinates,
            name="Points"
    ):

        super().__init__(name)

        self.coordinates = np.asarray(
            coordinates,
            dtype=np.float32
        )

        if self.coordinates.ndim != 2 or self.coordinates.shape[1] != 3:
            raise ValueError("Points coordinates must be an Nx3 array")
