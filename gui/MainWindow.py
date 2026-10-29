import logging
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QAction, QKeySequence, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow, QVBoxLayout, QFileDialog, QMessageBox, QInputDialog, QScrollArea, QFrame

from gui.Viewer3D import Viewer3D
from gui.dialogs.ImportDialog import ImportDialog
from gui.dialogs.ThemeDialog import ThemeDialog
from gui.theme import THEMES, apply_theme
from gui.custom_widgets.projectTreeView import ProjectTreeView
from gui.custom_widgets.AppearanceEditor import AppearanceEditor
from gui.custom_widgets.AxisScaleEditor import AxisScaleEditor
from models.project.Project import Project
from models.project.Folder import Folder
from models.PointCloud import PointCloud
from models.Well import Well
from models.WellFile import WellFile
from models.DataCube import DataCube
from models.LayeredCube import LayeredCube
from models.Surface import Surface

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    PROJECT_ID = "__project__"

    def __init__(self, *, settings=None, restore_session=True):
        super().__init__()
        uic.loadUi(Path(__file__).with_name("MainWindow.ui"), self)
        self.project = None
        self.settings = settings if settings is not None else QSettings("AVPD", "XSearch")
        self.replace_tree_view()
        self.viewer = Viewer3D(self)
        layout = QVBoxLayout(self.viewerWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewer)
        saved_theme = self.settings.value("theme", "light", type=str)
        self.set_theme(saved_theme if saved_theme in THEMES else "light", save=False)
        self.appearance_editor = AppearanceEditor(self)
        self.axis_scale_editor = AxisScaleEditor(self)
        self.propertyTree.setMaximumHeight(250)
        self.PropertiesPanel.layout().addWidget(self.axis_scale_editor)
        self.appearance_scroll = QScrollArea(self.PropertiesPanel)
        self.appearance_scroll.setWidgetResizable(True)
        self.appearance_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.appearance_scroll.setWidget(self.appearance_editor)
        self.PropertiesPanel.layout().addWidget(self.appearance_scroll)
        self.PropertiesPanel.setMinimumWidth(290)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([200, 550, 300])
        self.appearance_editor.appearanceChanged.connect(self._change_appearance)
        self.appearance_editor.paletteRequested.connect(self._open_palette)
        self.axis_scale_editor.scaleChanged.connect(self._change_axis_scale)
        self._connect_actions()
        self.update_project_tree()
        self.update_window_state()
        if restore_session:
            self.restore_last_project()

    def _connect_actions(self):
        self.menu.setTitle("Файл")
        actions = (
            (self.action_create_project, "Создать проект…", QKeySequence.StandardKey.New, self.new_project),
            (self.action_open_project, "Открыть проект…", QKeySequence.StandardKey.Open, self.open_project),
            (self.action_save_project, "Сохранить", QKeySequence.StandardKey.Save, self.save_project),
            (self.action_save_as_project, "Сохранить как…", QKeySequence.StandardKey.SaveAs, self.save_project_as),
        )
        for action, text, shortcut, callback in actions:
            action.setText(text)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
        self.actionImportXYZ.setText("Импортировать объект…")
        self.actionImportXYZ.triggered.connect(lambda: self.show_import_dialog())
        self.menu.addSeparator()
        self.action_close_project = QAction("Закрыть проект", self)
        self.action_close_project.triggered.connect(self.close_project)
        self.menu.addAction(self.action_close_project)
        self.action_exit = QAction("Выход", self)
        self.action_exit.triggered.connect(self.close)
        self.menu.addAction(self.action_exit)
        self.action_theme = QAction("Тема приложения…", self)
        self.action_theme.triggered.connect(self._open_theme_dialog)
        self.menuTools.addAction(self.action_theme)

    def set_theme(self, theme, *, save=True):
        background = apply_theme(QApplication.instance(), theme)
        self.viewer.set_theme(background)
        self.theme = theme
        if save:
            self.settings.setValue("theme", theme)
            self.settings.sync()

    def _open_theme_dialog(self):
        dialog = ThemeDialog(self.theme, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_theme(dialog.selected_theme)

    def replace_tree_view(self):
        old_tree = self.projectTree
        self.projectTree = ProjectTreeView(self)
        old_tree.parent().layout().replaceWidget(old_tree, self.projectTree)
        old_tree.deleteLater()

    def update_window_state(self):
        active = self.project is not None
        for action in (self.action_save_project, self.action_save_as_project,
                       self.action_close_project, self.actionImportXYZ):
            action.setEnabled(active)
        name = self.project.name if active else "Нет проекта"
        self.setWindowTitle(f"{name}[*] — X Search")
        self.setWindowModified(active and self.project.has_unsaved_changes())

    def _report_error(self, title, error):
        logger.error("%s: %s", title, error, exc_info=True)
        QMessageBox.warning(self, title, str(error))

    def _remember_project(self):
        if self.project is not None and self.project.project_file is not None:
            self.settings.setValue("last_project", str(self.project.project_file))
        else:
            self.settings.remove("last_project")
        self.settings.sync()

    def restore_last_project(self):
        filename = self.settings.value("last_project", "", type=str)
        if filename:
            try:
                self.set_project(Project.open(filename))
            except Exception as error:
                self.settings.remove("last_project")
                self._report_error("Не удалось восстановить последний проект", error)

    def set_project(self, project):
        # Load/render the candidate before replacing the current project.
        previous = self.project
        try:
            self._render_project(project)
        except Exception:
            self._render_project(previous)
            raise
        self.project = project
        self.axis_scale_editor.set_project(project)
        self.update_project_tree()
        self.update_window_state()
        self._remember_project()

    def _render_project(self, project):
        with self.viewer.scene_update():
            self.viewer.clear_scene()
            self.viewer.set_axis_scale(project.axis_scale if project is not None else (1, 1, 1))
            if project is not None:
                for obj in project.walk():
                    if project.is_visible(obj):
                        self.viewer.add_object(obj)
                self.viewer.focus_on_scene()

    def update_3d_viewer(self):
        self._render_project(self.project)

    def set_container_visibility(self, container, visible):
        if self.project is None:
            return
        try:
            if self.project.set_subtree_visible(container, visible):
                self.update_3d_viewer()
                self.update_project_tree()
                self.update_window_state()
        except Exception as error:
            self.update_project_tree()
            self.update_window_state()
            self._report_error("Не удалось изменить видимость контейнера", error)

    def update_project_tree(self):
        selected = self.projectTree.get_item_from_index(self.projectTree.currentIndex())
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected is not None else None
        previous_model = self.projectTree.model()
        model = QStandardItemModel(self.projectTree)
        model.setHorizontalHeaderLabels(["Проект"])
        if self.project is not None:
            item = QStandardItem(self.project.name)
            item.setData(self.PROJECT_ID, Qt.ItemDataRole.UserRole)
            model.appendRow(item)
            self._build_tree(self.project.root, item)
        self.projectTree.setModel(model)
        model.itemChanged.connect(self._tree_item_changed)
        self.projectTree.selectionModel().currentChanged.connect(self._show_properties)
        self.projectTree.expandAll()
        if selected_id is not None:
            self.select_object(selected_id)
        self._show_properties()
        if previous_model is not None:
            previous_model.deleteLater()

    def select_object(self, object_id):
        model = self.projectTree.model()
        matches = model.match(model.index(0, 0), Qt.ItemDataRole.UserRole, object_id, 1,
                              Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
        if matches:
            self.projectTree.setCurrentIndex(matches[0])

    def _build_tree(self, obj, parent_item):
        item = QStandardItem(obj.name)
        item.setData(obj.uuid, Qt.ItemDataRole.UserRole)
        item.setCheckable(True)
        item.setCheckState(Qt.CheckState.Checked if obj.visible else Qt.CheckState.Unchecked)
        parent_item.appendRow(item)
        for child in obj.children:
            self._build_tree(child, item)

    def object_for_item(self, item):
        if self.project is None or item is None:
            return None
        return self.project.find_by_id(item.data(Qt.ItemDataRole.UserRole))

    def _tree_item_changed(self, item):
        if self.project is None:
            return
        try:
            if item.data(Qt.ItemDataRole.UserRole) == self.PROJECT_ID:
                self.project.rename_project(item.text())
            else:
                obj = self.object_for_item(item)
                if obj is None:
                    return
                self.project.rename(obj, item.text())
                visible = item.checkState() == Qt.CheckState.Checked
                if obj.visible != visible:
                    self.project.set_visible(obj, visible)
                    self.update_3d_viewer()
            self.update_window_state()
            self._show_properties()
        except Exception as error:
            self.update_project_tree()
            self.update_window_state()
            self._report_error("Не удалось изменить объект", error)

    def _show_properties(self, *args):
        obj = None
        old_model = self.propertyTree.model()
        model = QStandardItemModel(self.propertyTree)
        model.setHorizontalHeaderLabels(["Свойство", "Значение"])
        if self.project is not None:
            item = self.projectTree.get_item_from_index(self.projectTree.currentIndex())
            obj = self.object_for_item(item)
            values = {"Проект": self.project.name, "Папка": str(self.project.project_path or "")}
            if obj is not None:
                type_name = {"folder": "Папка", "pointcloud": "Облако точек",
                             "well": "Скважина", "wellfile": "Файл скважин",
                             "cube": "Куб данных", "layered_cube": "Послойный куб",
                             "surface": "Поверхность"}.get(obj.TYPE, obj.TYPE)
                values.update({"Имя": obj.name, "Тип": type_name, "UUID": obj.uuid})
                if isinstance(obj, PointCloud):
                    values.update({"Строк": obj.point_count, "X": obj.x_column,
                                   "Y": obj.y_column, "Z": obj.z_column,
                                   "Параметры": ", ".join(map(str, obj.parameters))})
                if isinstance(obj, Well):
                    values.update({"ID скважины": obj.well_id,
                                   "Длина траектории": f"{obj.trajectory_length:.3f}"})
                elif isinstance(obj, DataCube):
                    if "layer_index" in obj.metadata:
                        values["Индекс слоя"] = obj.metadata["layer_index"]
                    if obj.is_corner_point:
                        values.update({"Геометрия": "Corner-point grid (COORD/ZCORN)",
                                       "Размеры I×J×K": "×".join(map(str, obj.grid_shape)),
                                       "Активных ячеек": obj.corner_grid.active_count})
                        if "grid_build_method" in obj.metadata:
                            values["Построение"] = ("По рядам центров" if
                                                   obj.metadata["grid_build_method"] == "rows"
                                                   else "Равномерная сетка")
                            values["Исходных точек"] = obj.metadata.get("source_point_count", "")
                            values["Соединение интервалов"] = (
                                "Да" if obj.metadata.get("connect_existing_cells") else "Нет")
                    else:
                        values.update({"Узлы X×Y×Z": "×".join(map(str, obj.grid_shape)),
                                       "Регулярная сетка": "Да" if obj.is_regular_grid else "Нет"})
                elif isinstance(obj, WellFile):
                    values.update({"Скважин": len(obj.wells), "Идентификаторы": ", ".join(obj.well_ids),
                                   "Параметры": ", ".join(obj.parameters)})
                elif isinstance(obj, LayeredCube):
                    values.update({"Слоёв": len(obj.layers), "Колонка слоя": obj.layer_column,
                                   "Кровля": obj.roof_column, "Подошва": obj.base_column,
                                   "Индексы": ", ".join(str(layer.metadata["layer_index"])
                                                        for layer in obj.layers)})
                elif isinstance(obj, Surface):
                    kind = {"general": "Обычная", "section": "Разрез", "fault": "Трещина"}.get(obj.surface_kind, obj.surface_kind)
                    values.update({"Вид поверхности": kind, "Вершин": len(obj.vertices),
                                   "Граней": obj.face_count, "Площадь": f"{obj.area:.3f}"})
            for key, value in values.items():
                row = [QStandardItem(str(key)), QStandardItem(str(value))]
                for cell in row:
                    cell.setEditable(False)
                model.appendRow(row)
        self.propertyTree.setModel(model)
        self.appearance_editor.set_object(obj)
        if old_model is not None:
            old_model.deleteLater()

    def _change_appearance(self, object_id, changes):
        if self.project is None:
            return
        obj = self.project.find_by_id(object_id)
        if obj is None or not hasattr(obj, "appearance"):
            return
        targets = list(obj.children) if isinstance(obj, (WellFile, LayeredCube)) else [obj]
        previous = [(node, node.appearance) for node in (obj, *targets)]
        was_modified = self.project.modified

        def refresh():
            if "color_map" in changes and hasattr(self.viewer, "rebuild_palette_actors"):
                self.viewer.rebuild_palette_actors(targets)
                return
            if set(changes) <= {"label_visible", "label_color", "label_font", "label_size"} \
                    and hasattr(self.viewer, "update_well_labels"):
                self.viewer.update_well_labels(targets)
                return
            if hasattr(self.viewer, "update_object_appearances"):
                self.viewer.update_object_appearances(targets)
            else:
                for target in targets:
                    self.viewer.update_object_appearance(target)

        try:
            if self.project.set_appearance(obj, **changes):
                refresh()
        except Exception as error:
            for node, appearance in previous:
                node.appearance = appearance
            self.project.modified = was_modified
            try:
                refresh()
            except Exception:
                logger.exception("Не удалось восстановить отображение объекта")
            self._report_error("Не удалось изменить отображение", error)
        self.appearance_editor.set_object(obj)
        self.update_window_state()

    def _change_axis_scale(self, x, y, z):
        if self.project is None:
            return
        previous, was_modified = self.project.axis_scale, self.project.modified
        try:
            if self.project.set_axis_scale(x, y, z):
                self.viewer.set_axis_scale(self.project.axis_scale)
        except Exception as error:
            self.project.axis_scale = previous
            self.project.modified = was_modified
            try:
                self.viewer.set_axis_scale(previous)
            except Exception:
                logger.exception("Не удалось восстановить масштаб осей")
            self._report_error("Не удалось изменить масштаб осей", error)
        self.axis_scale_editor.set_project(self.project)
        self.update_window_state()

    def _open_palette(self, object_id):
        if self.project is None:
            return
        obj = self.project.find_by_id(object_id)
        if obj is None or not hasattr(obj, "appearance"):
            return
        from gui.dialogs.PaletteDialog import PaletteDialog
        from PyQt6.QtWidgets import QDialog
        try:
            dialog = PaletteDialog(obj, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._change_appearance(object_id, {"color_map": dialog.palette})
        except Exception as error:
            self._report_error("Не удалось открыть палитру", error)

    def add_work_subfolder(self, parent=None):
        if self.project is None:
            return
        parent = self.project.root if parent is None else parent
        name, ok = QInputDialog.getText(self, "Новая папка", "Имя папки:")
        if not ok or not name.strip():
            return
        try:
            self.project.add(Folder(Project._valid_name(name)), parent)
            self.update_project_tree()
            self.update_window_state()
        except Exception as error:
            self._report_error("Не удалось создать папку", error)

    def rename_object(self, obj=None):
        if self.project is None:
            return
        old_name = self.project.name if obj is None else obj.name
        name, ok = QInputDialog.getText(self, "Переименовать", "Новое имя:", text=old_name)
        if not ok:
            return
        try:
            if obj is None:
                self.project.rename_project(name)
            else:
                self.project.rename(obj, name)
            self.update_project_tree()
            self.update_window_state()
        except Exception as error:
            self._report_error("Не удалось переименовать", error)

    def delete_object(self, obj):
        reply = QMessageBox.question(
            self, "Удалить объект", f"Удалить «{obj.name}» и его содержимое из проекта?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.project.remove(obj)
            self.update_project_tree()
            self.update_3d_viewer()
            self.update_window_state()
        except Exception as error:
            self._report_error("Не удалось удалить объект", error)

    def show_import_dialog(self, destination_folder=None):
        if self.project is None:
            return
        dialog = ImportDialog(self)
        if not dialog.exec():
            return
        source_file = Path(dialog.lineEditPathFile.text())
        obj = dialog.import_object
        obj.metadata["source_name"] = source_file.name
        was_modified = self.project.modified
        try:
            self.project.import_file(obj, destination_folder)
            self.update_3d_viewer()
        except Exception as error:
            if self.project.find_by_id(obj.uuid) is not None:
                self.project.remove(obj)
                self.project.modified = was_modified
                self.update_3d_viewer()
            self._report_error("Не удалось импортировать объект", error)
            return
        self.update_project_tree()
        self.update_window_state()
        count = len(obj.wells) if isinstance(obj, WellFile) else (
            sum(layer.point_count for layer in obj.layers) if isinstance(obj, LayeredCube) else (
                len(obj.vertices) if isinstance(obj, Surface) else obj.point_count))
        self.statusbar.showMessage(f"Импортировано: {source_file.name}, элементов: {count}", 5000)
        self.select_object(obj.uuid)

    def confirm_unsaved_changes(self):
        if self.project is None or not self.project.has_unsaved_changes():
            return True
        reply = QMessageBox.warning(
            self, "Несохранённые изменения", f"Сохранить изменения в проекте «{self.project.name}»?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self.save_project()
        return reply == QMessageBox.StandardButton.Discard

    @staticmethod
    def _project_directory(parent, name):
        name = Project._valid_name(name)
        if name in (".", "..") or any(char in name for char in '<>:"/\\|?*') or name.endswith(".") or Path(name).is_reserved():
            raise ValueError("Имя проекта не подходит для имени папки.")
        return Path(parent) / name

    def new_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для нового проекта")
        if not folder:
            return False
        name, ok = QInputDialog.getText(self, "Создание проекта", "Имя проекта:")
        if not ok or not name.strip():
            return False
        try:
            path = self._project_directory(folder, name)
            Project._check_destination(path)
            if not self.confirm_unsaved_changes():
                return False
            self.set_project(Project.create(path, name))
        except Exception as error:
            self._report_error("Не удалось создать проект", error)
            return False
        self.statusbar.showMessage(f"Проект «{self.project.name}» создан.", 5000)
        return True

    def save_project(self):
        if self.project is None:
            return False
        if not self.project.is_saved:
            return self.save_project_as()
        try:
            self.project.save()
        except Exception as error:
            self._report_error("Не удалось сохранить проект", error)
            return False
        self._remember_project()
        self.update_window_state()
        self.statusbar.showMessage("Проект сохранён", 5000)
        return True

    def save_project_as(self):
        if self.project is None:
            return False
        folder = QFileDialog.getExistingDirectory(self, "Выберите новую или пустую папку для копии проекта")
        if not folder:
            return False
        try:
            self.project.save_as(folder)
        except Exception as error:
            self._report_error("Не удалось сохранить копию проекта", error)
            return False
        self._remember_project()
        self.update_window_state()
        self._show_properties()
        self.statusbar.showMessage("Копия проекта сохранена", 5000)
        return True

    def open_project(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Открыть проект", "", "Проект (project.json);;JSON (*.json)")
        if not filename:
            return False
        try:
            # Validate before asking to discard the current project.
            candidate = Project.open(filename)
            if not self.confirm_unsaved_changes():
                return False
            # Saving the currently open project may have updated this same file.
            if self.project is not None and self.project.project_file == Path(filename).resolve():
                candidate = Project.open(filename)
            self.set_project(candidate)
        except Exception as error:
            self._report_error("Не удалось открыть проект", error)
            return False
        self.statusbar.showMessage(f"Проект «{self.project.name}» открыт.", 5000)
        return True

    def close_project(self):
        if not self.confirm_unsaved_changes():
            return False
        self.set_project(None)
        self.statusbar.showMessage("Проект закрыт", 5000)
        return True

    def closeEvent(self, event):
        if not self.confirm_unsaved_changes():
            event.ignore()
            return
        self._remember_project()
        self.viewer.close()
        event.accept()
