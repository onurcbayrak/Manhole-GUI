"""Ana pencere: toolbar, dock panelleri, canvas ve tüm modüllerin birleştirilmesi."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSpinBox,
    QTabWidget,
    QToolBar,
)

from sas_manhole_gui.canvas import RasterCanvas
from sas_manhole_gui.dialogs.export_dialog import ExportDialog
from sas_manhole_gui.dialogs.model_load_dialog import ModelLoadDialog
from sas_manhole_gui.inference_worker import InferenceWorker
from sas_manhole_gui.project_state import ProjectState
from sas_manhole_gui.widgets.class_panel import ClassPanel
from sas_manhole_gui.widgets.detection_list import DetectionListPanel
from sas_manhole_gui.widgets.thumbnail_panel import ThumbnailPanel

TIF_FILTER = "GeoTIFF (*.tif *.tiff)"


class RunOptionsDialog(QDialog):
    def __init__(self, has_multiple_rasters: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tespit Ayarları")
        layout = QFormLayout(self)

        self.scope_combo = None
        if has_multiple_rasters:
            from PySide6.QtWidgets import QComboBox

            self.scope_combo = QComboBox()
            self.scope_combo.addItems(["Aktif görüntü", "Açık tüm görüntüler"])
            layout.addRow("Kapsam:", self.scope_combo)

        self.tile_size_spin = QSpinBox()
        self.tile_size_spin.setRange(128, 4096)
        self.tile_size_spin.setSingleStep(32)
        self.tile_size_spin.setValue(640)
        layout.addRow("Kesit boyutu (piksel):", self.tile_size_spin)

        self.overlap_spin = QDoubleSpinBox()
        self.overlap_spin.setRange(0.0, 0.9)
        self.overlap_spin.setSingleStep(0.05)
        self.overlap_spin.setValue(0.2)
        layout.addRow("Kesit örtüşmesi:", self.overlap_spin)

        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.01, 0.99)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.setValue(0.25)
        layout.addRow("Güven eşiği (confidence):", self.conf_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def scope_all(self) -> bool:
        return self.scope_combo is not None and self.scope_combo.currentIndex() == 1


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SAS Manhole GUI — Ortofoto Tespit Arayüzü")
        self.resize(1440, 900)

        self.project_state = ProjectState()
        self._worker: InferenceWorker | None = None

        self.canvas = RasterCanvas(self.project_state, self)
        self.setCentralWidget(self.canvas)

        self.thumbnail_panel = ThumbnailPanel(self.project_state)
        self.class_panel = ClassPanel(self.project_state)
        self.detection_list = DetectionListPanel(self.project_state)

        self._build_docks()
        self._build_toolbar()
        self._build_statusbar()
        self._wire_signals()

    # --- arayüz kurulumu ---------------------------------------------------
    def _build_docks(self) -> None:
        left_dock = QDockWidget("Görüntüler", self)
        left_dock.setWidget(self.thumbnail_panel)
        left_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)

        right_tabs = QTabWidget()
        right_tabs.addTab(self.detection_list, "Tespitler")
        right_tabs.addTab(self.class_panel, "Sınıflar")
        right_dock = QDockWidget("Detaylar", self)
        right_dock.setWidget(right_tabs)
        right_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_dock)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Araçlar", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_files_action = QAction("Dosya(lar) Aç", self)
        open_files_action.triggered.connect(self._on_open_files)
        toolbar.addAction(open_files_action)

        open_folder_action = QAction("Klasör Aç", self)
        open_folder_action.triggered.connect(self._on_open_folder)
        toolbar.addAction(open_folder_action)

        toolbar.addSeparator()

        self.load_model_action = QAction("Model Yükle", self)
        self.load_model_action.triggered.connect(self._on_load_model)
        toolbar.addAction(self.load_model_action)

        self.run_action = QAction("Çalıştır", self)
        self.run_action.setEnabled(False)
        self.run_action.triggered.connect(self._on_run)
        toolbar.addAction(self.run_action)

        toolbar.addSeparator()

        self.draw_action = QAction("Yeni Kutu Çiz", self)
        self.draw_action.setCheckable(True)
        self.draw_action.toggled.connect(self._on_toggle_draw)
        toolbar.addAction(self.draw_action)

        toolbar.addSeparator()

        zoom_in_action = QAction("Yakınlaştır", self)
        zoom_in_action.triggered.connect(self.canvas.zoom_in)
        toolbar.addAction(zoom_in_action)

        zoom_out_action = QAction("Uzaklaştır", self)
        zoom_out_action.triggered.connect(self.canvas.zoom_out)
        toolbar.addAction(zoom_out_action)

        zoom_fit_action = QAction("Sığdır", self)
        zoom_fit_action.triggered.connect(self.canvas.zoom_fit)
        toolbar.addAction(zoom_fit_action)

        toolbar.addSeparator()

        export_action = QAction("Export", self)
        export_action.triggered.connect(self._on_export)
        toolbar.addAction(export_action)

    def _build_statusbar(self) -> None:
        self.model_label = QLabel("Model: yüklenmedi")
        self.statusBar().addWidget(self.model_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(280)
        self.progress_bar.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.statusBar().addPermanentWidget(self.progress_label)

    def _wire_signals(self) -> None:
        self.canvas.detection_selected.connect(self.detection_list.select_detection)
        self.detection_list.detection_activated.connect(self.canvas.select_detection)
        self.class_panel.current_class_changed.connect(self._on_draw_class_changed)
        self.project_state.model_changed.connect(self._on_model_changed)

    # --- dosya açma -------------------------------------------------------
    def _on_open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Ortofoto seç (.tif/.tiff)", "", TIF_FILTER)
        self._open_paths([Path(p) for p in paths])

    def _on_open_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Klasör seç")
        if not directory:
            return
        folder = Path(directory)
        found = sorted(set(folder.glob("*.tif")) | set(folder.glob("*.tiff")))
        if not found:
            QMessageBox.information(self, "Sonuç yok", "Bu klasörde .tif/.tiff dosyası bulunamadı.")
            return
        self._open_paths(found)

    def _open_paths(self, paths: list[Path]) -> None:
        failed = []
        for path in paths:
            if self.project_state.add_raster(path) is None:
                failed.append(path.name)
        if failed:
            QMessageBox.warning(self, "Bazı dosyalar açılamadı", "\n".join(failed))

    # --- model -------------------------------------------------------------
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
            self.model_label.setText("Model: yüklenmedi")
            self.run_action.setEnabled(False)
            return
        name = self.project_state.model_path.name if self.project_state.model_path else "?"
        self.model_label.setText(f"Model: {name}  ({len(self.project_state.classes)} sınıf)")
        self.run_action.setEnabled(True)

    # --- çizim modu ---------------------------------------------------------
    def _on_toggle_draw(self, checked: bool) -> None:
        self.canvas.set_draw_mode(checked, self.class_panel.current_class_id())

    def _on_draw_class_changed(self, class_id: int) -> None:
        if self.draw_action.isChecked():
            self.canvas.set_draw_mode(True, class_id)

    # --- inference -----------------------------------------------------------
    def _on_run(self) -> None:
        if self.project_state.model is None:
            QMessageBox.warning(self, "Model yok", "Önce bir model yükleyin.")
            return
        if not self.project_state.rasters:
            QMessageBox.warning(self, "Görüntü yok", "Önce en az bir görüntü açın.")
            return

        dialog = RunOptionsDialog(len(self.project_state.rasters) > 1, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if dialog.scope_all():
            raster_paths = list(self.project_state.rasters.keys())
        else:
            raster_paths = [self.project_state.active_raster_path] if self.project_state.active_raster_path else []
        if not raster_paths:
            return

        self._worker = InferenceWorker(
            self.project_state,
            raster_paths,
            self.project_state.model,
            tile_size=dialog.tile_size_spin.value(),
            overlap=dialog.overlap_spin.value(),
            conf=dialog.conf_spin.value(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.raster_finished.connect(self._on_raster_finished)
        self._worker.raster_error.connect(self._on_raster_error)
        self._worker.all_finished.connect(self._on_all_finished)

        self.run_action.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._worker.start()

    def _on_progress(self, done: int, total: int, image_name: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"İşleniyor: {image_name}  ({done}/{total})")

    def _on_raster_finished(self, raster_path: str, detections: list) -> None:
        self.project_state.set_detections(raster_path, detections)

    def _on_raster_error(self, raster_path: str, message: str) -> None:
        self.progress_label.setText(f"Hata ({Path(raster_path).name}): {message}")

    def _on_all_finished(self) -> None:
        self.run_action.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Tespit tamamlandı.")
        self._worker = None

    # --- export -------------------------------------------------------------
    def _on_export(self) -> None:
        if not self.project_state.rasters:
            QMessageBox.warning(self, "Görüntü yok", "Export edilecek açık bir görüntü yok.")
            return
        dialog = ExportDialog(self.project_state, self)
        dialog.exec()
