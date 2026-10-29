"""Ordered samples along one identified well trajectory."""

import numpy as np
import pandas as pd

from models.Appearance import Appearance
from models.PointCloud import PointCloud


class Well(PointCloud):
    TYPE = "well"

    def __init__(self, name="Скважина", file_path=None, dataframe=None, well_id=None):
        super().__init__(name, file_path, dataframe)
        self.well_id = str(well_id).strip() if well_id is not None else ""
        self.appearance = Appearance.default(self.TYPE)

    def validate(self):
        super().validate()
        if not self.well_id:
            raise ValueError("У скважины должен быть идентификатор.")
        if self.point_count < 2:
            raise ValueError("Траектория скважины должна содержать хотя бы две точки.")
        if not self.parameters:
            raise ValueError("Выберите хотя бы один параметр скважины.")
        numeric = []
        for column in self.parameters:
            try:
                numeric.append(pd.to_numeric(self.dataframe[column], errors="coerce").to_numpy(dtype=float))
            except (TypeError, ValueError):
                continue
        if not numeric or not np.isfinite(np.column_stack(numeric)).any(axis=1).all():
            raise ValueError("Каждая точка скважины должна иметь числовой параметр.")

    @property
    def trajectory_length(self):
        coordinates = self.coordinates
        return float(np.linalg.norm(np.diff(coordinates, axis=0), axis=1).sum()) if len(coordinates) > 1 else 0.0

    def parameter_values(self, name):
        if name not in self.parameters:
            raise ValueError("Параметр не принадлежит скважине.")
        return pd.to_numeric(self.dataframe[name], errors="coerce").to_numpy(dtype=float)

    def to_dict(self):
        data = super().to_dict()
        data["well_id"] = self.well_id
        return data

    @classmethod
    def from_dict(cls, data):
        well = super().from_dict(data)
        well.well_id = str(data.get("well_id", "")).strip()
        return well
