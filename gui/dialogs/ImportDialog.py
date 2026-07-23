from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QDialog, QFileDialog

from importers.CsvImporter import CsvImporter

from models.PandasTableModel import PandasTableModel
from PyQt6.QtWidgets import QHeaderView


class ImportDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.importer = CsvImporter()

        ui = Path(__file__).with_name("ImportDialog.ui")
        uic.loadUi(ui, self)

        self.init_ui()
        self.connect_signals()

    def init_ui(self):

        self.setWindowTitle("Import Data")

        self.buttonImport.setEnabled(False)

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

        # self.load_preview(filename)

    def load_preview(self, filename):
        df = self.importer.preview(filename)

        model = PandasTableModel(df)

        self.previewTable.setModel(model)

        header = self.previewTable.horizontalHeader()

        header.setStretchLastSection(True)

        header.setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )

        columns = list(df.columns)

        self.xColumnCombo.clear()
        self.yColumnCombo.clear()
        self.zColumnCombo.clear()

        self.xColumnCombo.addItems(columns)
        self.yColumnCombo.addItems(columns)
        self.zColumnCombo.addItems(columns)

        for i, name in enumerate(columns):

            lname = name.lower()

            if lname == "x":
                self.xColumnCombo.setCurrentIndex(i)

            elif lname == "y":
                self.yColumnCombo.setCurrentIndex(i)

            elif lname == "z":
                self.zColumnCombo.setCurrentIndex(i)