"""A typed 3D node set with regular-grid and section operations."""

import numpy as np
import pandas as pd

from models.Appearance import Appearance
from models.CornerPointGrid import CornerPointGrid
from models.PointCloud import PointCloud


class DataCube(PointCloud):
    TYPE = "cube"

    def __init__(self, name="DataCube", file_path=None, dataframe=None):
        super().__init__(name, file_path, dataframe)
        self.corner_grid: CornerPointGrid | None = None
        self.grid_kind = "nodes"

    @property
    def is_corner_point(self):
        return self.grid_kind == "corner_point"

    def set_corner_grid(self, grid):
        if not isinstance(grid, CornerPointGrid):
            raise TypeError("Ожидалась геометрия corner-point grid.")
        grid.validate()
        use_default_appearance = self.grid_kind == "nodes"
        self.corner_grid = grid
        self.grid_kind = "corner_point"
        indices = grid.active_indices
        centers = grid.cell_centers()
        data = {"x": centers[:, 0], "y": centers[:, 1], "z": centers[:, 2],
                "I": indices[:, 2] + 1, "J": indices[:, 1] + 1, "K": indices[:, 0] + 1}
        for name, values in grid.properties.items():
            if name in data:
                raise ValueError(f"Параметр {name} конфликтует с координатами или индексами сетки.")
            data[name] = values[grid.actnum]
        self.dataframe = pd.DataFrame(data)
        self.set_mapping("x", "y", "z", parameters=["I", "J", "K", *grid.properties])
        if use_default_appearance:
            self.appearance = Appearance(mode="surface", outline=True)

    def validate(self):
        super().validate()
        if self.is_corner_point:
            if self.corner_grid is None:
                raise ValueError("Для куба отсутствует геометрия corner-point grid.")
            self.corner_grid.validate()
            if self.point_count != self.corner_grid.active_count:
                raise ValueError("Число центров не совпадает с числом активных ячеек.")
            if not np.allclose(self.coordinates, self.corner_grid.cell_centers()):
                raise ValueError("Центры ячеек не соответствуют геометрии сетки.")
            return
        if not self.parameters:
            raise ValueError("Для куба выберите хотя бы один параметр.")
        if self.appearance.mode in ("surface", "wireframe"):
            raise ValueError("Для куба из узлов доступны только точки и сферы.")
        if not any(name in self.numeric_fields() for name in self.parameters):
            raise ValueError("Куб должен содержать числовой параметр узлов.")
        if self.dataframe[[self.x_column, self.y_column, self.z_column]].duplicated().any():
            raise ValueError("Куб содержит повторяющиеся узлы XYZ.")

    @property
    def grid_shape(self):
        if self.is_corner_point and self.corner_grid is not None:
            return self.corner_grid.dimensions
        coordinates = self.coordinates
        if coordinates is None or len(coordinates) == 0:
            return (0, 0, 0)
        return tuple(len(np.unique(coordinates[:, axis])) for axis in range(3))

    @property
    def is_regular_grid(self):
        if self.is_corner_point:
            return False
        shape = self.grid_shape
        if not all(shape) or np.prod(shape) != self.point_count:
            return False
        coordinates = self.coordinates
        return all(np.allclose(np.diff(values), np.diff(values)[0]) if len(values) > 2 else True
                   for values in (np.unique(coordinates[:, axis]) for axis in range(3)))

    def section(self, axis, value, tolerance=0):
        """Return nodes within tolerance of an X, Y or Z slice plane."""
        if axis.lower() not in "xyz" or len(axis) != 1:
            raise ValueError("Ось разреза должна быть X, Y или Z.")
        if tolerance < 0 or not np.isfinite(tolerance):
            raise ValueError("Допуск разреза должен быть неотрицательным числом.")
        column = (self.x_column, self.y_column, self.z_column)["xyz".index(axis.lower())]
        values = self.dataframe[column].to_numpy(dtype=float)
        return self.dataframe.loc[np.abs(values - value) <= tolerance].copy()

    def dense_values(self, parameter):
        """Return a regular X×Y×Z array and coordinate axes."""
        if not self.is_regular_grid:
            raise ValueError("Узлы куба не образуют полную регулярную сетку.")
        if parameter not in self.parameters:
            raise ValueError("Параметр не принадлежит кубу.")
        axes = tuple(np.unique(self.coordinates[:, i]) for i in range(3))
        dense = np.full(self.grid_shape, np.nan)
        values = self.color_values(parameter)
        for xyz, value in zip(self.coordinates, values):
            indices = tuple(int(np.searchsorted(axis, coordinate)) for axis, coordinate in zip(axes, xyz))
            dense[indices] = value
        return axes, dense

    def to_dict(self):
        data = super().to_dict()
        data["grid_kind"] = self.grid_kind
        if self.is_corner_point:
            if self.corner_grid is None:
                raise ValueError("Для куба отсутствует геометрия corner-point grid.")
            data["grid_dimensions"] = list(self.corner_grid.dimensions)
            data["grid_property_names"] = list(self.corner_grid.properties)
        return data

    @classmethod
    def from_dict(cls, data):
        cube = super().from_dict(data)
        cube.grid_kind = data.get("grid_kind", "nodes")
        if cube.grid_kind not in ("nodes", "corner_point"):
            raise ValueError("Неизвестная геометрия куба.")
        return cube
