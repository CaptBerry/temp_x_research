"""Lossless storage for imported tables, without loading Python pickle objects.

Numeric columns keep their NumPy representation (including NaN and infinity).
Text and object columns use JSON; nullable columns keep a separate null mask.
"""

import io
import json

import numpy as np
import pandas as pd


class TableStorage:
    @staticmethod
    def dumps(frame):
        if isinstance(frame.index, pd.MultiIndex) or isinstance(frame.columns, pd.MultiIndex):
            raise ValueError("Сохранение таблиц с MultiIndex не поддерживается.")
        arrays = {}

        def encode(series, key):
            dtype = series.dtype
            spec = {"dtype": str(dtype)}
            arrays[key + "_null"] = series.isna().to_numpy(dtype=bool)
            if isinstance(dtype, np.dtype) and dtype.kind in "biufcMm":
                spec["encoding"] = "numpy"
                arrays[key] = series.to_numpy(copy=True)
            elif hasattr(dtype, "numpy_dtype") and dtype.kind in "biuf":
                spec["encoding"] = "numpy"
                arrays[key] = series.to_numpy(dtype=dtype.numpy_dtype, na_value=0)
            elif isinstance(dtype, pd.StringDtype) or dtype == object:
                spec["encoding"] = "json"
                values = series.astype(object).where(series.notna(), None).tolist()
                content = json.dumps(values, ensure_ascii=False, allow_nan=False).encode("utf-8")
                arrays[key] = np.frombuffer(content, dtype=np.uint8)
            else:
                raise ValueError(f"Неподдерживаемый тип колонки: {dtype}")
            return spec

        schema = {
            "columns": frame.columns.tolist(),
            "columns_name": frame.columns.name,
            "columns_dtype": str(frame.columns.dtype),
            "series": [encode(frame.iloc[:, i], f"c{i}") for i in range(len(frame.columns))],
            "index": encode(pd.Series(frame.index), "index"),
            "index_name": frame.index.name,
        }
        if isinstance(frame.index, pd.RangeIndex):
            schema["range_index"] = [frame.index.start, frame.index.stop, frame.index.step]
        arrays["schema"] = np.frombuffer(json.dumps(schema, ensure_ascii=False).encode("utf-8"), dtype=np.uint8)
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **arrays)
        return buffer.getvalue()

    @staticmethod
    def load(path):
        with np.load(path, allow_pickle=False) as arrays:
            schema = json.loads(arrays["schema"].tobytes().decode("utf-8"))

            def decode(spec, key):
                if spec["encoding"] == "numpy":
                    values = arrays[key]
                elif spec["encoding"] == "json":
                    values = json.loads(arrays[key].tobytes().decode("utf-8"))
                else:
                    raise ValueError("Неизвестный формат колонки таблицы.")
                series = pd.Series(values, dtype=spec["dtype"])
                nulls = arrays[key + "_null"]
                if nulls.any():
                    series = series.mask(nulls)
                return series

            columns = [decode(spec, f"c{i}") for i, spec in enumerate(schema["series"])]
            index_values = decode(schema["index"], "index")
            frame = pd.concat(columns, axis=1) if columns else pd.DataFrame(index=range(len(index_values)))
            frame.columns = pd.Index(schema["columns"], dtype=schema["columns_dtype"], name=schema["columns_name"])
            if "range_index" in schema:
                frame.index = pd.RangeIndex(*schema["range_index"], name=schema["index_name"])
            else:
                frame.index = pd.Index(index_values, name=schema["index_name"])
            return frame
