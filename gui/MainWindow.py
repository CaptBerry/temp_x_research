import logging
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import Qt, QSettings, QSignalBlocker, QModelIndex, QSize
from PyQt6.QtGui import QAction, QKeySequence, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow, QVBoxLayout, QFileDialog, QMessageBox, QInputDialog, QScrollArea, QFrame, QPushButton, QTabWidget, QProgressBar, QLabel

from gui.Viewer3D import Viewer3D
from gui.GridBuildWorker import GridBuildWorker
from gui.dialogs.ImportDialog import ImportDialog
from gui.dialogs.AxisSettingsDialog import AxisSettingsDialog
from gui.dialogs.ClippingDialog import ClippingDialog
from gui.dialogs.ThemeDialog import ThemeDialog
from gui.dialogs.EDADialog import EDADialog
from gui.theme import THEMES, apply_theme
from gui.type_icons import object_icon_key, type_icon
from gui.CanvasEditor import CanvasEditor
from gui.ResearchWorkspace import ResearchWorkspace
from gui.dialogs.CalculationDialog import CalculationDialog
from models.CalculationArtifact import CalculationArtifact, TrainingSet, CatalogWell
from gui.custom_widgets.projectTreeView import ProjectTreeView
from gui.custom_widgets.AppearanceEditor import AppearanceEditor
from models.project.Project import Project
from models.project.Folder import Folder
from models.PointCloud import PointCloud
from models.Well import Well
from models.WellFile import WellFile
from models.DataCube import DataCube
from models.LayeredCube import LayeredCube
from models.DisplayPoints import DisplayPoints, LayeredDisplayPoints
from models.Surface import Surface

logger = logging.getLogger(__name__)
GRID_BACKGROUND_LAYERS = 8
GRID_BACKGROUND_POINTS = 50_000


class MainWindow(QMainWindow):
    PROJECT_ID = "__project__"

    def __init__(self, *, settings=None, restore_session=True):
        super().__init__()
        uic.loadUi(Path(__file__).with_name("MainWindow.ui"), self)
        self.project = None
        self._eda_dialogs = {}
        self._clip_dialog = None
        self._grid_worker = None
        self._grid_job = None
        self._pending_project_grid = None
        self._grid_cancelled = False
        self._close_after_grid = False
        self.settings = settings if settings is not None else QSettings("AVPD", "XSearch")
        self.replace_tree_view()
        layout = QVBoxLayout(self.viewerWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas_editor = CanvasEditor(self)
        self.workspace_tabs = ResearchWorkspace(Viewer3D, self.canvas_editor, self.settings, self)
        self.viewer = self.workspace_tabs.viewer
        layout.addWidget(self.workspace_tabs)
        self.workspace_tabs.currentChanged.connect(lambda index: self.PropertiesPanel.setVisible(index == 0))
        self.canvas_editor.changed.connect(self.update_window_state)
        self.canvas_editor.busyChanged.connect(self._canvas_busy_changed)
        self.canvas_editor.resultsChanged.connect(self._canvas_results_changed)
        self.canvas_editor.objectRequested.connect(self._open_canvas_object)
        self.canvas_editor.visibilityRequested.connect(self.show_object_in_3d)
        self.canvas_editor.edaRequested.connect(lambda identifier: self.open_eda(self.project.find_by_id(identifier)))
        self.canvas_editor.artifactRequested.connect(self.open_calculation)
        self.canvas_editor.dataRequested.connect(self.open_data)
        self.canvas_editor.chartRequested.connect(self.open_chart)
        saved_theme = self.settings.value("theme", "light", type=str)
        self.set_theme(saved_theme if saved_theme in THEMES else "light", save=False)
        self.appearance_editor = AppearanceEditor(self)
        self.axis_settings_button = QPushButton("Настройка осей…", self)
        self.axis_settings_button.clicked.connect(self._open_axis_settings)
        self.propertyTree.setMaximumHeight(250)
        self.PropertiesPanel.layout().addWidget(self.axis_settings_button)
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
        self.appearance_editor.displayGridChanged.connect(self._change_display_grid)
        self.grid_progress_label = QLabel("Построение сетки", self)
        self.grid_progress = QProgressBar(self)
        self.grid_progress.setFixedWidth(140)
        self.grid_cancel_button = QPushButton("Отменить", self)
        self.grid_cancel_button.clicked.connect(self._cancel_grid_build)
        for widget in (self.grid_progress_label, self.grid_progress, self.grid_cancel_button):
            self.statusbar.addPermanentWidget(widget)
            widget.hide()
        self._connect_actions()
        self.PropertiesPanel.setVisible(self.workspace_tabs.currentIndex() == 0)
        self.viewer.clippingMoved.connect(self._clipping_moved)
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
        self.action_axes = QAction("Настройка осей…", self)
        self.action_axes.triggered.connect(self._open_axis_settings)
        self.menuView.addAction(self.action_axes)
        self.menu_clip = self.menuView.addMenu("Отсечь объекты")
        self.action_clip_enabled = QAction("Показать плоскость и отсечь", self)
        self.action_clip_enabled.setCheckable(True)
        self.action_clip_enabled.toggled.connect(self._toggle_clipping)
        self.menu_clip.addAction(self.action_clip_enabled)
        self.action_clip_settings = QAction("Настроить плоскость…", self)
        self.action_clip_settings.triggered.connect(self._open_clipping_dialog)
        self.menu_clip.addAction(self.action_clip_settings)
        self.action_canvas = QAction("Canvas расчётов", self)
        self.action_canvas.triggered.connect(lambda: self.workspace_tabs.setCurrentIndex(1))
        self.menuView.addAction(self.action_canvas)

    def set_theme(self, theme, *, save=True):
        background = apply_theme(QApplication.instance(), theme)
        self.viewer.set_theme(background)
        self.canvas_editor.set_theme(theme)
        self.theme = theme
        if hasattr(self, "appearance_editor"):
            self.update_project_tree()
        if save:
            self.settings.setValue("theme", theme)
            self.settings.sync()

    def _open_theme_dialog(self):
        dialog = ThemeDialog(self.theme, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_theme(dialog.selected_theme)

    def open_eda(self, obj):
        try:
            dialog = EDADialog(obj, self)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            key = id(dialog)
            self._eda_dialogs[key] = dialog
            dialog.destroyed.connect(lambda _=None, key=key, dialogs=self._eda_dialogs: dialogs.pop(key, None))
            dialog.show()
        except Exception as error:
            self._report_error("Не удалось открыть EDA", error)

    def replace_tree_view(self):
        old_tree = self.projectTree
        self.projectTree = ProjectTreeView(self)
        self.projectTree.setIconSize(QSize(21, 21))
        old_tree.parent().layout().replaceWidget(old_tree, self.projectTree)
        old_tree.deleteLater()

    def _canvas_busy_changed(self, busy):
        self.projectTree.setEnabled(not busy)
        self.menu.setEnabled(not busy)
        for dialog in self._eda_dialogs.values():
            dialog.setEnabled(not busy)
        self.update_window_state()

    def _canvas_results_changed(self):
        self.update_project_tree()
        self._sync_visibility((self.project.root,))
        self.update_window_state()

    def _open_canvas_object(self, identifier):
        self.show_object_in_3d(identifier, "focus")

    def show_object_in_3d(self, identifier, action="show"):
        obj = self.project.find_by_id(identifier) if self.project else None
        if obj is None:
            return
        if isinstance(obj, CalculationArtifact) and not isinstance(obj, TrainingSet):
            self.open_calculation(obj)
            return
        if action == "hide":
            self.project.set_visible(obj, False)
        else:
            if obj.metadata.get("prediction"):
                source = self.project.find_by_id(obj.metadata.get("source_uuid"))
                if source is not None and source is not obj:
                    self.project.set_visible(source, False)
            current = obj
            while current is not None:
                self.project.set_visible(current, True)
                current = current.parent
            if isinstance(obj, Folder):
                self.project.set_subtree_visible(obj, True)
        self._sync_visibility((self.project.root,))
        self.update_project_tree()
        self.select_object(obj.uuid)
        self.update_window_state()
        if action != "hide":
            self.workspace_tabs.show_3d()
            if action == "focus" and hasattr(self.viewer, "focus_on_object"):
                self.viewer.focus_on_object(obj)

    def open_calculation(self, artifact):
        dialog = CalculationDialog(artifact, self)
        dialog.set_context(self.project)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        key = id(dialog)
        self._eda_dialogs[key] = dialog
        dialog.destroyed.connect(lambda _=None, key=key, dialogs=self._eda_dialogs: dialogs.pop(key, None))
        dialog.sampleSelected.connect(self._highlight_canvas_sample)
        dialog.catalogChanged.connect(self._catalog_selection_changed)
        dialog.sample3DRequested.connect(self.open_sample_explorer)
        dialog.catalog3DRequested.connect(lambda dataset: self.show_object_in_3d(dataset.uuid, "focus"))
        dialog.chartRequested.connect(self.open_chart)
        dialog.show()

    def open_data(self, identifier):
        from models.inspection import inspection_artifact
        obj = self.project.find_by_id(identifier) if self.project else None
        if obj is not None:
            self.open_calculation(inspection_artifact(obj))

    def open_chart(self, obj):
        from gui.dialogs.MiniChartDialog import MiniChartDialog
        from models.pipeline import node_result
        if isinstance(obj, str):
            obj = self.project.find_by_id(obj) or node_result(self.project, obj)
        if obj is None:
            self.statusbar.showMessage("Сначала рассчитайте выбранный шаг.", 5000)
            return
        dialog = MiniChartDialog(obj, self)
        self._track_analysis_dialog(dialog)

    def _track_analysis_dialog(self, dialog):
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        key = id(dialog)
        self._eda_dialogs[key] = dialog
        dialog.destroyed.connect(lambda _=None, key=key, dialogs=self._eda_dialogs: dialogs.pop(key, None))
        dialog.show()

    def open_sample_explorer(self, dataset, row):
        from gui.dialogs.SampleExplorer import SampleExplorer
        from models.inspection import replay_fingerprint
        content_fingerprint = replay_fingerprint(dataset)
        prediction = next((obj for obj in reversed(list(self.project.walk()))
                           if obj.metadata.get("prediction") and obj.metadata.get("source_uuid") == dataset.payload["cube_uuid"]
                           and obj.metadata.get("dataset_fingerprint") == content_fingerprint
                           and obj.metadata.get("source_fingerprint") == dataset.payload["cube_fingerprint"]), None)
        dialog = SampleExplorer(dataset, row, prediction, self)
        dialog.sampleSelected.connect(self._highlight_canvas_sample)
        self._track_analysis_dialog(dialog)

    def _catalog_selection_changed(self, artifact):
        self.project.mark_modified()
        visible_wells = [well for well in artifact.children
                         if well.uuid in getattr(self.viewer, "_catalog_actors", {})]
        if visible_wells:
            self.viewer.remove_objects(visible_wells)
            if self.project.is_visible(artifact):
                self.viewer.sync_object_visibility(self.project, (artifact,))
        self.canvas_editor.refresh_states()
        self.update_window_state()

    def _highlight_canvas_sample(self, artifact, row):
        frame = artifact.catalog if isinstance(artifact, TrainingSet) else artifact.tables.get("samples", artifact.tables.get("predictions"))
        if frame is None or not 0 <= row < len(frame):
            return
        sample = frame.iloc[row]
        dataset = artifact if isinstance(artifact, TrainingSet) else self.project.find_by_id(artifact.payload.get("dataset_uuid"))
        dataset_row = row
        if isinstance(dataset, TrainingSet) and not isinstance(artifact, TrainingSet):
            matches = dataset.catalog.index[dataset.catalog.sample_id == sample.sample_id]
            dataset_row = int(matches[0]) if len(matches) else -1
        self.workspace_tabs.show_3d()
        if hasattr(self.viewer, "highlight_sample"):
            cube = self.project.find_by_id(artifact.payload.get("cube_uuid")) if self.project else None
            if cube is not None:
                from models.pipeline import fingerprint
                if fingerprint(cube) != artifact.payload.get("cube_fingerprint"):
                    cube = None
            well = self.project.find_by_id(sample.well_uuid)
            for obj in (cube, well):
                if obj is not None and not self.project.is_visible(obj):
                    self.show_object_in_3d(obj.uuid)
            coordinates = (dataset.arrays["neighbor_coordinates"][dataset_row].reshape(-1, 3)
                           if isinstance(dataset, TrainingSet) and dataset_row >= 0 and "neighbor_coordinates" in dataset.arrays else None)
            self.viewer.highlight_sample(sample, cube, artifact.payload.get("patch_shape", [1, 1, 1]), coordinates)
            if well is None and isinstance(dataset, TrainingSet) and hasattr(self.viewer, "highlight_catalog_well"):
                self.viewer.highlight_catalog_well(dataset.catalog[dataset.catalog.well_uuid == sample.well_uuid])

    def update_window_state(self):
        active = self.project is not None
        for action in (self.action_save_project, self.action_save_as_project,
                       self.action_close_project, self.actionImportXYZ,
                       self.action_axes, self.axis_settings_button):
            action.setEnabled(active)
        self.menu_clip.setEnabled(active)
        self.action_canvas.setEnabled(active)
        with QSignalBlocker(self.action_clip_enabled):
            self.action_clip_enabled.setChecked(active and self.project.clip_enabled)
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
        if self.canvas_editor.busy:
            raise RuntimeError("Дождитесь завершения расчёта или нажмите «Остановить» в Canvas.")
        if self._grid_worker is not None:
            self._cancel_grid_build()
        self._pending_project_grid = None
        deferred = self._project_grid_candidates(project)
        # Load/render the candidate before replacing the current project.
        previous = self.project
        try:
            self._render_project(project, deferred=deferred)
        except Exception:
            self._render_project(previous)
            raise
        self.project = project
        self.canvas_editor.set_project(project)
        for dialog in list(self._eda_dialogs.values()):
            dialog.close()
        if self._clip_dialog is not None:
            self._clip_dialog.close()
            self._clip_dialog = None
        self.update_project_tree()
        self.update_window_state()
        self._remember_project()
        if deferred:
            if self._grid_worker is not None:
                self._pending_project_grid = (project, deferred)
            else:
                self._start_project_grid(project, deferred)

    def _project_grid_candidates(self, project):
        if project is None or not hasattr(self.viewer, "replace_source_meshes"):
            return []
        objects = [obj for obj in project.walk() if isinstance(obj, DisplayPoints)
                   and obj.appearance.mode in ("corner_grid", "grid_wireframe")
                   and project.is_visible(obj)]
        if (len(objects) < GRID_BACKGROUND_LAYERS and
                sum(obj.point_count for obj in objects) < GRID_BACKGROUND_POINTS):
            return []
        return objects

    def _render_project(self, project, *, deferred=()):
        deferred_ids = {obj.uuid for obj in deferred}
        with self.viewer.scene_update():
            self.viewer.clear_scene()
            self.viewer.set_axis_scale(project.axis_scale if project is not None else (1, 1, 1))
            self.viewer.set_axes_display(project.axes_visible if project is not None else True,
                                         project.axes_grid_visible if project is not None else False)
            self.viewer.set_axes_format(project.axes_label_decimals if project is not None else 2,
                                        project.axes_round_grid if project is not None else False)
            if project is not None:
                for obj in project.walk():
                    if project.is_visible(obj):
                        if obj.uuid in deferred_ids:
                            self.viewer.add_point_cloud(obj, force_points=True)
                        else:
                            self.viewer.add_object(obj)
                self.viewer.update_coordinate_axes()
                self.viewer.focus_on_scene()
                self.viewer.set_clipping_settings(
                    project.clip_enabled, project.clip_origin,
                    project.clip_rotation, project.clip_invert)

    def _clip_scene_center(self):
        bounds = self.viewer.scene_bounds
        if bounds is None:
            return (0.0, 0.0, 0.0)
        return tuple((bounds[2 * axis] + bounds[2 * axis + 1]) /
                     (2 * self.project.axis_scale[axis]) for axis in range(3))

    def _toggle_clipping(self, enabled):
        if self.project is None:
            return
        project = self.project
        previous = (project.clip_enabled, project.clip_origin, project.clip_rotation,
                    project.clip_invert, project.clip_initialized, project.modified)
        try:
            origin = self._clip_scene_center() if enabled and not project.clip_initialized else project.clip_origin
            project.set_clipping(enabled, origin, project.clip_rotation, project.clip_invert)
            self.viewer.set_clipping_settings(enabled, project.clip_origin,
                                              project.clip_rotation, project.clip_invert)
            if enabled:
                self._open_clipping_dialog()
            elif self._clip_dialog is not None:
                self._clip_dialog.close()
        except Exception as error:
            (project.clip_enabled, project.clip_origin, project.clip_rotation,
             project.clip_invert, project.clip_initialized, project.modified) = previous
            try:
                self.viewer.set_clipping_settings(*previous[:4])
            except Exception:
                logger.exception("Не удалось восстановить отсечение")
            with QSignalBlocker(self.action_clip_enabled):
                self.action_clip_enabled.setChecked(project.clip_enabled)
            self._report_error("Не удалось применить отсечение", error)
        self.update_window_state()

    def _open_clipping_dialog(self):
        if self.project is None:
            return
        if not self.project.clip_enabled:
            self.action_clip_enabled.setChecked(True)
            return
        if self._clip_dialog is None:
            bounds = self.viewer.scene_bounds
            spans = [(bounds[2 * i + 1] - bounds[2 * i]) for i in range(3)] if bounds else [1]
            step = max(max(spans) / 20, 0.000001)
            dialog = ClippingDialog(self.project, step, self)
            dialog.settingsChanged.connect(self._apply_clipping_from_dialog)
            dialog.finished.connect(lambda _result: setattr(self, "_clip_dialog", None))
            self._clip_dialog = dialog
        self._clip_dialog.show()
        self._clip_dialog.raise_()
        self._clip_dialog.activateWindow()

    def _apply_clipping_from_dialog(self, origin, rotation, invert, *, from_widget=False):
        if self.project is None:
            return
        previous = (self.project.clip_enabled, self.project.clip_origin,
                    self.project.clip_rotation, self.project.clip_invert,
                    self.project.clip_initialized, self.project.modified)
        try:
            if self.project.set_clipping(True, origin, rotation, invert):
                self.viewer.set_clipping_settings(True, origin, rotation, invert,
                                                  sync_widget=not from_widget)
        except Exception as error:
            (self.project.clip_enabled, self.project.clip_origin,
             self.project.clip_rotation, self.project.clip_invert,
             self.project.clip_initialized, self.project.modified) = previous
            if self._clip_dialog is not None:
                self._clip_dialog.set_settings(previous[1], previous[2], previous[3])
            self._report_error("Не удалось изменить плоскость", error)
        self.update_window_state()

    def _clipping_moved(self, origin, rotation):
        if self.project is None or not self.project.clip_enabled:
            return
        self._apply_clipping_from_dialog(origin, rotation, self.project.clip_invert,
                                         from_widget=True)
        if self._clip_dialog is not None:
            self._clip_dialog.set_settings(self.project.clip_origin,
                                           self.project.clip_rotation,
                                           self.project.clip_invert)

    def update_3d_viewer(self):
        self._render_project(self.project)

    def _sync_visibility(self, roots):
        if hasattr(self.viewer, "sync_object_visibility"):
            self.viewer.sync_object_visibility(self.project, roots)
        else:
            self.update_3d_viewer()

    def set_container_visibility(self, container, visible):
        if self.project is None:
            return
        previous = [(node, node.visible) for node in self.project.walk(container)]
        was_modified = self.project.modified
        try:
            if self.project.set_subtree_visible(container, visible):
                self._sync_visibility((container,))
                self.update_project_tree()
                self.update_window_state()
        except Exception as error:
            for node, old_visibility in previous:
                node.visible = old_visibility
            self.project.modified = was_modified
            try:
                self._sync_visibility((container,))
            except Exception:
                logger.exception("Не удалось восстановить видимость контейнера")
            self.update_project_tree()
            self.update_window_state()
            self._report_error("Не удалось изменить видимость контейнера", error)

    def update_project_tree(self):
        selected = self.projectTree.get_item_from_index(self.projectTree.currentIndex())
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected is not None else None
        previous_model = self.projectTree.model()
        same_project = getattr(self, "_tree_project", None) is self.project
        expanded_ids = set()
        if same_project and previous_model is not None:
            def remember_expanded(parent):
                for row in range(previous_model.rowCount(parent)):
                    index = previous_model.index(row, 0, parent)
                    if self.projectTree.isExpanded(index):
                        expanded_ids.add(index.data(Qt.ItemDataRole.UserRole))
                    remember_expanded(index)
            remember_expanded(QModelIndex())
        scroll_position = self.projectTree.verticalScrollBar().value() if same_project else 0
        model = QStandardItemModel(self.projectTree)
        model.setHorizontalHeaderLabels(["Проект"])
        if self.project is not None:
            item = QStandardItem(self.project.name)
            item.setIcon(type_icon("folder", self.theme == "dark"))
            item.setData(self.PROJECT_ID, Qt.ItemDataRole.UserRole)
            model.appendRow(item)
            self._build_tree(self.project.root, item)
        self.projectTree.setModel(model)
        self._tree_project = self.project
        model.itemChanged.connect(self._tree_item_changed)
        self.projectTree.selectionModel().currentChanged.connect(self._show_properties)
        if same_project:
            def restore_expanded(parent):
                for row in range(model.rowCount(parent)):
                    index = model.index(row, 0, parent)
                    if index.data(Qt.ItemDataRole.UserRole) in expanded_ids:
                        self.projectTree.expand(index)
                    restore_expanded(index)
            restore_expanded(QModelIndex())
        else:
            self.projectTree.expandAll()
        if selected_id is not None:
            self.select_object(selected_id)
        self.projectTree.verticalScrollBar().setValue(scroll_position)
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
        item.setIcon(type_icon(object_icon_key(obj), self.theme == "dark"))
        if isinstance(obj, CatalogWell):
            item.setEditable(False)
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
                if not isinstance(obj, CatalogWell):
                    self.project.rename(obj, item.text())
                visible = item.checkState() == Qt.CheckState.Checked
                if obj.visible != visible:
                    old_visibility, was_modified = obj.visible, self.project.modified
                    try:
                        self.project.set_visible(obj, visible)
                        self._sync_visibility((obj,))
                    except Exception:
                        obj.visible = old_visibility
                        self.project.modified = was_modified
                        self._sync_visibility((obj,))
                        raise
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
                             "display_points": "Точки с сеткой отображения",
                             "layered_display_points": "Слои точек с сеткой отображения",
                             "well": "Скважина", "wellfile": "Файл скважин",
                             "cube": "Куб данных", "layered_cube": "Послойный куб",
                             "surface": "Поверхность", "training_set": "Каталог образцов",
                             "catalog_well": "Скважина каталога",
                             "calculation": "Результат расчёта"}.get(obj.TYPE, obj.TYPE)
                values.update({"Имя": obj.name, "Тип": type_name, "UUID": obj.uuid})
                if isinstance(obj, CalculationArtifact):
                    values.update({"Расчёт": obj.kind, "Итог": obj.payload.get("summary", "")})
                if isinstance(obj, CatalogWell):
                    rows = obj.parent.catalog.well_uuid.astype(str).eq(obj.well_uuid)
                    selected = obj.parent.catalog.loc[rows]
                    values.update({"ID скважины": selected.well_id.iloc[0],
                                   "Образцов": len(selected),
                                   "Готовых": int(selected.status.eq("готов").sum())})
                if isinstance(obj, PointCloud):
                    values.update({"Строк": obj.point_count, "X": obj.x_column,
                                   "Y": obj.y_column, "Z": obj.z_column,
                                   "Параметры": ", ".join(map(str, obj.parameters))})
                if isinstance(obj, DisplayPoints):
                    values["Геометрия"] = "Исходные точки; сетка вычисляется для отображения"
                    if "layer_name" in obj.metadata:
                        values["Слой"] = obj.metadata["layer_name"]
                if isinstance(obj, LayeredDisplayPoints):
                    values.update({"Слоёв": len(obj.layers), "Колонка слоя": obj.layer_column,
                                   "Точек": sum(layer.point_count for layer in obj.layers)})
                if isinstance(obj, Well):
                    values.update({"ID скважины": obj.well_id,
                                   "Длина траектории": f"{obj.trajectory_length:.3f}"})
                elif isinstance(obj, DataCube):
                    if "layer_index" in obj.metadata:
                        values["Индекс слоя"] = obj.metadata["layer_index"]
                        values["Название слоя"] = obj.metadata.get("layer_name", obj.name)
                        if "median_height" in obj.metadata:
                            values["Медианная абсолютная высота"] = f'{obj.metadata["median_height"]:.3f}'
                            values["Диапазон абсолютной высоты"] = (
                                f'{obj.metadata["height_min"]:.3f}…'
                                f'{obj.metadata["height_max"]:.3f}')
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
                                   "Слои сверху вниз": ", ".join(
                                       f'{layer.metadata["layer_index"]}: '
                                       f'{layer.metadata.get("layer_name", layer.name)}'
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
        targets = list(obj.children) if isinstance(obj, (WellFile, LayeredCube, LayeredDisplayPoints)) else [obj]
        previous = [(node, node.appearance) for node in (obj, *targets)]
        was_modified = self.project.modified
        geometry_change = "mode" in changes and any(
            before.mode != changes["mode"] and (
                isinstance(node, DisplayPoints) or "cells" in (before.mode, changes["mode"]))
            for node, before in previous if node in targets)

        def restore_appearance():
            for node, appearance in previous:
                node.appearance = appearance

        def refresh():
            if geometry_change \
                    and hasattr(self.viewer, "rebuild_geometry_actors"):
                if self._start_background_grid(targets, restore_appearance, was_modified):
                    return
                self.viewer.rebuild_geometry_actors(targets)
                return
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

    def _change_display_grid(self, object_id, changes):
        if self.project is None:
            return
        obj = self.project.find_by_id(object_id)
        if not isinstance(obj, (DisplayPoints, LayeredDisplayPoints)):
            return
        targets = list(obj.layers) if isinstance(obj, LayeredDisplayPoints) else [obj]
        nodes = [obj, *targets] if isinstance(obj, LayeredDisplayPoints) else [obj]
        previous = [(node, node.display_grid, node.appearance) for node in nodes]
        was_modified = self.project.modified

        def restore_settings():
            for node, settings, appearance in previous:
                node.display_grid, node.appearance = settings, appearance

        try:
            self.project.set_display_grid(obj, **changes)
            if set(changes) != {"z_direction"} and obj.appearance.mode not in ("corner_grid", "grid_wireframe"):
                self.project.set_appearance(obj, mode="corner_grid")
            if set(changes) == {"z_direction"} and hasattr(self.viewer, "update_object_transforms"):
                self.viewer.update_object_transforms(targets)
            elif not self._start_background_grid(targets, restore_settings, was_modified):
                self.viewer.rebuild_geometry_actors(targets)
        except Exception as error:
            restore_settings()
            self.project.modified = was_modified
            try:
                self.viewer.rebuild_geometry_actors(targets)
            except Exception:
                logger.exception("Не удалось восстановить сетку отображения")
            self._report_error("Не удалось перестроить сетку отображения", error)
        self.appearance_editor.set_object(obj)
        self.update_window_state()

    def _start_background_grid(self, targets, rollback, was_modified):
        if not hasattr(self.viewer, "replace_source_meshes"):
            return False
        objects = [obj for obj in targets if isinstance(obj, DisplayPoints)
                   and obj.appearance.mode in ("corner_grid", "grid_wireframe")
                   and obj.uuid in self.viewer._source_meshes]
        if (len(objects) < GRID_BACKGROUND_LAYERS and
                sum(obj.point_count for obj in objects) < GRID_BACKGROUND_POINTS):
            return False
        if self._grid_worker is not None:
            raise RuntimeError("Дождитесь завершения текущего построения сетки или отмените его.")
        worker = GridBuildWorker(objects, self)
        self._grid_worker = worker
        self._grid_cancelled = False
        self._grid_job = {"project": self.project, "rollback": rollback,
                          "was_modified": was_modified, "serial": self.project._change_serial,
                          "targets": tuple(targets),
                          "source_ids": set(self.viewer._source_meshes)}
        self.appearance_editor.setEnabled(False)
        self.grid_progress.setRange(0, len(objects))
        self.grid_progress.setValue(0)
        self.grid_progress.setFormat("%v / %m")
        self.grid_progress_label.setText("Построение сетки")
        self.grid_cancel_button.setEnabled(True)
        for widget in (self.grid_progress_label, self.grid_progress, self.grid_cancel_button):
            widget.show()
        worker.progress.connect(self.grid_progress.setValue)
        worker.finished.connect(self._finish_grid_build)
        worker.start()
        return True

    def _start_project_grid(self, project, targets):
        def restore_points():
            changed = False
            parents = set()
            for obj in targets:
                if project.find_by_id(obj.uuid) is obj and obj.appearance.mode in ("corner_grid", "grid_wireframe"):
                    obj.appearance = obj.appearance.updated(obj.TYPE, mode="points")
                    if isinstance(obj.parent, LayeredDisplayPoints):
                        parents.add(obj.parent)
                    changed = True
            for parent in parents:
                if parent.appearance.mode in ("corner_grid", "grid_wireframe"):
                    parent.appearance = parent.appearance.updated(parent.TYPE, mode="points")
            if changed:
                project.mark_modified()
        self._start_background_grid(targets, restore_points, project.modified)

    def _cancel_grid_build(self):
        if self._grid_worker is not None:
            self._grid_cancelled = True
            self._grid_worker.requestInterruption()
            self.grid_cancel_button.setEnabled(False)
            self.grid_progress_label.setText("Остановка построения…")

    def _rollback_grid_job(self, job):
        job["rollback"]()
        # A previously unseen layer may have been made visible while the
        # worker was running. Its actor was built with the pending settings.
        newly_visible = [obj for obj in job["targets"]
                         if self.project.find_by_id(obj.uuid) is obj
                         and obj.uuid not in job["source_ids"]
                         and obj.uuid in self.viewer._source_meshes]
        failures = []
        for obj in newly_visible:
            try:
                self.viewer.rebuild_geometry_actors([obj])
            except Exception as failure:
                logger.exception("Не удалось восстановить отображение слоя после отмены")
                failures.append(failure)
                # Do not leave geometry built with the cancelled settings on
                # screen. The source points remain available as a fallback.
                obj.appearance = obj.appearance.updated(obj.TYPE, mode="points")
                self.project.mark_modified()
                try:
                    self.viewer.rebuild_geometry_actors([obj])
                except Exception:
                    logger.exception("Не удалось восстановить даже отображение точек")
                    self.viewer.remove_objects([obj])
        if failures:
            raise RuntimeError("Не удалось восстановить отображение одного или нескольких слоёв; "
                               "они переключены на точки.") from failures[0]

    def _finish_grid_build(self):
        worker, job = self._grid_worker, self._grid_job
        if worker is None or job is None:
            return
        self._grid_worker = self._grid_job = None
        for widget in (self.grid_progress_label, self.grid_progress, self.grid_cancel_button):
            widget.hide()
        self.appearance_editor.setEnabled(True)
        same_project = self.project is job["project"]
        error = worker.error
        rollback_error = None
        if same_project and not self._grid_cancelled and error is None:
            valid = [(obj, mesh) for obj, settings, mesh in worker.result
                     if self.project.find_by_id(obj.uuid) is obj
                     and obj.display_grid == settings
                     and obj.appearance.mode in ("corner_grid", "grid_wireframe")]
            old_sources = [(obj, self.viewer._source_meshes[obj.uuid]) for obj, _ in valid
                           if obj.uuid in self.viewer._source_meshes]
            try:
                self.viewer.replace_source_meshes(valid)
            except Exception as failure:
                error = failure
                try:
                    self._rollback_grid_job(job)
                except Exception as failure:
                    rollback_error = failure
                try:
                    self.viewer.replace_source_meshes(old_sources)
                except Exception:
                    logger.exception("Не удалось восстановить сетки после ошибки отображения")
        elif same_project:
            try:
                self._rollback_grid_job(job)
            except Exception as failure:
                rollback_error = failure
        if same_project and (self._grid_cancelled or error is not None or rollback_error is not None):
            if self.project._change_serial == job["serial"]:
                self.project.modified = job["was_modified"]
            else:
                self.project.modified = True
            self._show_properties()
            self.update_window_state()
        if same_project and rollback_error is not None:
            self._report_error("Не удалось полностью восстановить отображение", rollback_error)
        elif same_project and error is not None and not self._grid_cancelled:
            self._report_error("Не удалось построить сетку", error)
        elif same_project and self._grid_cancelled:
            self.statusbar.showMessage("Построение сетки отменено.", 5000)
        elif same_project:
            self.statusbar.showMessage("Построение сетки завершено.", 5000)
        worker.deleteLater()
        if self._close_after_grid:
            self._close_after_grid = False
            if self.close():
                self._pending_project_grid = None
                return
        if self._pending_project_grid is not None:
            pending_project, pending_targets = self._pending_project_grid
            self._pending_project_grid = None
            if self.project is pending_project:
                self._start_project_grid(pending_project, pending_targets)

    def _change_axis_scale(self, x, y, z):
        if self.project is None:
            return
        previous, was_modified = self.project.axis_scale, self.project.modified
        try:
            if self.project.set_axis_scale(x, y, z):
                self.viewer.set_axis_scale(self.project.axis_scale)
                if self._clip_dialog is not None:
                    self._clip_dialog.set_axis_scale(self.project.axis_scale)
        except Exception as error:
            self.project.axis_scale = previous
            self.project.modified = was_modified
            try:
                self.viewer.set_axis_scale(previous)
                if self._clip_dialog is not None:
                    self._clip_dialog.set_axis_scale(previous)
            except Exception:
                logger.exception("Не удалось восстановить масштаб осей")
            self._report_error("Не удалось изменить масштаб осей", error)
        self.update_window_state()

    def _open_axis_settings(self):
        if self.project is None:
            return
        dialog = AxisSettingsDialog(self.project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        previous = (self.project.axis_scale, self.project.axes_visible,
                    self.project.axes_grid_visible, self.project.axes_label_decimals,
                    self.project.axes_round_grid, self.project.modified)
        try:
            if self.project.set_axes_settings(dialog.axis_scale,
                                              dialog.axes_check.isChecked(),
                                              dialog.grid_check.isChecked(),
                                              label_decimals=dialog.decimals_spin.value(),
                                              round_grid=dialog.round_grid_check.isChecked()):
                with self.viewer.scene_update():
                    self.viewer.set_axis_scale(self.project.axis_scale)
                    self.viewer.set_axes_display(self.project.axes_visible,
                                                 self.project.axes_grid_visible)
                    self.viewer.set_axes_format(self.project.axes_label_decimals,
                                                self.project.axes_round_grid)
                if self._clip_dialog is not None:
                    self._clip_dialog.set_axis_scale(self.project.axis_scale)
        except Exception as error:
            (self.project.axis_scale, self.project.axes_visible,
             self.project.axes_grid_visible, self.project.axes_label_decimals,
             self.project.axes_round_grid, self.project.modified) = previous
            try:
                with self.viewer.scene_update():
                    self.viewer.set_axis_scale(previous[0])
                    self.viewer.set_axes_display(previous[1], previous[2])
                    self.viewer.set_axes_format(previous[3], previous[4])
                if self._clip_dialog is not None:
                    self._clip_dialog.set_axis_scale(previous[0])
            except Exception:
                logger.exception("Не удалось восстановить настройки осей")
            self._report_error("Не удалось изменить настройки осей", error)
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
            removed = list(self.project.walk(obj))
            self.project.remove(obj)
            self.update_project_tree()
            if hasattr(self.viewer, "remove_objects"):
                self.viewer.remove_objects(removed)
            else:
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
            self._sync_visibility((obj,))
        except Exception as error:
            if self.project.find_by_id(obj.uuid) is not None:
                self.project.remove(obj)
                self.project.modified = was_modified
                if hasattr(self.viewer, "remove_objects"):
                    self.viewer.remove_objects(list(self.project.walk(obj)))
                else:
                    self.update_3d_viewer()
            self._report_error("Не удалось импортировать объект", error)
            return
        self.update_project_tree()
        self.update_window_state()
        count = len(obj.wells) if isinstance(obj, WellFile) else (
            sum(layer.point_count for layer in obj.layers) if isinstance(obj, (LayeredCube, LayeredDisplayPoints)) else (
                len(obj.vertices) if isinstance(obj, Surface) else obj.point_count))
        self.statusbar.showMessage(f"Импортировано: {source_file.name}, элементов: {count}", 5000)
        self.select_object(obj.uuid)

    def confirm_unsaved_changes(self):
        if self.canvas_editor.busy:
            self.statusbar.showMessage("Расчёт выполняется. Нажмите «Остановить» в Canvas перед закрытием проекта.", 7000)
            return False
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
        if self._grid_worker is not None:
            self._close_after_grid = True
            self._cancel_grid_build()
            event.ignore()
            return
        if not self.confirm_unsaved_changes():
            event.ignore()
            return
        self._remember_project()
        self.workspace_tabs.shutdown()
        for dialog in list(self._eda_dialogs.values()):
            dialog.close()
        if self._clip_dialog is not None:
            self._clip_dialog.close()
        self.viewer.close()
        event.accept()
