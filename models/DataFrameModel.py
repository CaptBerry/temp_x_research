import pandas as pd

from PyQt6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex
)


class DataFrameModel(QAbstractTableModel):

    def __init__(self, parent=None):
        super().__init__(parent)

        self._df = pd.DataFrame()


    def set_dataframe(self, dataframe: pd.DataFrame):

        self.beginResetModel()

        self._df = dataframe

        self.endResetModel()

    @property
    def dataframe(self):
        return self._df

    @property
    def shape(self):

        return self._df.shape

    # количество строк

    def rowCount(
            self,
            parent: QModelIndex = QModelIndex()
    ) -> int:

        return len(self._df.index)


    # количество колонок

    def columnCount(
            self,
            parent: QModelIndex = QModelIndex()
    ) -> int:

        return len(self._df.columns)


    # содержимое ячейки

    def data(
            self,
            index,
            role=Qt.ItemDataRole.DisplayRole
    ):

        if not index.isValid():
            return None


        if role == Qt.ItemDataRole.DisplayRole:

            value = self._df.iat[
                index.row(),
                index.column()
            ]


            if pd.isna(value):
                return ""


            return str(value)


        return None


    # заголовки

    def headerData(
            self,
            section,
            orientation,
            role=Qt.ItemDataRole.DisplayRole
    ):

        if role != Qt.ItemDataRole.DisplayRole:
            return None


        if orientation == Qt.Orientation.Horizontal:

            return str(
                self._df.columns[section]
            )


        else:

            return str(section + 1)

    def clear(self):

        self.beginResetModel()

        self._df = self._df.iloc[0:0]

        self.endResetModel()


    def column_names(self):

        return list(self._df.columns)

