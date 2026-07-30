from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFileDialog, QPushButton, QLineEdit, QTableView, QComboBox, QListWidget

from importers.CsvImporter import CsvImporter

from models.PandasTableModel import PandasTableModel
from PyQt6.QtWidgets import QHeaderView, QListWidgetItem

from models.DataFrameProxyModel import DataFrameProxyModel
from models.DataFrameModel import DataFrameModel


class ImportDialog(QDialog):

    buttonImport: QPushButton
    buttonBrowse: QPushButton
    buttonCancel: QPushButton
    lineEditPathFile: QLineEdit
    tableViewPreview: QTableView
    comboBoxMapX: QComboBox
    comboBoxMapY: QComboBox
    comboBoxMapZ: QComboBox
    listWidgetParametrs: QListWidget

    def __init__(self, parent=None):
        super().__init__(parent)

        self.importer = CsvImporter()

        ui = Path(__file__).with_name("ImportDialog.ui")
        uic.loadUi(ui, self)

        self.tableModel = DataFrameModel(self)

        self.tableProxy = DataFrameProxyModel(self)

        self.tableProxy.setSourceModel(
            self.tableModel
        )

        self.tableViewPreview.setModel(
            self.tableProxy
        )

        self.init_ui()
        self.connect_signals()

    def init_ui(self):

        self.setWindowTitle("Import Data")

        self.buttonImport.setEnabled(False)

        self.tableViewPreview.setSortingEnabled(True)

    def connect_signals(self):

        self.buttonBrowse.clicked.connect(self.select_file)

        self.buttonCancel.clicked.connect(self.reject)

        self.buttonImport.clicked.connect(self.accept)

    def select_file(self):

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open data",
            "",
            "Data (*.csv *.txt *.dat);;All Files (*)"
        )

        if not filename:
            return

        self.lineEditPathFile.setText(filename)

        self.load_preview(filename)

    def load_preview(self, filename):
        df = self.importer.preview(filename)

        self.tableModel.set_dataframe(df)

        # print(self.tableModel.rowCount())
        # print(self.tableModel.columnCount())

        header = self.tableViewPreview.horizontalHeader()

        header.setStretchLastSection(True)

        header.setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )

        columns = list(df.columns)

        self.comboBoxMapX.clear()
        self.comboBoxMapY.clear()
        self.comboBoxMapZ.clear()

        self.comboBoxMapX.addItems(columns)
        self.comboBoxMapY.addItems(columns)
        self.comboBoxMapZ.addItems(columns)

        for i, name in enumerate(columns):

            lname = name.lower()

            if lname == "x":
                self.comboBoxMapX.setCurrentIndex(i)

            elif lname == "y":
                self.comboBoxMapY.setCurrentIndex(i)

            elif lname == "z":
                self.comboBoxMapZ.setCurrentIndex(i)

        self.listWidgetParametrs.clear()

        for column in columns:

            # Пропускаем координаты
            if column.lower() in ("x", "y", "z"):
                continue

            item = QListWidgetItem(column)

            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )

            item.setCheckState(Qt.CheckState.Checked)

            self.listWidgetParametrs.addItem(item)
