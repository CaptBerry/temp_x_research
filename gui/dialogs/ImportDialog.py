from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QFileDialog, QPushButton, QLineEdit, QTableView, QComboBox, QListWidget, QCheckBox, QMessageBox, QWidget, QHBoxLayout, QLabel, QSpinBox, QDoubleSpinBox, QProgressBar

import pandas as pd

from importers.CsvImporter import CsvImporter
from importers.DatLayerImporter import load_layer_intervals

from PyQt6.QtWidgets import QHeaderView, QListWidgetItem

from models.DataFrameProxyModel import DataFrameProxyModel
from models.DataFrameModel import DataFrameModel
from importers.ObjectFactory import (build_table_object, build_mesh_surface,
                                     build_corner_point_cube, MESH_SUFFIXES)


ASYNC_TABLE_FILE_BYTES = 16 * 1024 * 1024


class TableImportWorker(QThread):
    progress = pyqtSignal(int)

    def __init__(self, filename, coordinates, parameters, options, parent=None):
        super().__init__(parent)
        self.filename, self.coordinates, self.parameters = filename, coordinates, parameters
        self.options = options
        self.result = None
        self.error = None

    def run(self):
        try:
            if self.options["layered_dat"]:
                frame = load_layer_intervals(
                    self.filename, self.coordinates, self.options["layer_column"],
                    self.options["roof_column"], self.options["base_column"], self.parameters,
                    cancelled=self.isInterruptionRequested, progress=self.progress.emit)
            else:
                frame = CsvImporter().load(self.filename, delimiter=self.options["delimiter"],
                                           header=self.options["header"])
            if self.isInterruptionRequested():
                raise InterruptedError("Импорт отменён.")
            if frame.empty:
                raise ValueError("Файл не содержит строк данных.")
            obj = build_table_object(self.options["object_type"], frame, self.filename,
                                     self.coordinates, self.parameters,
                                     self.options["id_column"], self.options["surface_kind"],
                                     cube_geometry=self.options["geometry"],
                                     grid_dimensions=self.options["dimensions"],
                                     singleton_size=self.options["singleton_size"],
                                     connect_existing=self.options["connect_existing"],
                                     layer_column=self.options["layer_column"],
                                     roof_column=self.options["roof_column"],
                                     base_column=self.options["base_column"],
                                     z_direction=self.options["z_direction"])
            self.result = (frame, obj)
        except Exception as error:
            self.error = error


class ImportDialog(QDialog):

    buttonImport: QPushButton
    buttonBrowse: QPushButton
    buttonCancel: QPushButton
    lineEditPathFile: QLineEdit
    tableViewPreview: QTableView
    comboBoxMapX: QComboBox
    comboBoxMapY: QComboBox
    comboBoxMapZ: QComboBox
    listWidgetParametrs: QListWidget
    comboBox_Delimetr: QComboBox
    checkBox: QCheckBox
    checkBox_Header: QCheckBox

    def __init__(self, parent=None):
        super().__init__(parent)

        self._import_worker = None
        self._cancel_import = False

        self.importer = CsvImporter()

        ui = Path(__file__).with_name("ImportDialog.ui")
        uic.loadUi(ui, self)

        self.tableModel = DataFrameModel(self)

        self.tableProxy = DataFrameProxyModel(self)

        self.tableProxy.setSourceModel(
            self.tableModel
        )

        self.tableViewPreview.setModel(
            self.tableProxy
        )

        self.init_ui()
        self.connect_signals()

    def init_ui(self):

        self.setWindowTitle("Импорт объекта")
        self.label_6.setText("Файл")
        self.buttonBrowse.setText("Обзор…")
        self.label_7.setText("Разделитель")
        self.comboBox_Delimetr.setToolTip("Десятичная точка/запятая и кодировка UTF-8/Windows-1251 определяются автоматически.")
        self.label_8.setText("Заголовок")
        self.label.setText("Предпросмотр")
        self.label_2.setText("Назначение колонок")
        self.buttonCancel.setText("Отмена")
        self.buttonImport.setText("Импортировать")
        self.import_progress_label = QLabel("Чтение данных…", self)
        self.import_progress = QProgressBar(self)
        self.import_progress.setRange(0, 0)
        self.layout().insertWidget(self.layout().count() - 1, self.import_progress_label)
        self.layout().insertWidget(self.layout().count() - 1, self.import_progress)
        self.import_progress_label.hide()
        self.import_progress.hide()
        for index, (label, value) in enumerate((("Авто", "auto"), ("Запятая", "comma"),
                                                 ("Точка с запятой", "semicolon"),
                                                 ("Табуляция", "tab"), ("Пробел", "space"))):
            self.comboBox_Delimetr.setItemText(index, label)
            self.comboBox_Delimetr.setItemData(index, value)
        self.comboBoxObjectType = QComboBox()
        for label, value in (("Точки с настраиваемой сеткой", "display_points"),
                             ("Облако точек", "pointcloud"), ("Скважина", "well"),
                             ("Файл скважин", "wellfile"), ("Куб данных", "cube"),
                             ("Поверхность", "surface")):
            self.comboBoxObjectType.addItem(label, value)
        type_row = QWidget(self)
        type_layout = QHBoxLayout(type_row)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.addWidget(QLabel("Тип объекта"))
        type_layout.addWidget(self.comboBoxObjectType)
        self.tab.layout().insertWidget(0, type_row)
        self.well_id_row = QWidget(self)
        id_layout = QHBoxLayout(self.well_id_row)
        id_layout.setContentsMargins(0, 0, 0, 0)
        id_layout.addWidget(QLabel("Идентификатор скважины"))
        self.comboBoxWellId = QComboBox()
        id_layout.addWidget(self.comboBoxWellId)
        self.tab.layout().insertWidget(2, self.well_id_row)
        self.well_id_row.hide()
        self.surface_kind_row = QWidget(self)
        kind_layout = QHBoxLayout(self.surface_kind_row)
        kind_layout.setContentsMargins(0, 0, 0, 0)
        kind_layout.addWidget(QLabel("Вид поверхности"))
        self.comboBoxSurfaceKind = QComboBox()
        for label, value in (("Обычная", "general"), ("Разрез", "section"),
                             ("Трещина", "fault")):
            self.comboBoxSurfaceKind.addItem(label, value)
        kind_layout.addWidget(self.comboBoxSurfaceKind)
        self.tab.layout().insertWidget(3, self.surface_kind_row)
        self.surface_kind_row.hide()
        self.cube_mode_row = QWidget(self)
        cube_mode_layout = QHBoxLayout(self.cube_mode_row)
        cube_mode_layout.setContentsMargins(0, 0, 0, 0)
        cube_mode_layout.addWidget(QLabel("Сетка куба"))
        self.comboBoxCubeGeometry = QComboBox()
        for label, value in (("Corner-point: автоматически", "auto"),
                             ("Corner-point: по рядам центров", "rows"),
                             ("Corner-point: равномерная", "uniform"),
                             ("Послойная модель (кровля/подошва)", "layered"),
                             ("Узловой куб: исходные XYZ без усреднения", "nodes")):
            self.comboBoxCubeGeometry.addItem(label, value)
        self.comboBoxCubeGeometry.setToolTip(
            "Для патчей по исходной сетке выберите узловой куб. "
            "Corner-point: автоматически может усреднять исходные точки в новой сетке.")
        cube_mode_layout.addWidget(self.comboBoxCubeGeometry)
        self.tab.layout().insertWidget(4, self.cube_mode_row)
        self.display_layout_row = QWidget(self)
        display_layout = QHBoxLayout(self.display_layout_row)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.addWidget(QLabel("Структура точек"))
        self.comboBoxDisplayLayout = QComboBox()
        for label, value in (("Исходные XYZ без слоёв", "xyz"),
                             ("Исходные XYZ, разделить по колонке слоя", "layers"),
                             ("Интервалы слоёв: XY, кровля и подошва", "intervals")):
            self.comboBoxDisplayLayout.addItem(label, value)
        display_layout.addWidget(self.comboBoxDisplayLayout)
        self.tab.layout().insertWidget(4, self.display_layout_row)
        self.display_hint = QLabel(
            "Сохраняются точки и назначение слоёв. Corner-point grid строится только для "
            "отображения; его размеры и способ построения задаются после импорта в панели «Отображение». "
            "Для интервалов точка располагается посередине между кровлей и подошвой.", self)
        self.display_hint.setWordWrap(True)
        self.tab.layout().insertWidget(5, self.display_hint)
        self.display_layout_row.hide()
        self.display_hint.hide()
        self.display_z_row = QWidget(self)
        z_layout = QHBoxLayout(self.display_z_row)
        z_layout.setContentsMargins(0, 0, 0, 0)
        z_layout.addWidget(QLabel("Направление Z"))
        self.comboBoxZDirection = QComboBox()
        for label, value in (("Авто: по кровле и подошве", "auto"),
                             ("Высоты: Z увеличивается вверх", "up"),
                             ("Глубины: Z увеличивается вниз", "down")):
            self.comboBoxZDirection.addItem(label, value)
        self.comboBoxZDirection.setToolTip(
            "Для интервалов авто определяет направление по кровле/подошве. "
            "Для исходных XYZ авто означает высоты. Данные в таблице не меняются.")
        z_layout.addWidget(self.comboBoxZDirection)
        self.tab.layout().insertWidget(5, self.display_z_row)
        self.display_z_row.hide()
        self.layer_columns_row = QWidget(self)
        layer_layout = QHBoxLayout(self.layer_columns_row)
        layer_layout.setContentsMargins(0, 0, 0, 0)
        self.comboBoxLayer = QComboBox(self)
        self.comboBoxRoof = QComboBox(self)
        self.comboBoxBase = QComboBox(self)
        for label, combo in (("Слой", self.comboBoxLayer),
                             ("Кровля", self.comboBoxRoof),
                             ("Подошва", self.comboBoxBase)):
            layer_layout.addWidget(QLabel(label))
            layer_layout.addWidget(combo)
        self.tab.layout().insertWidget(5, self.layer_columns_row)
        self.layer_columns_row.hide()
        self.cube_size_row = QWidget(self)
        cube_size_layout = QHBoxLayout(self.cube_size_row)
        cube_size_layout.setContentsMargins(0, 0, 0, 0)
        cube_size_layout.addWidget(QLabel("Ячеек"))
        self.cube_dimension_spins = []
        for axis in "XYZ":
            cube_size_layout.addWidget(QLabel(axis))
            spin = QSpinBox(self)
            spin.setRange(0, 256)
            spin.setSpecialValueText("Авто")
            spin.setToolTip("0 — подобрать автоматически для нерегулярного облака.")
            cube_size_layout.addWidget(spin)
            self.cube_dimension_spins.append(spin)
        self.tab.layout().insertWidget(5, self.cube_size_row)
        self.cube_single_row = QWidget(self)
        cube_single_layout = QHBoxLayout(self.cube_single_row)
        cube_single_layout.setContentsMargins(0, 0, 0, 0)
        cube_single_layout.addWidget(QLabel("Размер ячейки по одиночной оси"))
        self.cubeSingletonSize = QDoubleSpinBox(self)
        self.cubeSingletonSize.setRange(0.0001, 1_000_000_000)
        self.cubeSingletonSize.setDecimals(4)
        self.cubeSingletonSize.setValue(1.0)
        self.cubeSingletonSize.setKeyboardTracking(False)
        cube_single_layout.addWidget(self.cubeSingletonSize)
        self.tab.layout().insertWidget(6, self.cube_single_row)
        self.cubeConnectCheck = QCheckBox("Соединять существующие ячейки через пустые интервалы", self)
        self.cubeConnectCheck.setChecked(True)
        self.cubeConnectCheck.setToolTip("Расширяет границы соседних ячеек без добавления ячеек и изменения их параметров.")
        self.tab.layout().insertWidget(7, self.cubeConnectCheck)
        self.cube_hint = QLabel("XYZ задают центры ячеек. По рядам — одна ячейка на точку; "
                                "без рядов — усреднение точек в равномерной сетке. "
                                "Пустые ячейки неактивны; их интервалы можно перекрыть "
                                "расширением существующих ячеек. "
                                "Для патчей по исходной сетке выберите узловой куб.", self)
        self.cube_hint.setWordWrap(True)
        self.tab.layout().insertWidget(8, self.cube_hint)
        self.tab.layout().removeWidget(self.layer_columns_row)
        self.tab.layout().insertWidget(5, self.layer_columns_row)
        self.layer_hint = QLabel(
            "Для каждого индекса слоя строится отдельный куб. X/Y задают положение ячеек; "
            "высота берётся из кровли и подошвы, колонка Z не используется.", self)
        self.layer_hint.setWordWrap(True)
        self.tab.layout().insertWidget(6, self.layer_hint)
        self.cube_mode_row.hide()
        self.cube_size_row.hide()
        self.cube_single_row.hide()
        self.cubeConnectCheck.hide()
        self.cube_hint.hide()
        self.layer_hint.hide()
        self._mesh_preview = False
        self._corner_preview_cube = None
        self._layer_dat_preview = False
        self._auto_layer_dat_source = None
        self._sync_cube_controls()
        self.buttonImport.setEnabled(False)
        self.tabWidget.setTabText(0, "Данные")
        self.tabWidget.removeTab(1)

        self.tableViewPreview.setSortingEnabled(True)

    def connect_signals(self):

        self.buttonBrowse.clicked.connect(self.select_file)

        self.buttonCancel.clicked.connect(self.reject)

        self.buttonImport.clicked.connect(self.import_data)
        self.comboBox_Delimetr.currentIndexChanged.connect(self.reload_preview)
        self.checkBox_Header.stateChanged.connect(self.reload_preview)
        self.lineEditPathFile.textChanged.connect(lambda: self.buttonImport.setEnabled(False))
        self.lineEditPathFile.editingFinished.connect(self.reload_preview)
        self.comboBoxObjectType.currentIndexChanged.connect(self._type_changed)
        self.comboBoxCubeGeometry.currentIndexChanged.connect(self._sync_cube_controls)
        self.comboBoxDisplayLayout.currentIndexChanged.connect(self._sync_cube_controls)

    @property
    def object_type(self):
        return self.comboBoxObjectType.currentData()

    def _type_changed(self):
        if self.object_type == "display_points" and self._layer_dat_preview:
            self.comboBoxDisplayLayout.setCurrentIndex(
                self.comboBoxDisplayLayout.findData("intervals"))
        self.well_id_row.setVisible(self.object_type in ("well", "wellfile"))
        self.surface_kind_row.setVisible(self.object_type == "surface")
        self.listWidgetParametrs.setEnabled(self.object_type != "surface")
        self.label_2.setText("Назначение колонок (поверхность: только XYZ)"
                             if self.object_type == "surface" else
                             "Координаты и класс/атрибуты отметок скважин"
                             if self.object_type in ("well", "wellfile") else "Назначение колонок")
        self.listWidgetParametrs.setToolTip(
            "Выберите колонку класса, например class. Предикторы модели извлекаются из куба."
            if self.object_type in ("well", "wellfile") else "Выберите параметры объекта.")
        self._sync_cube_controls()
        self.reload_preview()

    def _sync_cube_controls(self):
        is_cube_table = (self.object_type == "cube" and
                         Path(self.lineEditPathFile.text().strip()).suffix.lower() != ".grdecl")
        mode = self.comboBoxCubeGeometry.currentData()
        display = self.object_type == "display_points"
        display_layout = self.comboBoxDisplayLayout.currentData()
        intervals = display and display_layout == "intervals"
        layers = is_cube_table and mode == "layered"
        self.display_layout_row.setVisible(display)
        self.display_z_row.setVisible(display)
        self.display_hint.setVisible(display)
        self.cube_mode_row.setVisible(is_cube_table)
        self.layer_columns_row.setVisible(layers or display and display_layout != "xyz")
        self.comboBoxRoof.setEnabled(not display or intervals)
        self.comboBoxBase.setEnabled(not display or intervals)
        self.layer_hint.setVisible(is_cube_table and mode == "layered")
        self.cube_size_row.setVisible(is_cube_table and mode in ("auto", "uniform", "layered"))
        self.cube_dimension_spins[2].setEnabled(mode != "layered")
        self.comboBoxMapZ.setEnabled(
            Path(self.lineEditPathFile.text().strip()).suffix.lower() != ".grdecl"
            and (not is_cube_table or mode != "layered") and not intervals)
        self.cube_single_row.setVisible(is_cube_table and mode != "nodes")
        self.cubeConnectCheck.setVisible(is_cube_table and mode not in ("nodes", "layered"))
        self.cube_hint.setVisible(is_cube_table and mode not in ("nodes", "layered"))

    def select_file(self):

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть данные",
            "",
            "Данные (*.csv *.txt *.dat *.grdecl *.vtk *.vtp *.stl *.obj *.ply *.vtu *.vts);;Все файлы (*)"
        )

        if not filename:
            return

        self.lineEditPathFile.setText(filename)
        if Path(filename).suffix.lower() == ".grdecl" and self.object_type != "cube":
            self.comboBoxObjectType.setCurrentIndex(self.comboBoxObjectType.findData("cube"))
        else:
            self.load_preview()

    def load_preview(self):
        filename = self.lineEditPathFile.text().strip()

        if not filename:
            return

        self.buttonImport.setEnabled(False)
        self._corner_preview_cube = None
        self._layer_dat_preview = False
        corner_file = Path(filename).suffix.lower() == ".grdecl"
        self._sync_cube_controls()
        for widget in (self.comboBox_Delimetr, self.checkBox_Header, self.comboBoxMapX,
                       self.comboBoxMapY, self.comboBoxMapZ):
            widget.setEnabled(not corner_file)
        self._sync_cube_controls()
        self.listWidgetParametrs.setEnabled(not corner_file and self.object_type != "surface")
        try:
            self._mesh_preview = self.object_type == "surface" and Path(filename).suffix.lower() in MESH_SUFFIXES
            if corner_file and self.object_type != "cube":
                raise ValueError("Файл GRDECL импортируется как «Куб данных».")
            if corner_file:
                self._corner_preview_cube = build_corner_point_cube(filename)
                df = self._corner_preview_cube.dataframe.head(100)
            elif self._mesh_preview:
                mesh = build_mesh_surface(filename, self.comboBoxSurfaceKind.currentData())
                df = pd.DataFrame(mesh.vertices, columns=["x", "y", "z"]).head(100)
            else:
                df = self.importer.preview(
                    filename,
                    delimiter=self.current_delimiter(),
                    header=self.checkBox_Header.isChecked()
                )
                self._layer_dat_preview = (Path(filename).suffix.lower() == ".dat"
                                           and {"PKX", "PKY", "layer_id", "layer_AbsRoof",
                                                "layer_AbsBase"}.issubset(df.columns)
                                           and self.checkBox_Header.isChecked())
                if self._layer_dat_preview and self._auto_layer_dat_source != filename:
                    self._auto_layer_dat_source = filename
                    if self.object_type == "display_points":
                        self.comboBoxDisplayLayout.setCurrentIndex(
                            self.comboBoxDisplayLayout.findData("intervals"))
                    elif self.object_type == "cube":
                        self.comboBoxCubeGeometry.setCurrentIndex(
                            self.comboBoxCubeGeometry.findData("layered"))
                    self._sync_cube_controls()
        except Exception as error:
            self.tableModel.clear()
            for combo in (self.comboBoxMapX, self.comboBoxMapY, self.comboBoxMapZ):
                combo.clear()
            self.listWidgetParametrs.clear()
            self.comboBoxWellId.clear()
            for combo in (self.comboBoxLayer, self.comboBoxRoof, self.comboBoxBase):
                combo.clear()
            QMessageBox.warning(self, "Не удалось прочитать файл", str(error))
            return

        self.tableModel.set_dataframe(df)

        # print(self.tableModel.rowCount())
        # print(self.tableModel.columnCount())

        header = self.tableViewPreview.horizontalHeader()

        header.setStretchLastSection(True)

        header.setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )

        columns = list(df.columns)

        self.comboBoxMapX.clear()
        self.comboBoxMapY.clear()
        self.comboBoxMapZ.clear()

        self.comboBoxMapX.addItems(columns)
        self.comboBoxMapY.addItems(columns)
        self.comboBoxMapZ.addItems(columns)
        self.comboBoxWellId.clear()
        self.comboBoxWellId.addItems(columns)
        for combo in (self.comboBoxLayer, self.comboBoxRoof, self.comboBoxBase):
            combo.clear()
            combo.addItems(columns)
        for combo, preferred in ((self.comboBoxLayer, ("layer_id", "layer", "слой", "номер_слоя")),
                                 (self.comboBoxRoof, ("layer_absroof", "absroof", "roof", "кровля")),
                                 (self.comboBoxBase, ("layer_absbase", "absbase", "base", "подошва"))):
            match = next((i for wanted in preferred for i, name in enumerate(columns)
                          if str(name).casefold() == wanted), None)
            combo.setCurrentIndex(match if match is not None else -1)
        for preferred in ("well_id", "wellid", "well", "id", "скважина", "номер_скважины"):
            match = next((i for i, name in enumerate(columns) if name.lower() == preferred), None)
            if match is not None:
                self.comboBoxWellId.setCurrentIndex(match)
                break

        for index, combo in enumerate((self.comboBoxMapX, self.comboBoxMapY, self.comboBoxMapZ)):
            combo.setCurrentIndex(index if index < len(columns) else -1)

        for i, name in enumerate(columns):

            lname = name.lower()

            if lname == "x":
                self.comboBoxMapX.setCurrentIndex(i)

            elif lname == "y":
                self.comboBoxMapY.setCurrentIndex(i)

            elif lname == "z":
                self.comboBoxMapZ.setCurrentIndex(i)
        if self._layer_dat_preview:
            self.comboBoxMapX.setCurrentIndex(columns.index("PKX"))
            self.comboBoxMapY.setCurrentIndex(columns.index("PKY"))
            if self.object_type == "display_points" and "H" in columns:
                self.comboBoxMapZ.setCurrentIndex(columns.index("H"))

        self.listWidgetParametrs.clear()

        for column in columns:

            # Пропускаем координаты
            if column.lower() in ("x", "y", "z"):
                continue

            item = QListWidgetItem(column)

            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )

            is_cube_index = self.object_type == "cube" and column.upper() in ("I", "J", "K")
            numeric_preview = pd.to_numeric(df[column], errors="coerce").notna().any()
            dat_parameter = (column.startswith("layer_") and
                             column not in ("layer_id", "layer_number", "layer_abs_h",
                                            "layer_AbsRoof", "layer_AbsBase"))
            item.setCheckState(Qt.CheckState.Checked if self._layer_dat_preview and
                               dat_parameter and numeric_preview else
                               Qt.CheckState.Unchecked if self._layer_dat_preview or is_cube_index or
                               (self.object_type == "cube" and not numeric_preview)
                               else Qt.CheckState.Checked)

            self.listWidgetParametrs.addItem(item)

        self.buttonImport.setEnabled(len(columns) >= 3 and not df.empty)


    def reload_preview(self):
        if self.lineEditPathFile.text().strip():
            self.load_preview()

    def current_delimiter(self):
        if self.comboBox_Delimetr.currentData() is not None:
            return self.comboBox_Delimetr.currentData()
        text = self.comboBox_Delimetr.currentText().lower()

        if "comma" in text or "coma" in text:
            return "comma"
        if "semicolon" in text:
            return "semicolon"
        if "tab" in text:
            return "tab"
        if "space" in text:
            return "space"

        return "auto"

    def selected_parameters(self):
        if self.object_type == "surface":
            return []
        parameters = []
        display = self.object_type == "display_points"
        layered = (self.object_type == "cube" and self.comboBoxCubeGeometry.currentData() == "layered"
                   or display and self.comboBoxDisplayLayout.currentData() == "intervals")
        coordinates = {self.comboBoxMapX.currentText(), self.comboBoxMapY.currentText()}
        if not layered:
            coordinates.add(self.comboBoxMapZ.currentText())

        for row in range(self.listWidgetParametrs.count()):
            item = self.listWidgetParametrs.item(row)

            if (item.checkState() == Qt.CheckState.Checked and item.text() not in coordinates
                    and (not (layered or display and self.comboBoxDisplayLayout.currentData() == "layers")
                         or item.text() != self.comboBoxLayer.currentText())):
                parameters.append(item.text())

        return parameters

    def import_data(self):
        filename = self.lineEditPathFile.text().strip()

        if not filename:
            return

        self.coordinate_columns = (
            self.comboBoxMapX.currentText(),
            self.comboBoxMapY.currentText(),
            self.comboBoxMapZ.currentText(),
        )
        self.parameter_columns = self.selected_parameters()

        layered_dat = (self._layer_dat_preview and (
            self.object_type == "cube" and self.comboBoxCubeGeometry.currentData() == "layered"
            or self.object_type == "display_points" and
            self.comboBoxDisplayLayout.currentData() == "intervals"))
        try:
            background = (self._corner_preview_cube is None and not self._mesh_preview
                          and Path(filename).stat().st_size >= ASYNC_TABLE_FILE_BYTES)
        except OSError as error:
            QMessageBox.warning(self, "Не удалось импортировать данные", str(error))
            return
        if background:
            options = {"object_type": self.object_type,
                       "layered_dat": layered_dat,
                       "delimiter": self.current_delimiter(),
                       "header": self.checkBox_Header.isChecked(),
                       "id_column": self.comboBoxWellId.currentText() or None,
                       "surface_kind": self.comboBoxSurfaceKind.currentData(),
                       "geometry": (self.comboBoxDisplayLayout.currentData() if self.object_type == "display_points"
                                    else self.comboBoxCubeGeometry.currentData()),
                       "dimensions": tuple(spin.value() for spin in self.cube_dimension_spins),
                       "singleton_size": self.cubeSingletonSize.value(),
                       "connect_existing": self.cubeConnectCheck.isChecked(),
                       "layer_column": self.comboBoxLayer.currentText() or None,
                       "roof_column": self.comboBoxRoof.currentText() or None,
                       "base_column": self.comboBoxBase.currentText() or None,
                       "z_direction": self.comboBoxZDirection.currentData()}
            self._cancel_import = False
            self._import_worker = TableImportWorker(filename, self.coordinate_columns,
                                                     self.parameter_columns, options, self)
            self._import_worker.progress.connect(self._show_import_progress)
            self._import_worker.finished.connect(self._finish_background_import)
            self.tabWidget.setEnabled(False)
            self.buttonImport.setEnabled(False)
            self.buttonCancel.setText("Отменить загрузку")
            self.import_progress_label.setText("Чтение данных…")
            self.import_progress_label.show()
            self.import_progress.show()
            self._import_worker.start()
            return

        try:
            if self._corner_preview_cube is not None:
                self.import_object = self._corner_preview_cube
                self.dataframe = self.import_object.dataframe
            elif self._mesh_preview:
                self.dataframe = None
                self.import_object = build_mesh_surface(filename, self.comboBoxSurfaceKind.currentData())
            else:
                if layered_dat:
                    self.dataframe = load_layer_intervals(
                        filename, self.coordinate_columns,
                        self.comboBoxLayer.currentText(), self.comboBoxRoof.currentText(),
                        self.comboBoxBase.currentText(), self.parameter_columns)
                else:
                    self.dataframe = self.importer.load(
                        filename,
                        delimiter=self.current_delimiter(),
                        header=self.checkBox_Header.isChecked()
                    )
                if self.dataframe.empty:
                    raise ValueError("Файл не содержит строк данных.")
                self.import_object = build_table_object(
                    self.object_type, self.dataframe, filename, self.coordinate_columns,
                    self.parameter_columns, self.comboBoxWellId.currentText() or None,
                    self.comboBoxSurfaceKind.currentData(),
                    cube_geometry=(self.comboBoxDisplayLayout.currentData() if self.object_type == "display_points"
                                   else self.comboBoxCubeGeometry.currentData() if self.object_type == "cube" else "nodes"),
                    grid_dimensions=tuple(spin.value() for spin in self.cube_dimension_spins),
                    singleton_size=self.cubeSingletonSize.value(),
                    connect_existing=self.cubeConnectCheck.isChecked(),
                    layer_column=self.comboBoxLayer.currentText() or None,
                    roof_column=self.comboBoxRoof.currentText() or None,
                    base_column=self.comboBoxBase.currentText() or None,
                    z_direction=self.comboBoxZDirection.currentData())
        except Exception as error:
            QMessageBox.warning(self, "Не удалось импортировать данные", str(error))
            return

        self.accept()

    def _show_import_progress(self, count):
        if not self._cancel_import:
            self.import_progress_label.setText(f"Чтение слоёв: обработано строк {count:,}".replace(",", " "))

    def _finish_background_import(self):
        worker = self._import_worker
        if worker is None:
            return
        self._import_worker = None
        self.import_progress.hide()
        self.import_progress_label.hide()
        self.tabWidget.setEnabled(True)
        self.buttonImport.setEnabled(True)
        self.buttonCancel.setEnabled(True)
        self.buttonCancel.setText("Отмена")
        if self._cancel_import or isinstance(worker.error, InterruptedError):
            worker.deleteLater()
            super().reject()
            return
        if worker.error is not None:
            error = worker.error
            worker.deleteLater()
            QMessageBox.warning(self, "Не удалось импортировать данные", str(error))
            return
        self.dataframe, self.import_object = worker.result
        worker.deleteLater()
        self.accept()

    def reject(self):
        if self._import_worker is not None:
            self._cancel_import = True
            self._import_worker.requestInterruption()
            self.buttonCancel.setEnabled(False)
            self.import_progress_label.setText("Остановка загрузки…")
            return
        super().reject()

    def closeEvent(self, event):
        if self._import_worker is not None:
            event.ignore()
            self.reject()
            return
        super().closeEvent(event)
