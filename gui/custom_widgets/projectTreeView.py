from PyQt6.QtWidgets import QTreeView, QMenu
from PyQt6.QtCore import Qt, QPoint

from PyQt6.QtWidgets import QMessageBox


class ProjectTreeView(QTreeView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.main_window = parent

    def show_context_menu(self, position: QPoint):
        index = self.indexAt(position)
        if not index.isValid():
            return

        item = self.model().itemFromIndex(index)
        if not item:
            return

        menu = QMenu(self)

        # Определяем тип элемента по его тексту или данным
        item_text = item.text()

        # Создаем действия в зависимости от типа элемента
        if item_text == self.project.name:
            # Меню для корневого элемента (проект)
            add_action = menu.addAction("Добавить папку")
            add_action.triggered.connect(lambda: self.add_folder_to_project(item))

            menu.addSeparator()

            rename_action = menu.addAction("Переименовать проект")
            rename_action.triggered.connect(lambda: self.rename_project(item))

            menu.addSeparator()

            delete_action = menu.addAction("Удалить проект")
            delete_action.triggered.connect(lambda: self.delete_project(item))

        elif item_text == "Surfaces" or item_text == "Points":
            # Меню для категорий (Surfaces, Points)
            add_action = menu.addAction(f"Добавить {item_text.lower()[:-1]}")
            add_action.triggered.connect(lambda: self.add_item_to_category(item))

        elif item_text.startswith("Path:") or item_text.startswith("Work:") or item_text.startswith("Source:"):
            # Меню для элементов путей
            open_action = menu.addAction("Открыть в проводнике")
            open_action.triggered.connect(lambda: self.open_in_explorer(item))

        else:
            # Меню для обычных элементов (папок, файлов)
            rename_action = menu.addAction("Переименовать")
            rename_action.triggered.connect(lambda: self.rename_item(item))

            menu.addSeparator()

            delete_action = menu.addAction("Удалить")
            delete_action.triggered.connect(lambda: self.delete_item(item))

        menu.exec(self.mapToGlobal(position))

    def add_folder_to_project(self, item):
        """Добавить папку в проект"""
        from models.Folder import Folder

        # Создаем новую папку
        folder = Folder("Новая папка")

        # Добавляем в проект
        self.project.add(folder)

        # Обновляем дерево
        self.update_project_tree()

        self.statusbar.showMessage("Добавлена новая папка", 3000)

    def rename_project(self, item):
        """Переименовать проект"""
        # В реальном приложении здесь должен быть диалог ввода
        from PyQt6.QtWidgets import QInputDialog

        new_name, ok = QInputDialog.getText(
            self,
            "Переименовать проект",
            "Введите новое имя проекта:",
            text=self.project.name
        )

        if ok and new_name:
            self.project.name = new_name
            self.update_project_tree()
            self.statusbar.showMessage(f"Проект переименован в: {new_name}", 3000)

    def delete_project(self, item):
        """Удалить проект"""
        from PyQt6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Удалить проект",
            "Вы уверены, что хотите удалить проект?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.project = None
            self.projectTree.setModel(None)
            self.main_window.statusbar.showMessage("Проект удален", 3000)

    def add_item_to_category(self, item):
        """Добавить элемент в категорию (Surfaces или Points)"""
        from PyQt6.QtWidgets import QInputDialog

        category = item.text().lower()[:-1]  # "Surface" или "Point"

        # Здесь может быть ваш диалог импорта
        if category == "surface":
            self.show_import_dialog()
        else:
            # Для точек можно сделать другой диалог
            QMessageBox.information(self, "Информация", f"Добавление {category}")

    def open_in_explorer(self, item):
        """Открыть папку в проводнике"""
        import subprocess
        import os
        import platform

        # Извлекаем путь из текста элемента
        path_text = item.text()
        if ":" in path_text:
            path = path_text.split(":", 1)[1].strip()

            if os.path.exists(path):
                # Открываем в зависимости от ОС
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":  # macOS
                    subprocess.Popen(["open", path])
                else:  # Linux
                    subprocess.Popen(["xdg-open", path])
            else:
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    f"Путь не существует: {path}"
                )

    def rename_item(self, item):
        """Переименовать элемент"""
        from PyQt6.QtWidgets import QInputDialog

        new_name, ok = QInputDialog.getText(
            self,
            "Переименовать",
            "Введите новое имя:",
            text=item.text()
        )

        if ok and new_name:
            item.setText(new_name)
            self.project.modified = True
            self.main_window.statusbar.showMessage(f"Переименовано в: {new_name}", 3000)

    def delete_item(self, item):
        """Удалить элемент"""
        from PyQt6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Удалить элемент",
            f"Вы уверены, что хотите удалить '{item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Получаем родительский элемент
            parent = item.parent()
            if parent:
                parent.removeRow(item.row())
                self.project.modified = True
                self.main_window.statusbar.showMessage("Элемент удален", 3000)