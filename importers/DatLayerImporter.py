"""Read interval records from a large tab-delimited layered DAT file."""

import pandas as pd


def load_layer_intervals(filename, coordinates, layer_column, roof_column,
                         base_column, parameters=(), chunksize=100_000, *,
                         cancelled=None, progress=None):
    """Keep one interval per XY position and named layer, without loading sampled H rows."""
    columns = list(dict.fromkeys([*coordinates[:2], layer_column, roof_column,
                                  base_column, *parameters]))
    if any(not column for column in columns):
        raise ValueError("Выберите координаты, название слоя, кровлю и подошву.")
    intervals = []
    rows_read = 0
    for chunk in pd.read_csv(filename, sep="\t", usecols=columns,
                             chunksize=chunksize, low_memory=False):
        if cancelled is not None and cancelled():
            raise InterruptedError("Импорт отменён.")
        rows_read += len(chunk)
        if progress is not None:
            progress(rows_read)
        names = chunk[layer_column].astype("string").str.strip()
        chunk = chunk.loc[names.notna() & names.ne("")].copy()
        if chunk.empty:
            continue
        chunk[layer_column] = names.loc[chunk.index].astype(str)
        intervals.append(chunk.drop_duplicates(subset=[*coordinates[:2], layer_column]))
    if cancelled is not None and cancelled():
        raise InterruptedError("Импорт отменён.")
    if not intervals:
        raise ValueError("Файл не содержит интервалов с названиями слоёв.")
    return pd.concat(intervals, ignore_index=True).drop_duplicates(
        subset=[*coordinates[:2], layer_column], ignore_index=True)
