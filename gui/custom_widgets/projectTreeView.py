from PyQt6.QtWidgets import QTreeView, QMenu, QMessageBox, QInputDialog
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QStandardItemModel, QStandardItem
import subprocess
import os
import platform


class ProjectTreeView(QTreeView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.main_window = parent
        print("ProjectTreeView успешно создан")

        # Включаем возможность выбирать элементы
        self.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)

    def get_item_from_index(self, index):
        """Безопасное получение элемента из модели"""
        model = self.model()
        if isinstance(model, QStandardItemModel):
            return model.itemFromIndex(index)
        return None

    def get_item_parent_name(self, item):
        """Получить имя родительского элемента"""
        parent = item.parent()
        if parent:
            return parent.text()
        return None

    def show_context_menu(self, position: QPoint):
        """Показать контекстное меню"""
        index = self.indexAt(position)
        if not index.isValid():
            return

        item = self.get_item_from_index(index)
        if not item:
            return

        # Проверяем проект
        if not hasattr(self.main_window, 'project') or self.main_window.project is None:
            return

        menu = QMenu(self)
        item_text = item.text()
        project = self.main_window.project
        parent_text = self.get_item_parent_name(item)

        # Определяем тип элемента
        if item_text == project.name:
            # Корневой элемент - проект
            add_action = menu.addAction("Добавить папку")
            add_action.triggered.connect(lambda: self.add_folder_to_project(item))

            menu.addSeparator()

            # Действия для работы с чекбоксами
            check_action = menu.addAction("Выбрать все")
            check_action.triggered.connect(lambda: self.check_all_items(item, True))

            uncheck_action = menu.addAction("Снять все")
            uncheck_action.triggered.connect(lambda: self.check_all_items(item, False))

            menu.addSeparator()

            rename_action = menu.addAction("Переименовать проект")
            rename_action.triggered.connect(lambda: self.rename_project(item))

            menu.addSeparator()

            delete_action = menu.addAction("Удалить проект")
            delete_action.triggered.connect(lambda: self.delete_project(item))

        elif item_text == "Surfaces" or item_text == "Points":
            # Категории
            category_name = item_text.lower()[:-1]
            add_action = menu.addAction(f"Добавить {category_name}")
            add_action.triggered.connect(lambda: self.add_item_to_category(item))

            menu.addSeparator()

            # Действия для работы с чекбоксами
            check_action = menu.addAction("Выбрать все")
            check_action.triggered.connect(lambda: self.check_all_items(item, True))

            uncheck_action = menu.addAction("Снять все")
            uncheck_action.triggered.connect(lambda: self.check_all_items(item, False))

        elif item_text.startswith("Path:") or item_text.startswith("Work:") or item_text.startswith("Source:"):
            # Пути
            open_action = menu.addAction("Открыть в проводнике")
            open_action.triggered.connect(lambda: self.open_in_explorer(item))

        else:
            # Обычные элементы (папки, поверхности, точки)
            # Проверяем, есть ли у элемента чекбокс
            if item.isCheckable():
                # Переключаем состояние чекбокса
                if item.checkState() == Qt.CheckState.Checked:
                    toggle_action = menu.addAction("Снять выделение")
                else:
                    toggle_action = menu.addAction("Выделить")
                toggle_action.triggered.connect(lambda: self.toggle_item_check(item))

                menu.addSeparator()

            rename_action = menu.addAction("Переименовать")
            rename_action.triggered.connect(lambda: self.rename_item(item))

            menu.addSeparator()

            delete_action = menu.addAction("Удалить")
            delete_action.triggered.connect(lambda: self.delete_item(item))

        menu.exec(self.mapToGlobal(position))

    def toggle_item_check(self, item):
        """Переключить состояние чекбокса элемента"""
        if not item.isCheckable():
            return

        current_state = item.checkState()
        new_state = Qt.CheckState.Unchecked if current_state == Qt.CheckState.Checked else Qt.CheckState.Checked
        item.setCheckState(new_state)

        # Обновляем детей и родителей
        self.main_window._update_children_check_state(item, new_state == Qt.CheckState.Checked)

        parent = item.parent()
        if parent:
            self.main_window._update_parent_check_state(parent)

        self.main_window.update_3d_viewer()

    def check_all_items(self, parent_item, checked):
        """Выбрать/снять все элементы в ветке"""
        for i in range(parent_item.rowCount()):
            child = parent_item.child(i)
            if child and child.isCheckable():
                child.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self.check_all_items(child, checked)

        # Обновляем родителя
        parent = parent_item.parent()
        if parent:
            self.main_window._update_parent_check_state(parent)

        self.main_window.update_3d_viewer()

    def add_folder_to_project(self, item):
        """Добавить папку в проект"""
        from models.Folder import Folder

        folder = Folder("Новая папка")
        self.main_window.project.add(folder)
        self.main_window.update_project_tree()
        self.main_window.statusbar.showMessage("Добавлена новая папка", 3000)

    def rename_project(self, item):
        """Переименовать проект"""
        new_name, ok = QInputDialog.getText(
            self,
            "Переименовать проект",
            "Введите новое имя проекта:",
            text=self.main_window.project.name
        )

        if ok and new_name:
            self.main_window.project.name = new_name
            self.main_window.update_project_tree()
            self.main_window.statusbar.showMessage(f"Проект переименован в: {new_name}", 3000)

    def delete_project(self, item):
        """Удалить проект"""
        reply = QMessageBox.question(
            self,
            "Удалить проект",
            "Вы уверены, что хотите удалить проект?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.main_window.project = None
            self.setModel(None)
            self.main_window.statusbar.showMessage("Проект удален", 3000)

    def add_item_to_category(self, item):
        """Добавить элемент в категорию"""
        category = item.text().lower()[:-1]

        if category == "surface":
            self.main_window.show_import_dialog()
        else:
            QMessageBox.information(self, "Информация", f"Добавление {category}")

    def open_in_explorer(self, item):
        """Открыть папку в проводнике"""
        path_text = item.text()
        if ":" in path_text:
            path = path_text.split(":", 1)[1].strip()

            if os.path.exists(path):
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            else:
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    f"Путь не существует: {path}"
                )

    def rename_item(self, item):
        """Переименовать элемент"""
        new_name, ok = QInputDialog.getText(
            self,
            "Переименовать",
            "Введите новое имя:",
            text=item.text()
        )

        if ok and new_name:
            item.setText(new_name)
            self.main_window.project.modified = True
            self.main_window.statusbar.showMessage(f"Переименовано в: {new_name}", 3000)

    def delete_item(self, item):
        """Удалить элемент"""
        reply = QMessageBox.question(
            self,
            "Удалить элемент",
            f"Вы уверены, что хотите удалить '{item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            parent = item.parent()
            if parent:
                parent.removeRow(item.row())
                self.main_window.project.modified = True
                self.main_window.statusbar.showMessage("Элемент удален", 3000)