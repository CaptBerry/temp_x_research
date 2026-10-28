from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItemModel, QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QTreeView, QMenu, QAbstractItemView

from models.project.Folder import Folder
from models.WellFile import WellFile
from models.LayeredCube import LayeredCube


class ProjectTreeView(QTreeView):
    """The tree stores UUIDs; names are presentation, never object identity."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        # QStandardItem drag/drop would mutate only the widget, not the project.
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def get_item_from_index(self, index):
        model = self.model()
        if isinstance(model, QStandardItemModel):
            return model.itemFromIndex(index)
        return None

    def show_context_menu(self, position):
        item = self.get_item_from_index(self.indexAt(position))
        window = self.main_window
        if item is None or window.project is None:
            return
        self.setCurrentIndex(item.index())
        menu = QMenu(self)
        obj = window.object_for_item(item)
        if item.data(Qt.ItemDataRole.UserRole) == window.PROJECT_ID:
            menu.addAction("Добавить папку", lambda: window.add_work_subfolder())
            menu.addAction("Импортировать объект…", lambda: window.show_import_dialog())
            menu.addAction("Переименовать проект", lambda: window.rename_object())
            if window.project.project_path is not None:
                menu.addAction("Открыть папку проекта", lambda: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(window.project.project_path))))
            menu.addSeparator()
            menu.addAction("Закрыть проект", window.close_project)
        elif obj is not None:
            if isinstance(obj, Folder) and not isinstance(obj, (WellFile, LayeredCube)):
                menu.addAction("Добавить папку", lambda: window.add_work_subfolder(obj))
                menu.addAction("Импортировать объект…", lambda: window.show_import_dialog(obj))
                menu.addSeparator()
            menu.addAction("Переименовать", lambda: window.rename_object(obj))
            if obj is not window.project.root:
                menu.addAction("Удалить", lambda: window.delete_object(obj))
        menu.exec(self.viewport().mapToGlobal(position))
