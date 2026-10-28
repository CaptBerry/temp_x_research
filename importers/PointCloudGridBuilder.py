"""Infer a corner-point grid from XYZ samples representing cell centres.

The generated geometry is rectilinear (a valid corner-point special case).
Rows of centres map one-to-one to cells; scattered samples are binned into a
user-sized regular grid. No fault or pillar displacement is invented.
"""

import numpy as np
import pandas as pd

from models.CornerPointGrid import CornerPointGrid


MAX_GRID_CELLS = 2_000_000
MAX_AXIS_CELLS = 256


def _edges(centres, singleton_size):
    if len(centres) == 1:
        return np.asarray([centres[0] - singleton_size / 2,
                           centres[0] + singleton_size / 2], dtype=float)
    middle = (centres[:-1] + centres[1:]) / 2
    return np.r_[centres[0] - (centres[1] - centres[0]) / 2,
                 middle,
                 centres[-1] + (centres[-1] - centres[-2]) / 2]


def _uniform_dimensions(points, requested):
    dimensions = list(requested)
    spans = np.ptp(points, axis=0)
    remaining = [axis for axis in range(3) if dimensions[axis] == 0 and spans[axis] > 0]
    target = min(MAX_GRID_CELLS, max(1, 2 * len(points)))
    fixed = int(np.prod([value for value in dimensions if value > 0]))
    if remaining:
        scale = (max(1, target / fixed) / np.prod(spans[remaining])) ** (1 / len(remaining))
        for axis in remaining:
            dimensions[axis] = min(MAX_AXIS_CELLS, max(1, round(spans[axis] * scale)))
    for axis in range(3):
        if dimensions[axis] == 0:
            dimensions[axis] = 1
        if spans[axis] == 0 and dimensions[axis] != 1:
            raise ValueError("По оси с одинаковыми координатами центров возможна только одна ячейка.")
    return tuple(dimensions)


def _join_existing_cells(grid, edges):
    """Expand occupied hexahedra across empty bins; never activate a new cell."""
    k, j, i = grid.active_indices.T
    index_map = np.full(grid.actnum.shape, -1, dtype=np.int64)
    index_map[grid.actnum] = np.arange(grid.active_count)
    lower = np.column_stack((edges[0][i], edges[1][j], edges[2][k]))
    upper = np.column_stack((edges[0][i + 1], edges[1][j + 1], edges[2][k + 1]))
    changed = False

    def join_layers(ids):
        nonlocal changed
        occupied = ids[ids >= 0]
        for left, right in zip(occupied[:-1], occupied[1:]):
            if k[right] - k[left] <= 1:
                continue
            boundary = (upper[left, 2] + lower[right, 2]) / 2
            upper[left, 2] = boundary
            lower[right, 2] = boundary
            changed = True

    _, ny, nx = grid.actnum.shape
    footprint = grid.actnum.any(axis=0)

    # Empty slices can be closed globally along both axes without overlap.
    global_x = footprint.any(axis=0)
    global_y = footprint.any(axis=1)
    for axis, occupied, take_ids in (
        (0, np.flatnonzero(global_x), lambda index: index_map[:, :, index]),
        (1, np.flatnonzero(global_y), lambda index: index_map[:, index, :]),
    ):
        for near, far in zip(occupied[:-1], occupied[1:]):
            if far - near <= 1:
                continue
            boundary = (edges[axis][near + 1] + edges[axis][far]) / 2
            near_ids, far_ids = take_ids(near), take_ids(far)
            upper[near_ids[near_ids >= 0], axis] = boundary
            lower[far_ids[far_ids >= 0], axis] = boundary
            changed = True

    x_gaps = sum(np.count_nonzero(np.diff(np.flatnonzero(footprint[row])) > 1)
                 for row in range(ny))
    y_gaps = sum(np.count_nonzero(np.diff(np.flatnonzero(footprint[:, column])) > 1)
                 for column in range(nx))
    # Stretch within rows OR within columns. Doing both may make diagonal cells
    # overlap, even though no new cells were created.
    if x_gaps >= y_gaps:
        for row in range(ny):
            occupied = np.flatnonzero(footprint[row])
            for left, right in zip(occupied[:-1], occupied[1:]):
                if right - left <= 1:
                    continue
                boundary = (upper[index_map[:, row, left][index_map[:, row, left] >= 0], 0].max() +
                            lower[index_map[:, row, right][index_map[:, row, right] >= 0], 0].min()) / 2
                left_ids = index_map[:, row, left]
                right_ids = index_map[:, row, right]
                upper[left_ids[left_ids >= 0], 0] = boundary
                lower[right_ids[right_ids >= 0], 0] = boundary
                changed = True
    else:
        for column in range(nx):
            occupied = np.flatnonzero(footprint[:, column])
            for near, far in zip(occupied[:-1], occupied[1:]):
                if far - near <= 1:
                    continue
                near_ids = index_map[:, near, column]
                far_ids = index_map[:, far, column]
                boundary = (upper[near_ids[near_ids >= 0], 1].max() +
                            lower[far_ids[far_ids >= 0], 1].min()) / 2
                upper[near_ids[near_ids >= 0], 1] = boundary
                lower[far_ids[far_ids >= 0], 1] = boundary
                changed = True
    for row in range(ny):
        for column in range(nx):
            join_layers(index_map[:, row, column])
    if not changed:
        return
    corners = np.empty((grid.active_count, 8, 3), dtype=float)
    for corner, (di, dj, dk) in enumerate(((0, 0, 0), (1, 0, 0),
                                             (1, 1, 0), (0, 1, 0),
                                             (0, 0, 1), (1, 0, 1),
                                             (1, 1, 1), (0, 1, 1))):
        corners[:, corner, 0] = upper[:, 0] if di else lower[:, 0]
        corners[:, corner, 1] = upper[:, 1] if dj else lower[:, 1]
        corners[:, corner, 2] = upper[:, 2] if dk else lower[:, 2]
    grid.explicit_corners = corners


def _grid_from_edges(edges, flat_indices, points, property_values, connect_existing):
    nx, ny, nz = (len(axis) - 1 for axis in edges)
    shape = (nz, ny, nx)
    counts = np.bincount(flat_indices, minlength=nx * ny * nz)
    actnum = counts.reshape(shape) > 0
    x_edges, y_edges, z_edges = edges
    xx, yy = np.meshgrid(x_edges, y_edges, indexing="xy")
    coord = np.empty((ny + 1, nx + 1, 2, 3), dtype=float)
    coord[:, :, 0, 0], coord[:, :, 1, 0] = xx, xx
    coord[:, :, 0, 1], coord[:, :, 1, 1] = yy, yy
    coord[:, :, 0, 2], coord[:, :, 1, 2] = z_edges[0], z_edges[-1]
    zcorn = np.repeat(np.repeat(np.repeat(z_edges, 2)[1:-1].reshape(2 * nz, 1, 1),
                                  2 * ny, axis=1), 2 * nx, axis=2)
    properties = {"N_POINTS": counts.reshape(shape).astype(float)}
    source_values = {f"CENTER_{axis}": points[:, index] for index, axis in enumerate("XYZ")}
    for name, values in {**source_values, **property_values}.items():
        finite = np.isfinite(values)
        sums = np.bincount(flat_indices[finite], weights=values[finite], minlength=counts.size)
        valid = np.bincount(flat_indices[finite], minlength=counts.size)
        means = np.divide(sums, valid, out=np.full(counts.size, np.nan), where=valid > 0)
        properties[name] = means.reshape(shape)
    grid = CornerPointGrid((nx, ny, nz), coord, zcorn, actnum, properties)
    if connect_existing:
        _join_existing_cells(grid, edges)
    grid.validate()
    return grid


def build_grid_from_centres(dataframe, coordinates, parameters=(), *, method="auto",
                            dimensions=(0, 0, 0), singleton_size=1.0,
                            connect_existing=True):
    """Return (grid, used_method) from centre samples in arbitrary row order.

    `method`: auto, rows, or uniform. Zero dimensions request automatic sizing
    for the uniform grid. Empty cells are inactive; multiple samples in one
    cell contribute their mean and are counted in N_POINTS. With
    connect_existing, occupied cells expand to meet along coordinate lines.
    """
    if method not in ("auto", "rows", "uniform"):
        raise ValueError("Неизвестный способ построения сетки из центров.")
    if (len(dimensions) != 3 or any(type(value) is not int or not 0 <= value <= MAX_AXIS_CELLS
                                    for value in dimensions)):
        raise ValueError(f"Число ячеек по каждой оси должно быть от 0 до {MAX_AXIS_CELLS}.")
    if not np.isfinite(singleton_size) or singleton_size <= 0:
        raise ValueError("Размер ячейки для одиночной оси должен быть положительным числом.")
    if len(set(coordinates)) != 3 or any(column not in dataframe for column in coordinates):
        raise ValueError("Выберите три разные колонки для координат центров X, Y и Z.")
    if dataframe.empty:
        raise ValueError("Облако точек не содержит центров ячеек.")
    try:
        points = dataframe[list(coordinates)].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError("Координаты центров ячеек должны быть числовыми.") from error
    if not np.isfinite(points).all():
        raise ValueError("Координаты центров содержат пропуски или бесконечные значения.")
    property_values = {}
    for name in parameters:
        if name in coordinates or name not in dataframe:
            raise ValueError(f"Не найдена колонка параметра: {name}")
        if str(name) in ("x", "y", "z", "I", "J", "K", "N_POINTS",
                         "CENTER_X", "CENTER_Y", "CENTER_Z"):
            raise ValueError(f"Имя {name} зарезервировано для геометрии куба.")
        values = pd.to_numeric(dataframe[name], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).any():
            raise ValueError(f"Параметр {name} не содержит числовых значений.")
        property_values[str(name)] = values

    axes = tuple(np.unique(points[:, axis]) for axis in range(3))
    row_cells = int(np.prod([len(axis) for axis in axes]))
    possible_rows = row_cells <= MAX_GRID_CELLS and row_cells <= 8 * len(points)
    if method == "rows" and not possible_rows:
        raise ValueError("Центры не образуют достаточно плотные ряды и слои; выберите равномерную сетку.")
    used_method = ("rows" if method == "rows" or
                   (method == "auto" and possible_rows and row_cells <= 2 * len(points))
                   else "uniform")
    if used_method == "rows":
        edges = tuple(_edges(axis, singleton_size) for axis in axes)
        ix, iy, iz = (np.searchsorted(axis, points[:, number]) for number, axis in enumerate(axes))
        nx, ny, nz = (len(axis) for axis in axes)
    else:
        nx, ny, nz = _uniform_dimensions(points, dimensions)
        def uniform_edges(axis, size):
            minimum, maximum = points[:, axis].min(), points[:, axis].max()
            if minimum == maximum:
                return _edges(np.asarray([minimum]), singleton_size)
            step = (maximum - minimum) / (size - 1) if size > 1 else maximum - minimum
            return np.linspace(minimum - step / 2, maximum + step / 2, size + 1)

        edges = tuple(uniform_edges(axis, size) for axis, size in enumerate((nx, ny, nz)))
        ix, iy, iz = (np.clip(np.searchsorted(edge, points[:, axis], side="right") - 1,
                              0, len(edge) - 2) for axis, edge in enumerate(edges))
    cell_count = nx * ny * nz
    if cell_count > MAX_GRID_CELLS:
        raise ValueError(f"Сетка содержит {cell_count} ячеек; предел {MAX_GRID_CELLS}.")
    indices = (iz * ny + iy) * nx + ix
    return _grid_from_edges(edges, indices, points, property_values,
                            connect_existing), used_method
