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

        if not hasattr(self.main_window, 'project') or self.main_window.project is None:
            return

        menu = QMenu(self)
        item_text = item.text()
        project = self.main_window.project
        parent_text = self.get_item_parent_name(item)

        # Убираем эмодзи для сравнения
        clean_text = item_text.replace("📁 ", "").replace("📐 ", "").replace("📊 ", "")

        # Корневой элемент - проект
        if item_text == project.name:
            add_action = menu.addAction("Добавить папку в Work")
            add_action.triggered.connect(lambda: self.main_window.add_work_subfolder())

            menu.addSeparator()

            rename_action = menu.addAction("Переименовать проект")
            rename_action.triggered.connect(lambda: self.rename_project(item))

            menu.addSeparator()

            delete_action = menu.addAction("Удалить проект")
            delete_action.triggered.connect(lambda: self.delete_project(item))

        # Секция Work
        elif item_text == "Work":
            add_action = menu.addAction("Добавить папку")
            add_action.triggered.connect(lambda: self.main_window.add_work_subfolder())

        # Папка в Work (первый уровень)
        elif parent_text == "Work" and clean_text.startswith("📁"):
            folder_name = clean_text.replace("📁", "").strip()

            add_action = menu.addAction("Добавить поверхность")
            add_action.triggered.connect(lambda: self.add_surface_to_folder(folder_name))

            add_point_action = menu.addAction("Добавить облако точек")
            add_point_action.triggered.connect(lambda: self.add_pointcloud_to_folder(folder_name))

            menu.addSeparator()

            rename_action = menu.addAction("Переименовать папку")
            rename_action.triggered.connect(lambda: self.rename_work_folder(folder_name, item))

            menu.addSeparator()

            delete_action = menu.addAction("Удалить папку")
            delete_action.triggered.connect(lambda: self.main_window.delete_work_subfolder(folder_name))

        # Элементы внутри папки (поверхности и точки)
        elif parent_text and parent_text.startswith(""):
            # Это элементы внутри папки
            rename_action = menu.addAction("Переименовать")
            rename_action.triggered.connect(lambda: self.rename_item(item))

            menu.addSeparator()

            delete_action = menu.addAction("Удалить")
            delete_action.triggered.connect(lambda: self.delete_item(item))

        # Пути
        elif item_text.startswith("Path:") or item_text.startswith("Work:") or item_text.startswith("Source:"):
            open_action = menu.addAction("Открыть в проводнике")
            open_action.triggered.connect(lambda: self.open_in_explorer(item))

        # Другие элементы
        else:
            rename_action = menu.addAction("Переименовать")
            rename_action.triggered.connect(lambda: self.rename_item(item))

            menu.addSeparator()

            delete_action = menu.addAction("Удалить")
            delete_action.triggered.connect(lambda: self.delete_item(item))

        menu.exec(self.mapToGlobal(position))

    def add_surface_to_folder(self, folder_name):
        """Добавить поверхность в папку"""
        # Здесь будет логика импорта поверхности
        self.main_window.show_import_dialog()

    def add_pointcloud_to_folder(self, folder_name):
        """Добавить облако точек в папку"""
        # Здесь будет логика импорта облака точек
        QMessageBox.information(self, "Информация", f"Добавление облака точек в папку '{folder_name}'")

    def rename_work_folder(self, old_name, item):
        """Переименовать папку в Work"""
        new_name, ok = QInputDialog.getText(
            self,
            "Переименовать папку",
            "Введите новое имя папки:",
            text=old_name
        )

        if ok and new_name:
            self.main_window.rename_work_subfolder(old_name, new_name)

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