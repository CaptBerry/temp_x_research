from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QStandardItemModel, QDesktopServices, QDrag
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QTreeView, QMenu, QAbstractItemView

from models.project.Folder import Folder
from models.WellFile import WellFile
from models.LayeredCube import LayeredCube
from models.DisplayPoints import LayeredDisplayPoints
from models.eda import supports_eda
from models.CalculationArtifact import CalculationArtifact, TrainingSet, CatalogWell


class ProjectTreeView(QTreeView):
    """The tree stores UUIDs; names are presentation, never object identity."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        # QStandardItem drag/drop would mutate only the widget, not the project.
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def startDrag(self, supported_actions):
        item = self.get_item_from_index(self.currentIndex())
        obj = self.main_window.object_for_item(item)
        if obj is None:
            return
        data = QMimeData()
        data.setData("application/x-xsearch-object", obj.uuid.encode())
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.exec(Qt.DropAction.CopyAction)

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
            if supports_eda(window.project.root):
                menu.addAction("Разведочный анализ (EDA)…", lambda: window.open_eda(window.project.root))
            if window.project.project_path is not None:
                menu.addAction("Открыть папку проекта", lambda: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(window.project.project_path))))
            menu.addSeparator()
            menu.addAction("Закрыть проект", window.close_project)
        elif obj is not None:
            if isinstance(obj, CatalogWell):
                menu.addAction("Показать скважину в 3D", lambda: window.show_object_in_3d(obj.uuid, "focus"))
                menu.addAction("Открыть каталог образцов…", lambda: window.open_calculation(obj.parent))
                menu.exec(self.viewport().mapToGlobal(position))
                return
            if obj.metadata.get("system_role") == "canvas_results":
                menu.addAction("Открыть Canvas", lambda: window.workspace_tabs.setCurrentIndex(1))
            else:
                menu.addAction("Добавить на Canvas", lambda: (
                    window.canvas_editor.add_source(obj.uuid), window.workspace_tabs.setCurrentIndex(1)))
            if isinstance(obj, CalculationArtifact):
                menu.addAction("Открыть результат расчёта…", lambda: window.open_calculation(obj))
            if isinstance(obj, TrainingSet):
                menu.addAction("Показать каталог в 3D", lambda: window.show_object_in_3d(obj.uuid, "focus"))
            if supports_eda(obj):
                menu.addAction("Разведочный анализ (EDA)…", lambda: window.open_eda(obj))
                menu.addSeparator()
            if isinstance(obj, Folder) and obj.children:
                menu.addAction("Выбрать все", lambda: window.set_container_visibility(obj, True))
                menu.addAction("Отменить выбор", lambda: window.set_container_visibility(obj, False))
                menu.addSeparator()
            if isinstance(obj, Folder) and not isinstance(obj, (WellFile, LayeredCube, LayeredDisplayPoints)):
                menu.addAction("Добавить папку", lambda: window.add_work_subfolder(obj))
                menu.addAction("Импортировать объект…", lambda: window.show_import_dialog(obj))
                menu.addSeparator()
            menu.addAction("Переименовать", lambda: window.rename_object(obj))
            if obj is not window.project.root:
                menu.addAction("Удалить", lambda: window.delete_object(obj))
        menu.exec(self.viewport().mapToGlobal(position))
