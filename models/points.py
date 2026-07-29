from pathlib import Path

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

    @classmethod
    def from_csv(
            cls,
            file_path,
            x_column,
            y_column,
            z_column,
            name="Points",
            delimiter=",",
            skip_header=0
    ):

        path = Path(file_path)

        coordinates = np.genfromtxt(
            path,
            delimiter=delimiter,
            usecols=(x_column, y_column, z_column),
            skip_header=skip_header,
            dtype=np.float32
        )

        if coordinates.ndim == 1:
            coordinates = coordinates.reshape(1, 3)

        if np.isnan(coordinates).any():
            raise ValueError("CSV file contains empty or non-numeric coordinates")

        return cls(coordinates, name)
