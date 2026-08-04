from pathlib import Path
from PyQt6 import uic
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QFileDialog, QMessageBox, QStatusBar, QInputDialog
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QStandardItemModel, QStandardItem

from gui.Viewer3D import Viewer3D
from gui.dialogs.ImportDialog import ImportDialog
from models.Project import Project
from models.Folder import Folder
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
        self.action_save_as_project.triggered.connect(self.save_project_as)

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
        if not self.project:
            return

        model = QStandardItemModel()
        root = model.invisibleRootItem()

        # Корневой элемент проекта
        projectItem = self.create_checkable_item(self.project.name, True)
        projectItem.setSelectable(True)

        # Добавляем информацию о путях
        if self.project.path:
            pathItem = QStandardItem(f"Path: {self.project.path}")
            pathItem.setSelectable(True)
            projectItem.appendRow(pathItem)

        if self.project.work_path:
            workItem = QStandardItem(f"Work: {self.project.work_path}")
            workItem.setSelectable(True)
            projectItem.appendRow(workItem)

        if self.project.source_path:
            sourceItem = QStandardItem(f"Source: {self.project.source_path}")
            sourceItem.setSelectable(True)
            projectItem.appendRow(sourceItem)

        # Добавляем структуру Work
        work_section = self.create_checkable_item("Work", True)
        projectItem.appendRow(work_section)

        # Добавляем подпапки Work (только первый уровень)
        for child in self.project.root.children:
            if isinstance(child, Folder):
                folder_item = self.create_checkable_item(f"{child.name}", True)
                work_section.appendRow(folder_item)

                # Добавляем содержимое папки (поверхности и точки)
                self._add_folder_contents(folder_item, child)

        # Добавляем Source секцию (только для отображения)
        source_section = QStandardItem("Source")
        source_section.setSelectable(True)
        projectItem.appendRow(source_section)

        root.appendRow(projectItem)
        self.projectTree.setModel(model)
        self.projectTree.expandAll()

    def _add_folder_contents(self, parent_item, folder):
        """Добавить содержимое папки (поверхности и точки)"""
        from models.Surface import Surface
        from models.PointCloud import PointCloud

        for child in folder.children:
            if isinstance(child, Surface):
                item = self.create_checkable_item(f"{child.name}", True)
                if child.file_path:
                    item.setToolTip(child.file_path)
                parent_item.appendRow(item)
            elif isinstance(child, PointCloud):
                item = self.create_checkable_item(f"{child.name}", True)
                if child.file_path:
                    item.setToolTip(child.file_path)
                parent_item.appendRow(item)

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

    def rename_work_subfolder(self, old_name, new_name):
        """Переименовать подпапку в Work"""
        if not self.project:
            return

        # Находим папку
        folder = self.project.find_by_name(old_name)
        if not folder or not isinstance(folder, Folder):
            return

        # Проверяем, что папка находится на первом уровне
        if not self.project.is_work_subfolder(folder):
            QMessageBox.warning(
                self,
                "Ошибка",
                "Можно переименовывать только папки первого уровня в Work"
            )
            return

        # Проверяем, не существует ли уже папка с новым именем
        for child in self.project.root.children:
            if isinstance(child, Folder) and child.name == new_name:
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    f"Папка с именем '{new_name}' уже существует"
                )
                return

        # Переименовываем физическую папку
        if self.project.work_path:
            old_path = Path(self.project.work_path) / old_name
            new_path = Path(self.project.work_path) / new_name
            if old_path.exists():
                old_path.rename(new_path)

        # Переименовываем в модели
        folder.name = new_name
        self.project.modified = True
        self.update_project_tree()
        self.statusbar.showMessage(f"Папка переименована в '{new_name}'", 3000)

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
        self.project.modified = True
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

    def _update_children_check_state(self, parent_item, checked):
        """Рекурсивно обновить состояние чекбоксов всех детей"""
        for i in range(parent_item.rowCount()):
            child = parent_item.child(i)
            if child and child.isCheckable():
                child.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self._update_children_check_state(child, checked)

    def _update_parent_check_state(self, parent_item):
        """Обновить состояние родительского чекбокса на основе детей"""
        if not parent_item or not parent_item.isCheckable():
            return

        checked_count = 0
        total_count = 0

        for i in range(parent_item.rowCount()):
            child = parent_item.child(i)
            if child and child.isCheckable():
                total_count += 1
                if child.checkState() == Qt.CheckState.Checked:
                    checked_count += 1

        if total_count == 0:
            return

        if checked_count == total_count:
            parent_item.setCheckState(Qt.CheckState.Checked)
        elif checked_count == 0:
            parent_item.setCheckState(Qt.CheckState.Unchecked)
        else:
            parent_item.setCheckState(Qt.CheckState.PartiallyChecked)

    def update_3d_viewer(self):
        """Обновить 3D вьювер на основе выбранных элементов"""
        # TODO: Реализовать обновление 3D вьювера
        pass

    def new_project(self):
        """Создать новый проект"""
        self.project = Project()
        self.update_project_tree()
        self.statusbar.showMessage("Создан новый проект", 3000)

    def save_project(self):
        """Сохранить проект"""
        if not self.project:
            QMessageBox.warning(
                self,
                "Нет проекта",
                "Нет открытого проекта для сохранения"
            )
            return

        if self.project.path:
            try:
                self.project.save()
                self.statusbar.showMessage(f"Проект сохранен: {self.project.path}", 5000)
                self.update_project_tree()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Ошибка сохранения",
                    f"Не удалось сохранить проект:\n{str(e)}"
                )
        else:
            self.save_project_as()

    def save_project_as(self):
        """Сохранить проект как..."""
        if not self.project:
            QMessageBox.warning(
                self,
                "Нет проекта",
                "Нет открытого проекта для сохранения"
            )
            return

        # Предлагаем выбрать папку для сохранения
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сохранения проекта",
            "",
            QFileDialog.Option.ShowDirsOnly
        )

        if not folder_path:
            return

        try:
            project_path = Path(folder_path)

            # Проверяем, не существует ли уже проект с таким именем
            project_file = project_path / f"{self.project.name}.json"
            if project_file.exists():
                reply = QMessageBox.question(
                    self,
                    "Проект существует",
                    f"Проект с именем '{self.project.name}' уже существует. Перезаписать?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return

            self.project.save(project_path)
            self.statusbar.showMessage(f"Проект сохранен как: {project_path}", 5000)
            self.update_project_tree()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка сохранения",
                f"Не удалось сохранить проект:\n{str(e)}"
            )

    def open_project(self):
        """Открыть существующий проект"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть проект",
            "",
            "Project files (*.json);;All files (*.*)"
        )

        if not file_path:
            return

        try:
            self.load_project(Path(file_path))
        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка загрузки",
                f"Не удалось загрузить проект:\n{str(e)}"
            )

    def load_project(self, project_file: Path):
        """Загрузить проект из файла"""
        self.project = Project.load(project_file)
        self.update_project_tree()
        self.statusbar.showMessage(f"Проект загружен: {self.project.name}", 5000)

    def create_project_at_path(self, project_path: Path):
        """Создать новый проект по указанному пути"""
        try:
            self.project = Project(
                name=project_path.name,
                path=str(project_path)
            )
            self.project.save()
            self.update_project_tree()
            self.statusbar.showMessage(f"Проект создан в: {project_path}", 5000)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось создать проект:\n{str(e)}"
            )