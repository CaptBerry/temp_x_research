from pathlib import Path
from PyQt6 import uic
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTreeView, QFileDialog, QMessageBox, QStatusBar
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QAction, QStandardItemModel, QStandardItem

from gui.Viewer3D import Viewer3D
from gui.dialogs.ImportDialog import ImportDialog
from models.Project import Project
from gui.custom_widgets.projectTreeView import ProjectTreeView


class MainWindow(QMainWindow):

    actionImportXYZ: QAction
    action_open_project: QAction
    action_create_project: QAction
    action_save_project: QAction  # Добавим действие сохранения
    action_save_as_project: QAction  # Добавим действие "Сохранить как"

    viewerWidget: QWidget
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
        print("Заменяем QTreeView на ProjectTreeView")

        parent_widget = self.projectTree.parent()
        parent_layout = parent_widget.layout()

        if parent_layout is None:
            print("Ошибка: parent_layout is None")
            return

        index = parent_layout.indexOf(self.projectTree)
        if index == -1:
            print("Ошибка: виджет не найден в layout")
            return

        new_tree = ProjectTreeView(self)
        parent_layout.replaceWidget(self.projectTree, new_tree)

        old_tree = self.projectTree
        old_tree.deleteLater()

        self.projectTree = new_tree
        print("Замена успешно выполнена")

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

    def create_checkable_item(self, text, checked=False):
        """Создать элемент с чекбоксом"""
        item = QStandardItem(text)
        item.setCheckable(True)
        if checked:
            item.setCheckState(Qt.CheckState.Checked)
        else:
            item.setCheckState(Qt.CheckState.Unchecked)
        return item

    def update_project_tree(self):
        """Обновить дерево проекта с чекбоксами"""
        if not self.project:
            return

        model = QStandardItemModel()
        root = model.invisibleRootItem()

        # Корневой элемент проекта с чекбоксом
        projectItem = self.create_checkable_item(self.project.name, True)
        projectItem.setSelectable(True)

        # Добавляем информацию о путях (без чекбоксов)
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

        root.appendRow(projectItem)
        self.projectTree.setModel(model)
        self.projectTree.expandAll()

        # Подключаем сигнал изменения состояния чекбоксов
        self.projectTree.model().dataChanged.connect(self.on_item_checked_changed)

    def _add_tree_items_with_checkboxes(self, parent_item, folder, category_type):
        """Рекурсивно добавить элементы с чекбоксами"""
        from models.Folder import Folder
        from models.Surface import Surface
        from models.PointCloud import PointCloud

        for child in folder.children:
            if isinstance(child, Folder):
                # Папка с чекбоксом
                folder_item = self.create_checkable_item(child.name, True)
                parent_item.appendRow(folder_item)
                # Рекурсивно добавляем содержимое папки
                self._add_tree_items_with_checkboxes(folder_item, child, category_type)
            elif isinstance(child, Surface) and category_type == "surface":
                item = self.create_checkable_item(child.name, True)
                if child.file_path:
                    item.setToolTip(child.file_path)
                parent_item.appendRow(item)
            elif isinstance(child, PointCloud) and category_type == "point":
                item = self.create_checkable_item(child.name, True)
                if child.file_path:
                    item.setToolTip(child.file_path)
                parent_item.appendRow(item)

    def on_item_checked_changed(self, top_left, bottom_right, roles):
        """Обработчик изменения состояния чекбокса"""
        if Qt.ItemDataRole.CheckStateRole not in roles:
            return

        # Получаем измененный элемент
        item = self.projectTree.model().itemFromIndex(top_left)
        if not item:
            return

        # Получаем новое состояние
        is_checked = item.checkState() == Qt.CheckState.Checked

        # Блокируем сигналы чтобы избежать рекурсии
        self.projectTree.model().blockSignals(True)

        # Рекурсивно обновляем всех детей
        self._update_children_check_state(item, is_checked)

        # Обновляем родителя
        parent = item.parent()
        if parent:
            self._update_parent_check_state(parent)

        self.projectTree.model().blockSignals(False)

        # Обновляем отображение в 3D вьювере
        self.update_3d_viewer()

        # Выводим информацию в статусбар
        checked_count = self.count_checked_items()
        self.statusbar.showMessage(f"Выбрано элементов: {checked_count}", 2000)

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

    def count_checked_items(self, parent=None):
        """Подсчитать количество выбранных элементов"""
        if parent is None:
            model = self.projectTree.model()
            if not model:
                return 0
            parent = model.invisibleRootItem()

        count = 0
        for i in range(parent.rowCount()):
            child = parent.child(i)
            if child:
                if child.isCheckable() and child.checkState() == Qt.CheckState.Checked:
                    count += 1
                count += self.count_checked_items(child)
        return count

    def get_checked_items(self, parent=None):
        """Получить список всех выбранных элементов"""
        if parent is None:
            model = self.projectTree.model()
            if not model:
                return []
            parent = model.invisibleRootItem()

        checked_items = []
        for i in range(parent.rowCount()):
            child = parent.child(i)
            if child:
                if child.isCheckable() and child.checkState() == Qt.CheckState.Checked:
                    checked_items.append(child)
                checked_items.extend(self.get_checked_items(child))
        return checked_items

    def update_3d_viewer(self):
        """Обновить 3D вьювер на основе выбранных элементов"""
        # Получаем выбранные элементы
        checked_items = self.get_checked_items()

        # Здесь будет логика обновления 3D вьювера
        print(f"Обновление 3D вьювера: выбрано {len(checked_items)} элементов")

        # TODO: Обновить отображение в 3D вьювере

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

        # Если проект уже имеет путь, сохраняем по нему
        if self.project.path:
            try:
                self.project.save()
                self.statusbar.showMessage(f"Проект сохранен: {self.project.path}", 5000)
                self.update_project_tree()  # Обновляем для отображения путей
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Ошибка сохранения",
                    f"Не удалось сохранить проект:\n{str(e)}"
                )
        else:
            # Если пути нет - вызываем "Сохранить как"
            self.save_project_as()

    def save_project_as(self):
        """Сохранить проект как... (выбор папки)"""
        if not self.project:
            QMessageBox.warning(
                self,
                "Нет проекта",
                "Нет открытого проекта для сохранения"
            )
            return

        # Диалог выбора папки для сохранения
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
            # Сохраняем проект по выбранному пути
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
        # Ищем файл project.json
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть проект",
            "",
            "Project files (project.json);;All files (*.*)"
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

        # TODO: Загрузить данные в 3D вьювер

    def create_project_at_path(self, project_path: Path):
        """Создать новый проект по указанному пути"""
        try:
            # Создаем объект проекта
            self.project = Project(
                name=project_path.name,
                path=str(project_path)
            )

            # Сохраняем проект (создает все папки и project.json)
            self.project.save()

            # Обновляем дерево
            self.update_project_tree()

            self.statusbar.showMessage(f"Проект создан в: {project_path}", 5000)

        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось создать проект:\n{str(e)}"
            )