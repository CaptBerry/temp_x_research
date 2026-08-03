import json
from abc import ABC, abstractmethod


class ProjectObject(ABC):
    def __init__(self, name="Object"):
        self.name = name
        self.parent = None
        self.metadata = {}  # Дополнительные данные

    @abstractmethod
    def to_dict(self) -> dict:
        """Преобразовать объект в словарь для JSON"""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict):
        """Воссоздать объект из словаря"""
        pass

    def get_path(self):
        """Получить путь к объекту в дереве проекта"""
        if self.parent:
            parent_path = self.parent.get_path()
            return f"{parent_path}/{self.name}"
        return self.name