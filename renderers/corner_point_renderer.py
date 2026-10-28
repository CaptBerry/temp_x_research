"""Build VTK hexahedra; share coincident corners but preserve fault offsets."""

import numpy as np
import pyvista as pv


def render_corner_point_grid(grid):
    corners = grid.cell_corners()
    count = len(corners)
    # VTK can omit internal faces only when adjacent cells share point IDs.
    # Exact coincidence is safe to merge; displaced fault corners stay apart.
    points, point_ids = np.unique(corners.reshape(-1, 3), axis=0, return_inverse=True)
    connectivity = np.empty((count, 9), dtype=np.int64)
    connectivity[:, 0] = 8
    connectivity[:, 1:] = point_ids.reshape(count, 8)
    cell_types = np.full(count, pv.CellType.HEXAHEDRON, dtype=np.uint8)
    mesh = pv.UnstructuredGrid(connectivity.ravel(), cell_types, points)
    k, j, i = grid.active_indices.T
    mesh.cell_data["I"] = i + 1
    mesh.cell_data["J"] = j + 1
    mesh.cell_data["K"] = k + 1
    for name, values in grid.properties.items():
        mesh.cell_data[name] = np.asarray(values[grid.actnum], dtype=np.float64)
    return mesh
