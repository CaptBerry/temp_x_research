from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np

from models.project.ProjectObject import ProjectObject
from models.Appearance import Appearance


class PointCloud(ProjectObject):
    TYPE = "pointcloud"

    def __init__(self, name="PointCloud", file_path=None, dataframe=None):
        super().__init__(name)
        self.file_path = str(file_path) if file_path is not None else None
        self.file_type = Path(file_path).suffix.lstrip(".").lower() if file_path else None
        self.dataframe = dataframe if dataframe is not None else pd.DataFrame()
        self.x_column = None
        self.y_column = None
        self.z_column = None
        self.parameters = []
        self.appearance = Appearance.default(self.TYPE)

    @property
    def point_count(self):
        return len(self.dataframe)

    @property
    def coordinates(self):
        if any(column is None for column in (self.x_column, self.y_column, self.z_column)):
            return None

        return self.dataframe[[self.x_column, self.y_column, self.z_column]].to_numpy(float)

    def set_mapping(self, x_column, y_column, z_column, parameters=None):
        self.x_column = x_column
        self.y_column = y_column
        self.z_column = z_column
        self.parameters = list(parameters or [])

    def validate(self):
        self.appearance.validate(self.TYPE)
        if self.appearance.color_map is not None:
            self.color_values(self.appearance.color_map.field)
        columns = (self.x_column, self.y_column, self.z_column)
        if any(column is None for column in columns) or len(set(columns)) != 3:
            raise ValueError("Выберите три разные колонки для X, Y и Z.")
        if not self.dataframe.columns.is_unique:
            raise ValueError("Названия колонок должны быть уникальными.")
        missing = [column for column in (*columns, *self.parameters)
                   if column not in self.dataframe.columns]
        if missing:
            raise ValueError(f"В таблице отсутствуют колонки: {missing}")
        try:
            coordinates = self.coordinates
        except (ValueError, TypeError) as error:
            raise ValueError("Координаты должны быть числами.") from error
        if not np.isfinite(coordinates).all():
            raise ValueError("Координаты содержат пропуски или бесконечные значения.")

    def numeric_fields(self):
        fields = []
        for column in self.dataframe.columns:
            try:
                values = pd.to_numeric(self.dataframe[column], errors="coerce").to_numpy(dtype=float)
                if np.isfinite(values).any():
                    fields.append(str(column))
            except (TypeError, ValueError):
                continue
        return fields

    def color_values(self, field):
        column = next((name for name in self.dataframe.columns if str(name) == field), None)
        if column is None:
            raise ValueError("Числовой параметр палитры отсутствует в таблице.")
        values = pd.to_numeric(self.dataframe[column], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).any():
            raise ValueError("Параметр палитры не содержит числовых значений.")
        return values


    def to_dict(self) -> dict:
        data = self._base_dict()
        data.update({
            "file_path": self.file_path,
            "file_type": self.file_type,
            "point_count": self.point_count,
            "x_column": self.x_column,
            "y_column": self.y_column,
            "z_column": self.z_column,
            "parameters": self.parameters,
            "appearance": self.appearance.to_dict(),
        })
        return data

    @classmethod
    def from_dict(cls, data: dict):
        pointcloud = cls(data["name"], data.get("file_path"))
        pointcloud._load_base(data)
        pointcloud.file_type = data.get("file_type")
        pointcloud.appearance = Appearance.from_dict(data.get("appearance", {}), cls.TYPE)
        pointcloud.set_mapping(
            data.get("x_column"),
            data.get("y_column"),
            data.get("z_column"),
            data.get("parameters", []),
        )
        return pointcloud
