from pathlib import Path

import pandas as pd

from models.project.ProjectObject import ProjectObject


class TableData(ProjectObject):

    def __init__(self, name="Table"):

        super().__init__(name)

        # Основные данные
        self.data = pd.DataFrame()

        # Исходный файл
        self.file_path: Path | None = None

        # Настройки импорта
        self.delimiter = ","
        self.encoding = "utf-8"
        self.header = True

        # Соответствие ролей колонкам
        self.mapping = {}

        # Метаданные
        self.metadata = {}

    @property
    def column_names(self):

        return list(self.data.columns)


    @property
    def row_count(self):

        return len(self.data)


    @property
    def column_count(self):

        return len(self.data.columns)


    @property
    def empty(self):

        return self.data.empty

    # работа с датафрейм
    def set_dataframe(self, dataframe: pd.DataFrame):
        self.data = dataframe

    def column(self, name):
        return self.data[name]

    