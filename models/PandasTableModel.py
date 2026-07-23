import pandas as pd

from PyQt6.QtCore import Qt, QAbstractTableModel


class PandasTableModel(QAbstractTableModel):

    def __init__(self, dataframe: pd.DataFrame):
        super().__init__()

        self._df = dataframe

    # -----------------------------
    # Размеры таблицы
    # -----------------------------

    def rowCount(self, parent=None):
        return len(self._df.index)

    def columnCount(self, parent=None):
        return len(self._df.columns)

    # -----------------------------
    # Данные ячеек
    # -----------------------------

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):

        if not index.isValid():
            return None

        if role == Qt.ItemDataRole.DisplayRole:

            value = self._df.iat[
                index.row(),
                index.column()
            ]

            return str(value)

        return None

    # -----------------------------
    # Заголовки
    # -----------------------------

    def headerData(
            self,
            section,
            orientation,
            role=Qt.ItemDataRole.DisplayRole
    ):

        if role != Qt.ItemDataRole.DisplayRole:
            return None

        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])

        return str(section + 1)