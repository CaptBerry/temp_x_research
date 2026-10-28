"""A cube assembled from independently visible corner-point layer cubes."""

import numpy as np

from models.Appearance import Appearance
from models.DataCube import DataCube
from models.project.Folder import Folder


class LayeredCube(Folder):
    TYPE = "layered_cube"

    def __init__(self, name="Послойный куб", layer_column=None,
                 roof_column=None, base_column=None):
        super().__init__(name)
        self.layer_column = layer_column
        self.roof_column = roof_column
        self.base_column = base_column
        self.appearance = Appearance.default(self.TYPE)

    def _add(self, obj):
        if not isinstance(obj, DataCube) or not obj.is_corner_point:
            raise ValueError("Послойный куб может содержать только слои corner-point grid.")
        index = obj.metadata.get("layer_index")
        if index is None or any(str(child.metadata.get("layer_index")) == str(index)
                                for child in self._children):
            raise ValueError("Индекс слоя должен быть задан и уникален.")
        super()._add(obj)

    @property
    def layers(self):
        return tuple(self.children)

    def get_layer(self, index):
        return next((layer for layer in self.layers
                     if str(layer.metadata.get("layer_index")) == str(index)), None)

    def validate(self):
        self.appearance.validate(self.TYPE)
        if not all((self.layer_column, self.roof_column, self.base_column)):
            raise ValueError("У послойного куба не заданы колонки слоя, кровли и подошвы.")
        indices = set()
        for layer in self.layers:
            if not isinstance(layer, DataCube) or not layer.is_corner_point:
                raise ValueError("У послойного куба неверный тип дочернего объекта.")
            index = layer.metadata.get("layer_index")
            if index is None or str(index) in indices:
                raise ValueError("Индексы слоёв должны быть заданы и уникальны.")
            indices.add(str(index))
            layer.validate()
        if self.appearance.color_map is not None:
            self.color_values(self.appearance.color_map.field)

    def numeric_fields(self):
        if not self.layers:
            return []
        common = set.intersection(*(set(layer.numeric_fields()) for layer in self.layers))
        return [field for field in self.layers[0].numeric_fields() if field in common]

    def color_values(self, field):
        if not self.layers or field not in self.numeric_fields():
            raise ValueError("Числовой параметр палитры должен быть у всех слоёв куба.")
        return np.concatenate([layer.color_values(field) for layer in self.layers])

    def to_dict(self):
        data = super().to_dict()
        data.update(layer_column=self.layer_column, roof_column=self.roof_column,
                    base_column=self.base_column, appearance=self.appearance.to_dict())
        return data

    @classmethod
    def from_dict(cls, data):
        cube = cls(data["name"], data.get("layer_column"),
                   data.get("roof_column"), data.get("base_column"))
        cube._load_base(data)
        cube.appearance = Appearance.from_dict(data.get("appearance", {}), cls.TYPE)
        return cube
