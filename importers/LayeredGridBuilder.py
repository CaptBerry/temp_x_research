"""Build a collection of corner-point layers from XY, layer, roof and base columns."""

from pathlib import Path

import numpy as np
import pandas as pd

from importers.PointCloudGridBuilder import (_edges, _uniform_dimensions,
                                             MAX_GRID_CELLS)
from models.CornerPointGrid import CornerPointGrid
from models.DataCube import DataCube
from models.LayeredCube import LayeredCube


def _axis_edges(values, count, singleton_size):
    minimum, maximum = values.min(), values.max()
    if minimum == maximum:
        return _edges(np.asarray([minimum]), singleton_size)
    step = (maximum - minimum) / (count - 1) if count > 1 else maximum - minimum
    return np.linspace(minimum - step / 2, maximum + step / 2, count + 1)


def _node_values(cell_values, active, fallback):
    ny, nx = active.shape
    total = np.zeros((ny + 1, nx + 1), dtype=float)
    counts = np.zeros_like(total)
    j, i = np.nonzero(active)
    for dj, di in ((0, 0), (0, 1), (1, 0), (1, 1)):
        np.add.at(total, (j + dj, i + di), cell_values[j, i])
        np.add.at(counts, (j + dj, i + di), 1)
    return np.divide(total, counts, out=np.full_like(total, fallback), where=counts > 0)


def _layer_grid(x_edges, y_edges, ix, iy, roof, base, parameters):
    nx, ny = len(x_edges) - 1, len(y_edges) - 1
    flat = iy * nx + ix
    counts = np.bincount(flat, minlength=nx * ny)
    active = counts.reshape(ny, nx) > 0
    properties = {"N_POINTS": counts.reshape(1, ny, nx).astype(float)}
    values = dict(parameters)
    for name, raw in values.items():
        finite = np.isfinite(raw)
        sums = np.bincount(flat[finite], weights=raw[finite], minlength=nx * ny)
        nvalid = np.bincount(flat[finite], minlength=nx * ny)
        mean = np.divide(sums, nvalid, out=np.full(nx * ny, np.nan), where=nvalid > 0)
        properties[name] = mean.reshape(1, ny, nx)

    def cell_mean(raw):
        return (np.bincount(flat, weights=raw, minlength=nx * ny) / np.maximum(counts, 1)).reshape(ny, nx)

    low_cells = np.minimum(cell_mean(roof), cell_mean(base))
    high_cells = np.maximum(cell_mean(roof), cell_mean(base))
    low_nodes = _node_values(low_cells, active, float(np.mean(low_cells[active])))
    high_nodes = _node_values(high_cells, active, float(np.mean(high_cells[active])))
    xx, yy = np.meshgrid(x_edges, y_edges, indexing="xy")
    coord = np.empty((ny + 1, nx + 1, 2, 3), dtype=float)
    coord[:, :, 0, 0] = coord[:, :, 1, 0] = xx
    coord[:, :, 0, 1] = coord[:, :, 1, 1] = yy
    coord[:, :, 0, 2], coord[:, :, 1, 2] = low_nodes, high_nodes
    zcorn = np.empty((2, 2 * ny, 2 * nx), dtype=float)
    for dj in (0, 1):
        for di in (0, 1):
            zcorn[0, dj::2, di::2] = low_nodes[dj:dj + ny, di:di + nx]
            zcorn[1, dj::2, di::2] = high_nodes[dj:dj + ny, di:di + nx]
    grid = CornerPointGrid((nx, ny, 1), coord, zcorn, active[np.newaxis], properties)
    grid.validate()
    return grid


def build_layered_cube(dataframe, source, coordinates, parameters, layer_column,
                       roof_column, base_column, *, dimensions=(0, 0, 0),
                       singleton_size=1.0):
    """Import every distinct layer as one visible child cube with shared XY indexing."""
    if dataframe.empty:
        raise ValueError("Послойная модель не содержит строк.")
    x_name, y_name = coordinates[:2]
    chosen = (x_name, y_name, layer_column, roof_column, base_column)
    if any(name not in dataframe for name in chosen) or len(set(chosen)) != len(chosen):
        raise ValueError("Выберите разные колонки X, Y, слоя, кровли и подошвы.")
    if len(dimensions) != 3 or any(type(n) is not int or n < 0 or n > 256 for n in dimensions):
        raise ValueError("Размеры сетки должны быть от 0 до 256.")
    if dimensions[2] not in (0, 1):
        raise ValueError("В послойной модели число ячеек по Z определяется колонкой слоя.")
    if not np.isfinite(singleton_size) or singleton_size <= 0:
        raise ValueError("Размер ячейки должен быть положительным числом.")
    identifiers = dataframe[layer_column].map(
        lambda value: value.strip() if isinstance(value, str) else value)
    if identifiers.isna().any() or identifiers.astype(str).str.strip().eq("").any():
        raise ValueError("Индекс слоя не должен быть пустым.")
    try:
        xy = dataframe[[x_name, y_name]].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
        roof = pd.to_numeric(dataframe[roof_column], errors="raise").to_numpy(dtype=float)
        base = pd.to_numeric(dataframe[base_column], errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError("X, Y, кровля и подошва должны быть числовыми.") from error
    if not np.isfinite(xy).all() or not np.isfinite(roof).all() or not np.isfinite(base).all():
        raise ValueError("Координаты, кровля и подошва должны быть конечными числами.")
    if np.any(roof == base):
        raise ValueError("Кровля и подошва слоя не должны совпадать.")
    if np.any(np.sign(roof - base) != np.sign(roof[0] - base[0])):
        raise ValueError("Порядок кровли и подошвы должен быть одинаковым во всех строках.")

    fields = list(dict.fromkeys([*parameters, roof_column, base_column]))
    fields = [name for name in fields if name not in (x_name, y_name, layer_column)]
    numeric = {}
    for name in fields:
        if name not in dataframe or str(name) in ("I", "J", "K", "N_POINTS", "x", "y", "z"):
            raise ValueError(f"Некорректная колонка параметра: {name}")
        values = pd.to_numeric(dataframe[name], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).any():
            raise ValueError(f"Параметр {name} не содержит числовых значений.")
        numeric[name] = values

    unique_x, unique_y = (np.unique(xy[:, axis]) for axis in range(2))
    unique_xy = len(np.unique(xy, axis=0))
    rows = (not any(dimensions[:2]) and len(unique_x) * len(unique_y) <= MAX_GRID_CELLS
            and len(unique_x) * len(unique_y) <= 2 * unique_xy)
    if rows:
        x_edges, y_edges = _edges(unique_x, singleton_size), _edges(unique_y, singleton_size)
        ix, iy = np.searchsorted(unique_x, xy[:, 0]), np.searchsorted(unique_y, xy[:, 1])
        method = "rows"
    else:
        unique_positions = np.unique(xy, axis=0)
        points = np.column_stack((unique_positions, np.zeros(len(unique_positions))))
        nx, ny, _ = _uniform_dimensions(points, (dimensions[0], dimensions[1], 1))
        x_edges = _axis_edges(xy[:, 0], nx, singleton_size)
        y_edges = _axis_edges(xy[:, 1], ny, singleton_size)
        ix, iy = (np.clip(np.searchsorted(edges, xy[:, axis], side="right") - 1,
                          0, len(edges) - 2) for axis, edges in enumerate((x_edges, y_edges)))
        method = "uniform"
    layer_count = identifiers.nunique()
    if (len(x_edges) - 1) * (len(y_edges) - 1) * layer_count > MAX_GRID_CELLS:
        raise ValueError("Послойная сетка превышает предел числа ячеек.")

    source = Path(source)
    collection = LayeredCube(source.stem, layer_column, roof_column, base_column)
    collection.metadata.update({"source_name": source.name, "grid_build_method": method})
    identifier_values = identifiers.to_numpy()
    for raw_index in pd.unique(identifiers):
        index = raw_index.item() if isinstance(raw_index, np.generic) else raw_index
        if isinstance(index, float) and index.is_integer():
            index = int(index)
        if not isinstance(index, (str, int, float, bool)):
            index = str(index)
        positions = np.flatnonzero(identifier_values == raw_index)
        grid = _layer_grid(x_edges, y_edges, ix[positions], iy[positions],
                           roof[positions], base[positions],
                           {name: values[positions] for name, values in numeric.items()})
        layer = DataCube(f"Слой {index}")
        layer.set_corner_grid(grid)
        layer.metadata.update({"layer_index": index, "source_point_count": len(positions),
                               "grid_build_method": method})
        collection._add(layer)
    collection.validate()
    return collection
