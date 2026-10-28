"""A file-level collection of wells, preserving each well as a typed child."""

import numpy as np

from models.Appearance import Appearance
from models.project.Folder import Folder
from models.Well import Well


class WellFile(Folder):
    TYPE = "wellfile"

    def __init__(self, name="Файл скважин", id_column=None):
        super().__init__(name)
        self.id_column = id_column
        self.appearance = Appearance.default(self.TYPE)

    def _add(self, obj):
        if not isinstance(obj, Well):
            raise ValueError("Файл скважин может содержать только скважины.")
        if any(well.well_id == obj.well_id for well in self._children):
            raise ValueError("Идентификаторы скважин в файле должны быть уникальными.")
        super()._add(obj)

    @property
    def wells(self):
        return tuple(self.children)

    @property
    def well_ids(self):
        return tuple(well.well_id for well in self.wells)

    def get_well(self, well_id):
        return next((well for well in self.wells if well.well_id == str(well_id)), None)

    def validate(self):
        self.appearance.validate(self.TYPE)
        if not self.id_column:
            raise ValueError("У файла скважин не указана колонка идентификатора.")
        if not self.wells:
            raise ValueError("Файл скважин не содержит скважин.")
        if len(set(self.well_ids)) != len(self.wells):
            raise ValueError("Идентификаторы скважин должны быть уникальными.")
        for well in self.wells:
            well.validate()
        if self.appearance.color_map is not None:
            self.color_values(self.appearance.color_map.field)

    @property
    def parameters(self):
        return tuple(sorted({name for well in self.wells for name in well.parameters}))

    def numeric_fields(self):
        if not self.wells:
            return []
        common = set.intersection(*(set(well.numeric_fields()) for well in self.wells))
        return [field for field in self.wells[0].numeric_fields() if field in common]

    def color_values(self, field):
        if not self.wells or field not in self.numeric_fields():
            raise ValueError("Числовой параметр палитры должен быть у всех скважин файла.")
        return np.concatenate([well.color_values(field) for well in self.wells])

    def to_dict(self):
        data = super().to_dict()
        data["id_column"] = self.id_column
        data["appearance"] = self.appearance.to_dict()
        return data

    @classmethod
    def from_dict(cls, data):
        well_file = cls(data["name"], data.get("id_column"))
        well_file._load_base(data)
        well_file.appearance = Appearance.from_dict(data.get("appearance", {}), cls.TYPE)
        return well_file
