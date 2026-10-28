"""Eclipse-style corner-point geometry, independent of Qt and VTK.

Arrays use K,J,I order (I varies fastest), matching GRDECL.  Pillars are
indexed J,I and each contains its top and bottom XYZ point.  ZCORN is the
logical 2*K,2*J,2*I corner array; its duplicated boundary depths are kept so
fault offsets and gaps are not lost.
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class CornerPointGrid:
    dimensions: tuple[int, int, int]
    coord: np.ndarray
    zcorn: np.ndarray
    actnum: np.ndarray
    properties: dict[str, np.ndarray] = field(default_factory=dict)
    explicit_corners: np.ndarray | None = None

    def validate(self):
        if (not isinstance(self.dimensions, tuple) or len(self.dimensions) != 3
                or any(type(value) is not int or value <= 0 for value in self.dimensions)):
            raise ValueError("Размеры corner-point grid должны быть положительными целыми числами.")
        nx, ny, nz = self.dimensions
        if np.shape(self.coord) != (ny + 1, nx + 1, 2, 3):
            raise ValueError("COORD не соответствует размерам сетки.")
        if np.shape(self.zcorn) != (2 * nz, 2 * ny, 2 * nx):
            raise ValueError("ZCORN не соответствует размерам сетки.")
        if np.shape(self.actnum) != (nz, ny, nx):
            raise ValueError("ACTNUM не соответствует размерам сетки.")
        if not np.isfinite(self.coord).all() or not np.isfinite(self.zcorn).all():
            raise ValueError("Геометрия сетки содержит нечисловые или бесконечные координаты.")
        if not np.any(self.actnum):
            raise ValueError("В corner-point grid нет активных ячеек.")
        for name, values in self.properties.items():
            if not isinstance(name, str) or not name or np.shape(values) != (nz, ny, nx):
                raise ValueError(f"Некорректный ячеечный параметр: {name}")
            if not np.issubdtype(np.asarray(values).dtype, np.number):
                raise ValueError(f"Параметр {name} должен быть числовым.")
        if self.explicit_corners is not None:
            if (np.shape(self.explicit_corners) != (self.active_count, 8, 3)
                    or not np.isfinite(self.explicit_corners).all()):
                raise ValueError("Явные углы активных ячеек имеют неверную форму или координаты.")

    @property
    def active_count(self):
        return int(np.count_nonzero(self.actnum))

    @property
    def active_indices(self):
        """Zero-based K,J,I indices of active cells in GRDECL order."""
        return np.argwhere(self.actnum)

    def cell_corners(self):
        """Eight XYZ corners per active cell, in VTK_HEXAHEDRON order."""
        self.validate()
        if self.explicit_corners is not None:
            return self.explicit_corners
        k, j, i = self.active_indices.T
        corners = np.empty((len(k), 8, 3), dtype=np.float64)
        for corner, (di, dj, dk) in enumerate(((0, 0, 0), (1, 0, 0),
                                                 (1, 1, 0), (0, 1, 0),
                                                 (0, 0, 1), (1, 0, 1),
                                                 (1, 1, 1), (0, 1, 1))):
            pillar = self.coord[j + dj, i + di]
            depth = self.zcorn[2 * k + dk, 2 * j + dj, 2 * i + di]
            upper, lower = pillar[:, 0], pillar[:, 1]
            delta_z = lower[:, 2] - upper[:, 2]
            if np.any((delta_z == 0) & ((depth != upper[:, 2]) |
                                         np.any(lower[:, :2] != upper[:, :2], axis=1))):
                raise ValueError("Невозможно определить угол ячейки на горизонтальном пилларе.")
            fraction = np.divide(depth - upper[:, 2], delta_z,
                                 out=np.zeros_like(depth), where=delta_z != 0)
            corners[:, corner, 0] = upper[:, 0] + fraction * (lower[:, 0] - upper[:, 0])
            corners[:, corner, 1] = upper[:, 1] + fraction * (lower[:, 1] - upper[:, 1])
            corners[:, corner, 2] = depth
        return corners

    def cell_centers(self):
        return self.cell_corners().mean(axis=1)
