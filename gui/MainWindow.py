from pathlib import Path
from PyQt6 import uic
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QFileDialog, QMessageBox, QStatusBar, QInputDialog
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QStandardItemModel, QStandardItem

from gui.Viewer3D import Viewer3D
from gui.dialogs.ImportDialog import ImportDialog
from models.project.Project import Project
from models.project.Folder import Folder
from gui.custom_widgets.projectTreeView import ProjectTreeView

class MainWindow(QMainWindow):
    viewerWidget: QWidget
    actionImportXYZ: QAction
    action_open_project: QAction
    action_create_project: QAction
    action_save_project: QAction
    action_save_as_project: QAction
    projectTree: ProjectTreeView
    statusbar: QStatusBar

    def __init__(self):
        super().__init__()

        ui = Path(__file__).with_name("MainWindow.ui")
        uic.loadUi(ui, self)

        # Заменяем стандартный QTreeView на ProjectTreeView
        self.replace_tree_view()

        self.viewer = Viewer3D()

        layout = QVBoxLayout(self.viewerWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewer)

        self.actionImportXYZ.triggered.connect(self.show_import_dialog)
        self.action_open_project.triggered.connect(self.open_project)
        self.action_create_project.triggered.connect(self.new_project)
        self.action_save_project.triggered.connect(self.save_project)
        # self.action_save_as_project.triggered.connect(self.save_project_as)

        # Инициализация проекта
        self.project = None

    def replace_tree_view(self):
        """Заменить стандартный QTreeView на ProjectTreeView"""
        parent_widget = self.projectTree.parent()
        parent_layout = parent_widget.layout()

        if parent_layout is None:
            return

        index = parent_layout.indexOf(self.projectTree)
        if index == -1:
            return

        new_tree = ProjectTreeView(self)
        parent_layout.replaceWidget(self.projectTree, new_tree)

        old_tree = self.projectTree
        old_tree.deleteLater()

        self.projectTree = new_tree

    def create_checkable_item(self, text, checked=False):
        """Создать элемент с чекбоксом"""
        item = QStandardItem(text)
        item.setCheckable(True)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    def update_project_tree(self):
        """Обновить дерево проекта"""

        if self.project is None:
            return

        model = QStandardItemModel()

        root_item = model.invisibleRootItem()

        project_item = self.create_checkable_item(
            self.project.name,
            True
        )

        root_item.appendRow(project_item)

        self._build_tree(
            self.project.root,
            project_item
        )

        self.projectTree.setModel(model)

        self.projectTree.expandAll()

    def _build_tree(self, project_node, tree_item):

        for child in project_node:

            item = self.create_checkable_item(
                child.name,
                child.visible
            )

            tree_item.appendRow(item)

            if isinstance(child, Folder):
                self._build_tree(
                    child,
                    item
                )

    def add_work_subfolder(self):
        """Добавить подпапку в Work"""
        if not self.project:
            return

        # Проверяем количество существующих подпапок
        existing_folders = self.project.get_work_subfolders()

        # Запрашиваем имя новой папки
        name, ok = QInputDialog.getText(
            self,
            "Новая папка",
            "Введите имя папки:"
        )

        if not ok or not name:
            return

        # Проверяем, существует ли уже папка с таким именем
        for folder in existing_folders:
            if folder.name == name:
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    f"Папка с именем '{name}' уже существует"
                )
                return

        # Добавляем папку
        if self.project.add_work_subfolder(name):
            self.update_project_tree()
            self.statusbar.showMessage(f"Папка '{name}' создана в Work", 3000)
        else:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Не удалось создать папку"
            )

    def delete_work_subfolder(self, name):
        """Удалить подпапку из Work"""
        if not self.project:
            return

        # Проверяем, есть ли содержимое в папке
        folder = self.project.find_by_name(name)
        if not folder or not isinstance(folder, Folder):
            return

        if len(folder.children) > 0:
            reply = QMessageBox.question(
                self,
                "Удаление папки",
                f"Папка '{name}' содержит данные. Удалить ее вместе с содержимым?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # Удаляем физическую папку
        if self.project.work_path:
            folder_path = Path(self.project.work_path) / name
            if folder_path.exists():
                import shutil
                shutil.rmtree(folder_path)

        # Удаляем из модели
        self.project.remove(folder)
        self.update_project_tree()
        self.statusbar.showMessage(f"Папка '{name}' удалена", 3000)

    def show_import_dialog(self):
        if not self.project:
            QMessageBox.warning(
                self,
                "Нет проекта",
                "Сначала создайте или откройте проект"
            )
            return

        dialog = ImportDialog(self)
        result = dialog.exec()
        if result:
            print("Import")
        else:
            print("Cancel")


    def update_3d_viewer(self):
        """Обновить 3D вьювер на основе выбранных элементов"""
        # TODO: Реализовать обновление 3D вьювера
        pass

    def new_project(self):

        # 1. Выбираем папку

        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для нового проекта"
        )

        if not folder:
            return

        # 2. Имя проекта

        name, ok = QInputDialog.getText(
            self,
            "Создание проекта",
            "Имя проекта:"
        )

        if not ok:
            return

        if not name.strip():
            return

        # 3. Создаем каталог проекта

        project_path = Path(folder) / name

        if project_path.exists():
            QMessageBox.warning(
                self,
                "Ошибка",
                "Такая папка уже существует."
            )

            return

        # 4. Создаем проект

        self.project = Project.create(
            project_path,
            name
        )

        # 5. Обновляем интерфейс

        self.update_project_tree()

        self.statusbar.showMessage(
            f"Проект '{name}' создан."
        )

    def save_project(self):

        if self.project is None:
            return

        self.project.save()

        self.statusbar.showMessage("Проект сохранен")

    def open_project(self):

        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть проект",
            "",
            "Project (*.json)"
        )

        if not file_name:
            return

        self.project = Project.open(file_name)

        self.update_project_tree()

        self.statusbar.showMessage(
            f"Проект '{self.project.name}' открыт."
        )
