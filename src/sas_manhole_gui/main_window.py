from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from sas_manhole_gui import recent
from sas_manhole_gui.canvas import RasterCanvas
from sas_manhole_gui.dialogs.export_dialog import ExportDialog
from sas_manhole_gui.dialogs.model_load_dialog import ModelLoadDialog
from sas_manhole_gui.inference_worker import (
    SAM_FILTER_INSIDE,
    SAM_FILTER_NONE,
    SAM_FILTER_OUTSIDE,
    InferenceWorker,
)
from sas_manhole_gui.project_state import ProjectState, SamRegion
from sas_manhole_gui.raster_loader import RasterOpenWorker
from sas_manhole_gui.raster_layer import PixelWindow
from sas_manhole_gui.sam_manager import LoadedSam, load_sam
from sas_manhole_gui.sam_worker import SamTextWorker
from sas_manhole_gui.widgets.class_panel import ClassPanel
from sas_manhole_gui.widgets.detection_list import DetectionListPanel
from sas_manhole_gui.widgets.sam_panel import SamPanel
from sas_manhole_gui.widgets.thumbnail_panel import ThumbnailPanel

IMAGE_EXTENSIONS = (".tif", ".tiff", ".png", ".jpg", ".jpeg")
IMAGE_FILTER = "Images (*.tif *.tiff *.png *.jpg *.jpeg);;GeoTIFF (*.tif *.tiff);;PNG (*.png);;JPEG (*.jpg *.jpeg);;All files (*.*)"
SAM_INPUT_SIZE = 1024


def _folder_image_files(folder: Path) -> list[Path]:
    found: set[Path] = set()
    for ext in IMAGE_EXTENSIONS:
        found.update(folder.glob(f"*{ext}"))
        found.update(folder.glob(f"*{ext.upper()}"))
    return sorted(found)


class RunOptionsDialog(QDialog):
    def __init__(self, has_multiple_rasters: bool, has_sam_regions: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detection Settings")
        layout = QFormLayout(self)

        self.scope_combo: Optional[QComboBox] = None
        if has_multiple_rasters:
            self.scope_combo = QComboBox()
            self.scope_combo.addItems(["Active image", "All open images"])
            layout.addRow("Scope:", self.scope_combo)

        self.tile_size_spin = QSpinBox()
        self.tile_size_spin.setRange(128, 4096)
        self.tile_size_spin.setSingleStep(32)
        self.tile_size_spin.setValue(640)
        layout.addRow("Tile size (px):", self.tile_size_spin)

        self.overlap_spin = QDoubleSpinBox()
        self.overlap_spin.setRange(0.0, 0.9)
        self.overlap_spin.setSingleStep(0.05)
        self.overlap_spin.setValue(0.2)
        layout.addRow("Tile overlap:", self.overlap_spin)

        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.01, 0.99)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.setValue(0.25)
        layout.addRow("Confidence threshold:", self.conf_spin)

        self.sam_filter_combo = QComboBox()
        self.sam_filter_combo.addItem("No filter (use whole image)", SAM_FILTER_NONE)
        self.sam_filter_combo.addItem("Only INSIDE SAM regions", SAM_FILTER_INSIDE)
        self.sam_filter_combo.addItem("Only OUTSIDE SAM regions", SAM_FILTER_OUTSIDE)
        self.sam_filter_combo.setEnabled(has_sam_regions)
        if not has_sam_regions:
            self.sam_filter_combo.setToolTip("Segment SAM regions first from the SAM tab.")
        layout.addRow("SAM region filter:", self.sam_filter_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def scope_all(self) -> bool:
        return self.scope_combo is not None and self.scope_combo.currentIndex() == 1

    def sam_filter_mode(self) -> str:
        return self.sam_filter_combo.currentData()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SAS Manhole GUI — Orthophoto Detection Interface")
        self.resize(1440, 900)

        self.project_state = ProjectState()
        self._inference_worker: Optional[InferenceWorker] = None
        self._loader: Optional[RasterOpenWorker] = None
        self._sam_worker: Optional[SamTextWorker] = None
        self._sam_default_path = Path(__file__).resolve().parents[2] / "sam3.pt"

        self.canvas = RasterCanvas(self.project_state, self)
        self.setCentralWidget(self.canvas)

        self.thumbnail_panel = ThumbnailPanel(self.project_state)
        self.class_panel = ClassPanel(self.project_state)
        self.detection_list = DetectionListPanel(self.project_state)
        self.sam_panel = SamPanel(self.project_state)

        self._build_docks()
        self._build_toolbar()
        self._build_statusbar()
        self._build_shortcuts()
        self._wire_signals()

    def _build_docks(self) -> None:
        left_dock = QDockWidget("Images", self)
        left_dock.setWidget(self.thumbnail_panel)
        left_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)

        right_tabs = QTabWidget()
        right_tabs.addTab(self.detection_list, "Detections")
        right_tabs.addTab(self.sam_panel, "SAM")
        right_tabs.addTab(self.class_panel, "Classes")
        right_dock = QDockWidget("Details", self)
        right_dock.setWidget(right_tabs)
        right_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_dock)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Tools", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_files_action = QAction("Open Files", self)
        open_files_action.triggered.connect(self._on_open_files)
        toolbar.addAction(open_files_action)

        open_folder_action = QAction("Open Folder", self)
        open_folder_action.triggered.connect(self._on_open_folder)
        toolbar.addAction(open_folder_action)

        self.recent_button = QToolButton(self)
        self.recent_button.setText("Recent")
        self.recent_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.recent_menu = QMenu(self.recent_button)
        self.recent_button.setMenu(self.recent_menu)
        self.recent_menu.aboutToShow.connect(self._populate_recent_menu)
        toolbar.addWidget(self.recent_button)

        toolbar.addSeparator()

        self.load_model_action = QAction("Load Model", self)
        self.load_model_action.triggered.connect(self._on_load_model)
        toolbar.addAction(self.load_model_action)

        self.run_action = QAction("Run", self)
        self.run_action.setEnabled(False)
        self.run_action.triggered.connect(self._on_run)
        toolbar.addAction(self.run_action)
        run_widget = toolbar.widgetForAction(self.run_action)
        if isinstance(run_widget, QToolButton):
            run_widget.setObjectName("primaryToolButton")

        toolbar.addSeparator()

        self.load_sam_action = QAction("Load SAM", self)
        self.load_sam_action.triggered.connect(self._on_load_sam)
        toolbar.addAction(self.load_sam_action)

        toolbar.addSeparator()

        self.draw_action = QAction("Draw Box  (R)", self)
        self.draw_action.setCheckable(True)
        self.draw_action.toggled.connect(self._on_toggle_draw)
        toolbar.addAction(self.draw_action)

        self.pan_action = QAction("Pan  (T)", self)
        self.pan_action.setCheckable(True)
        self.pan_action.toggled.connect(self._on_toggle_pan)
        toolbar.addAction(self.pan_action)

        self.undo_action = QAction("Undo", self)
        self.undo_action.setToolTip("Undo the last edit (Ctrl+Z)")
        self.undo_action.setEnabled(False)
        self.undo_action.triggered.connect(self._on_undo)
        toolbar.addAction(self.undo_action)

        toolbar.addSeparator()

        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.triggered.connect(self.canvas.zoom_in)
        toolbar.addAction(zoom_in_action)

        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.triggered.connect(self.canvas.zoom_out)
        toolbar.addAction(zoom_out_action)

        zoom_fit_action = QAction("Fit", self)
        zoom_fit_action.triggered.connect(self.canvas.zoom_fit)
        toolbar.addAction(zoom_fit_action)

        toolbar.addSeparator()

        export_action = QAction("Export", self)
        export_action.triggered.connect(self._on_export)
        toolbar.addAction(export_action)

    def _build_statusbar(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)

        self.model_label = QLabel("Model: not loaded")
        self.model_label.setObjectName("statusHint")
        status.addWidget(self.model_label)

        divider = QLabel("|")
        divider.setObjectName("statusDivider")
        status.addWidget(divider)

        self.sam_label = QLabel("SAM: not loaded")
        self.sam_label.setObjectName("statusHint")
        status.addWidget(self.sam_label)

        right = QWidget()
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.pause_button = QPushButton("Pause")
        self.pause_button.setObjectName("statusPauseButton")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self._on_pause_resume)
        right_layout.addWidget(self.pause_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("statusStopButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop)
        right_layout.addWidget(self.stop_button)

        vsep = QLabel("|")
        vsep.setObjectName("statusDivider")
        right_layout.addWidget(vsep)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(240)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("Ready.")
        self.progress_label.setObjectName("statusHint")
        self.progress_label.setMinimumWidth(180)
        right_layout.addWidget(self.progress_label)

        status.addPermanentWidget(right)

    def _build_shortcuts(self) -> None:
        undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        undo_sc.activated.connect(self._on_undo)

        del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        del_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        del_sc.activated.connect(self._on_delete_selected)

        back_sc = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self)
        back_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        back_sc.activated.connect(self._on_delete_selected)

        r_sc = QShortcut(QKeySequence(Qt.Key.Key_R), self)
        r_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        r_sc.activated.connect(self._on_shortcut_r)

        t_sc = QShortcut(QKeySequence(Qt.Key.Key_T), self)
        t_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        t_sc.activated.connect(self._on_shortcut_t)

    def _text_input_focused(self) -> bool:
        focused = QApplication.focusWidget()
        return isinstance(focused, (QLineEdit, QAbstractSpinBox))

    def _on_shortcut_r(self) -> None:
        if self._text_input_focused():
            return
        self.draw_action.toggle()

    def _on_shortcut_t(self) -> None:
        if self._text_input_focused():
            return
        self.pan_action.toggle()

    def _wire_signals(self) -> None:
        self.canvas.detection_selected.connect(self.detection_list.select_detection)
        self.detection_list.detection_activated.connect(self.canvas.select_detection)
        self.class_panel.current_class_changed.connect(self._on_draw_class_changed)
        self.sam_panel.segment_requested.connect(self._on_sam_segment_requested)
        self.project_state.model_changed.connect(self._on_model_changed)
        self.project_state.sam_model_changed.connect(self._on_sam_model_changed)
        self.project_state.undo_manager.stack_changed.connect(self._on_undo_stack_changed)

    def _populate_recent_menu(self) -> None:
        self.recent_menu.clear()
        folders = recent.recent_folders()
        files = recent.recent_files()
        if not folders and not files:
            act = self.recent_menu.addAction("(empty)")
            act.setEnabled(False)
            return
        if folders:
            hdr = self.recent_menu.addAction("Folders")
            hdr.setEnabled(False)
            for f in folders:
                act = self.recent_menu.addAction(f)
                act.triggered.connect(lambda _checked=False, path=f: self._open_folder_path(Path(path)))
        if files:
            self.recent_menu.addSeparator()
            hdr = self.recent_menu.addAction("Files")
            hdr.setEnabled(False)
            for f in files:
                act = self.recent_menu.addAction(f)
                act.triggered.connect(lambda _checked=False, path=f: self._open_paths([Path(path)]))
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("Clear List")
        clear.triggered.connect(recent.clear_recent)

    def _initial_dir(self) -> str:
        return recent.last_directory()

    def _on_open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select image(s)", self._initial_dir(), IMAGE_FILTER)
        if not paths:
            return
        path_objs = [Path(p) for p in paths]
        recent.add_files(path_objs)
        self._open_paths(path_objs)

    def _on_open_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select folder", self._initial_dir())
        if not directory:
            return
        self._open_folder_path(Path(directory))

    def _open_folder_path(self, folder: Path) -> None:
        if not folder.exists():
            QMessageBox.warning(self, "Not found", f"Folder does not exist:\n{folder}")
            return
        found = _folder_image_files(folder)
        if not found:
            QMessageBox.information(
                self,
                "No results",
                "No image files (.tif/.tiff/.png/.jpg/.jpeg) found in this folder.",
            )
            return
        recent.add_folder(folder)
        self._open_paths(found)

    def _decide_open_mode(self, incoming_count: int) -> Optional[str]:
        if not self.project_state.rasters:
            return "replace"
        current = len(self.project_state.rasters)
        box = QMessageBox(self)
        box.setWindowTitle("Open Images")
        box.setIcon(QMessageBox.Icon.Question)
        current_word = "image" if current == 1 else "images"
        incoming_word = "one" if incoming_count == 1 else f"{incoming_count} images"
        box.setText(f"You already have {current} {current_word} open.")
        box.setInformativeText(f"How should the {incoming_word} you are opening be handled?")
        add_btn = box.addButton("Add to current", QMessageBox.ButtonRole.AcceptRole)
        replace_btn = box.addButton("Replace current", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(add_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is add_btn:
            return "add"
        if clicked is replace_btn:
            return "replace"
        return None

    def _open_paths(self, paths: list[Path]) -> None:
        if not paths:
            return
        mode = self._decide_open_mode(len(paths))
        if mode is None:
            return
        if self._loader is not None and self._loader.isRunning():
            self._loader.wait()
        if mode == "replace":
            self.project_state.clear_rasters()
        self._loader = RasterOpenWorker(paths, self)
        self._loader.file_opened.connect(self._on_file_opened)
        self._loader.file_failed.connect(self._on_file_failed)
        self._loader.progress.connect(self._on_load_progress)
        self._loader.finished_all.connect(self._on_load_finished)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(paths))
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"Loading images... (0/{len(paths)})")
        self._loader.start()

    def _on_file_opened(self, path_str: str, layer, thumbnail) -> None:
        path = Path(path_str)
        self.project_state.add_raster_prebuilt(path, layer, thumbnail, notify=False)

    def _on_file_failed(self, path_str: str, message: str) -> None:
        self.progress_label.setText(f"Failed: {Path(path_str).name}")

    def _on_load_progress(self, done: int, total: int) -> None:
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"Loading images... ({done}/{total})")

    def _on_load_finished(self) -> None:
        self.project_state.rasters_changed.emit()
        self.progress_bar.setVisible(False)
        self.progress_label.setText(f"Loaded {len(self.project_state.rasters)} images")
        self._loader = None

    def _on_load_model(self) -> None:
        dialog = ModelLoadDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.project_state.model = dialog.loaded_model
        self.project_state.model_path = dialog.model_path
        self.project_state.set_classes(dialog.classes)
        self.project_state.model_changed.emit()

    def _on_model_changed(self) -> None:
        if self.project_state.model is None:
            self.model_label.setText("Model: not loaded")
            self.run_action.setEnabled(False)
            return
        name = self.project_state.model_path.name if self.project_state.model_path else "?"
        self.model_label.setText(f"Model: {name}  ({len(self.project_state.classes)} classes)")
        self.run_action.setEnabled(True)

    def _on_load_sam(self) -> None:
        default = str(self._sam_default_path) if self._sam_default_path.exists() else self._initial_dir()
        path_str, _ = QFileDialog.getOpenFileName(self, "Select SAM model (.pt)", default, "SAM Model (*.pt)")
        if not path_str:
            return
        path = Path(path_str)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            loaded = load_sam(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error", f"Could not load SAM model:\n{exc}")
            return
        QApplication.restoreOverrideCursor()
        self.project_state.sam = loaded
        self.project_state.sam_path = path
        self.project_state.sam_model_changed.emit()

    def _on_sam_model_changed(self) -> None:
        sam: Optional[LoadedSam] = self.project_state.sam
        if sam is None:
            self.sam_label.setText("SAM: not loaded")
            return
        self.sam_label.setText(f"SAM: {sam.path.name}  ({sam.kind})")

    def _on_sam_segment_requested(self, text: str, conf: float, scope: str) -> None:
        if self.project_state.sam is None or self.project_state.active_raster_path is None:
            return
        pr = self.project_state.active_raster
        if pr is None:
            return
        if self._sam_worker is not None and self._sam_worker.isRunning():
            self.progress_label.setText("SAM: previous query still running")
            return

        if scope == "full":
            window = self.canvas.full_pixel_window()
        else:
            window = self.canvas.visible_pixel_window()
        if window is None:
            window = self.canvas.full_pixel_window()
        if window is None:
            return

        image_np = pr.layer.read_tile_array(window, SAM_INPUT_SIZE)
        offset = (float(window.col_off), float(window.row_off))
        native_size = (int(window.width), int(window.height))

        self._sam_worker = SamTextWorker(
            self.project_state.active_raster_path,
            self.project_state.sam,
            image_np,
            text,
            conf,
            offset,
            native_size,
            self,
        )
        self._sam_worker.result.connect(self._on_sam_result)
        self._sam_worker.error.connect(self._on_sam_error)
        self.progress_label.setText(f"SAM: segmenting '{text}'...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._sam_worker.start()

    def _on_sam_result(self, raster_path: str, text: str, results: list) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self._sam_worker = None
        if not results:
            self.progress_label.setText(f"SAM: no regions found for '{text}'.")
            return
        for _text, conf, bbox, polygon in results:
            region = SamRegion(
                x_min=bbox[0], y_min=bbox[1], x_max=bbox[2], y_max=bbox[3],
                text=text, confidence=conf, polygon=polygon,
            )
            self.project_state.add_sam_region(raster_path, region)
        self.progress_label.setText(f"SAM: added {len(results)} region(s) for '{text}'.")

    def _on_sam_error(self, raster_path: str, message: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_label.setText(f"SAM error: {message}")
        self._sam_worker = None
        QMessageBox.warning(self, "SAM error", message)

    def _on_toggle_draw(self, checked: bool) -> None:
        self.canvas.set_draw_mode(checked, self.class_panel.current_class_id())
        if checked and self.pan_action.isChecked():
            self.pan_action.setChecked(False)

    def _on_toggle_pan(self, checked: bool) -> None:
        self.canvas.set_pan_mode(checked)
        if checked and self.draw_action.isChecked():
            self.draw_action.setChecked(False)

    def _on_draw_class_changed(self, class_id: int) -> None:
        if self.draw_action.isChecked():
            self.canvas.set_draw_mode(True, class_id)

    def _on_undo(self) -> None:
        description = self.project_state.undo_manager.undo()
        if description:
            self.progress_label.setText(f"Undone: {description}")

    def _on_undo_stack_changed(self, depth: int) -> None:
        self.undo_action.setEnabled(depth > 0)
        label = "Undo" if depth == 0 else f"Undo ({depth})"
        self.undo_action.setText(label)

    def _on_delete_selected(self) -> None:
        path = self.project_state.active_raster_path
        if path is None:
            return
        pr = self.project_state.active_raster
        if pr is None:
            return
        det_id = self.detection_list._selected_det_id()
        if det_id is not None:
            self.project_state.remove_detection(path, det_id)
            return
        for item in self.canvas.scene_.selectedItems():
            from sas_manhole_gui.canvas import SamRegionItem
            from sas_manhole_gui.detection_item import DetectionItem

            if isinstance(item, DetectionItem):
                self.project_state.remove_detection(path, item.det_id)
            elif isinstance(item, SamRegionItem):
                self.project_state.remove_sam_region(path, item.region_id)

    def _on_run(self) -> None:
        if self.project_state.model is None:
            QMessageBox.warning(self, "No model", "Please load a model first.")
            return
        if not self.project_state.rasters:
            QMessageBox.warning(self, "No images", "Please open at least one image first.")
            return

        has_sam_regions = any(pr.sam_regions for pr in self.project_state.rasters.values())
        dialog = RunOptionsDialog(len(self.project_state.rasters) > 1, has_sam_regions, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if dialog.scope_all():
            raster_paths = list(self.project_state.rasters.keys())
        else:
            raster_paths = [self.project_state.active_raster_path] if self.project_state.active_raster_path else []
        if not raster_paths:
            return

        self._inference_worker = InferenceWorker(
            self.project_state,
            raster_paths,
            self.project_state.model,
            tile_size=dialog.tile_size_spin.value(),
            overlap=dialog.overlap_spin.value(),
            conf=dialog.conf_spin.value(),
            sam_filter_mode=dialog.sam_filter_mode(),
        )
        self._inference_worker.progress.connect(self._on_progress)
        self._inference_worker.raster_finished.connect(self._on_raster_finished)
        self._inference_worker.raster_error.connect(self._on_raster_error)
        self._inference_worker.state_changed.connect(self._on_worker_state_changed)
        self._inference_worker.all_finished.connect(self._on_all_finished)

        self.run_action.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.pause_button.setText("Pause")
        self.stop_button.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._inference_worker.start()

    def _on_pause_resume(self) -> None:
        if self._inference_worker is None:
            return
        if self._inference_worker.is_paused():
            self._inference_worker.resume()
        else:
            self._inference_worker.pause()

    def _on_stop(self) -> None:
        if self._inference_worker is None:
            return
        confirm = QMessageBox.question(
            self,
            "Stop detection",
            "Stop the running detection? Progress on the current image will be discarded.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._inference_worker.cancel()

    def _on_worker_state_changed(self, state: str) -> None:
        if state == "paused":
            self.pause_button.setText("Resume")
            self.progress_label.setText("Paused.")
        elif state == "running":
            self.pause_button.setText("Pause")
        elif state == "stopped":
            self.progress_label.setText("Detection stopped.")

    def _on_progress(self, done: int, total: int, image_name: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"Processing: {image_name}  ({done}/{total})")

    def _on_raster_finished(self, raster_path: str, detections: list) -> None:
        pr = self.project_state.rasters.get(raster_path)
        preserved: list = []
        if pr is not None:
            preserved = [d for d in pr.detections if d.source == "manual" or d.edited]
        merged = preserved + list(detections)
        self.project_state.set_detections(raster_path, merged, record_undo=True)
        self.project_state.mark_inference_done(raster_path, True)

    def _on_raster_error(self, raster_path: str, message: str) -> None:
        self.progress_label.setText(f"Error ({Path(raster_path).name}): {message}")

    def _on_all_finished(self) -> None:
        self.run_action.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.pause_button.setText("Pause")
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        if not self.progress_label.text().startswith("Detection stopped"):
            self.progress_label.setText("Detection complete.")
        self._inference_worker = None

    def _on_export(self) -> None:
        if not self.project_state.rasters:
            QMessageBox.warning(self, "No images", "No open image to export.")
            return
        dialog = ExportDialog(self.project_state, self)
        dialog.exec()

    def closeEvent(self, event) -> None:
        for worker in (self._loader, self._sam_worker, self._inference_worker):
            if worker is not None and worker.isRunning():
                if hasattr(worker, "cancel"):
                    worker.cancel()
                worker.wait(3000)
        super().closeEvent(event)
