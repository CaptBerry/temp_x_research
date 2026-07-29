from PyQt6.QtCore import (
    Qt,
    QSortFilterProxyModel
)


class DataFrameProxyModel(QSortFilterProxyModel):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setDynamicSortFilter(True)

    def lessThan(self, left, right):

        leftData = self.sourceModel().data(left)

        rightData = self.sourceModel().data(right)

        try:
            return float(leftData) < float(rightData)

        except (TypeError, ValueError):
            return str(leftData) < str(rightData)

