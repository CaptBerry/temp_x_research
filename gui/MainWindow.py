from PyQt6.QtGui import QAction

from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTreeView

from gui.Viewer3D import Viewer3D

from gui.dialogs.ImportDialog import ImportDialog

from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtGui import QStandardItem

from models.Project import Project
from models.Folder import Folder


class MainWindow(QMainWindow):

    viewerWidget: QWidget
    actionImportXYZ: QAction
    actionnew_project: QAction
    actionopen_project: QAction
    projectTree: QTreeView

    def __init__(self):
        super().__init__()

        ui = Path(__file__).with_name("MainWindow.ui")
        uic.loadUi(ui, self)

        self.viewer = Viewer3D()

        layout = QVBoxLayout(self.viewerWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewer)

        self.actionImportXYZ.triggered.connect(
            self.show_import_dialog
        )

        self.actionnew_project.triggered.connect(
            self.new_project
        )

        # self.actionopen_project.triggered.connect(
        #     self.create_project
        # )


    def show_import_dialog(self):

        dialog = ImportDialog(self)

        result = dialog.exec()

        if result:
            print("Import")
        else:
            print("Cancel")

    def update_project_tree(self):

        model = QStandardItemModel()

        root = model.invisibleRootItem()

        projectItem = QStandardItem(self.project.name)

        root.appendRow(projectItem)

        surfacesItem = QStandardItem("Surfaces")
        pointsItem = QStandardItem("Points")

        projectItem.appendRow(surfacesItem)
        projectItem.appendRow(pointsItem)

        self.projectTree.setModel(model)

        self.projectTree.expandAll()

    def new_project(self):

        self.project = Project()

        self.update_project_tree()
