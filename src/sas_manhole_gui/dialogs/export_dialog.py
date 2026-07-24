from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)
from PySide6.QtCore import Qt

from sas_manhole_gui import export_manager
from sas_manhole_gui.project_state import ProjectState

_VISUAL_EXTS = {"PNG": ".png", "JPEG": ".jpg", "GeoTIFF (georeferenced)": ".tif"}


class ExportDialog(QDialog):
    def __init__(self, project_state: ProjectState, parent=None):
        super().__init__(parent)
        self.project_state = project_state
        self.setWindowTitle("Export")
        self.resize(480, 420)
        self._last_out_dir: Path | None = None

        layout = QVBoxLayout(self)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Scope:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["Active image", "All open images"])
        scope_row.addWidget(self.scope_combo, 1)
        layout.addLayout(scope_row)

        out_row = QHBoxLayout()
        self.out_dir_edit = QLineEdit()
        self.out_dir_edit.setPlaceholderText("Select output folder...")
        out_browse = QPushButton("Select Folder...")
        out_browse.clicked.connect(self._browse_out_dir)
        out_row.addWidget(self.out_dir_edit, 1)
        out_row.addWidget(out_browse)
        layout.addLayout(out_row)

        visual_box = QGroupBox("Visual Export")
        visual_box.setCheckable(True)
        visual_box.setChecked(True)
        self.visual_box = visual_box
        v_layout = QVBoxLayout(visual_box)
        self.radio_full = QRadioButton("Full image ({name}_detections.<ext>)")
        self.radio_full.setChecked(True)
        self.radio_tiles = QRadioButton("640x640 tiles ({name}_tile_rXXX_cXXX_640x640.<ext>)")
        v_layout.addWidget(self.radio_full)
        v_layout.addWidget(self.radio_tiles)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self.visual_format_combo = QComboBox()
        self.visual_format_combo.addItems(list(_VISUAL_EXTS.keys()))
        fmt_row.addWidget(self.visual_format_combo, 1)
        v_layout.addLayout(fmt_row)
        layout.addWidget(visual_box)

        vector_box = QGroupBox("GIS Export — final state of detections")
        vector_box.setCheckable(True)
        vector_box.setChecked(True)
        self.vector_box = vector_box
        vec_layout = QVBoxLayout(vector_box)
        self.shp_checkbox = QCheckBox(".shp (Shapefile)")
        self.shp_checkbox.setChecked(True)
        self.csv_checkbox = QCheckBox(".csv")
        self.csv_checkbox.setChecked(True)
        self.geojson_checkbox = QCheckBox(".geojson")
        self.gpkg_checkbox = QCheckBox(".gpkg (GeoPackage)")
        for cb in (self.shp_checkbox, self.csv_checkbox, self.geojson_checkbox, self.gpkg_checkbox):
            vec_layout.addWidget(cb)
        layout.addWidget(vector_box)

        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_export)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_out_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select output folder")
        if directory:
            self.out_dir_edit.setText(directory)

    def _selected_rasters(self):
        if self.scope_combo.currentIndex() == 0:
            pr = self.project_state.active_raster
            return [pr] if pr else []
        return list(self.project_state.rasters.values())

    def _on_export(self) -> None:
        out_dir_str = self.out_dir_edit.text().strip()
        if not out_dir_str:
            QMessageBox.warning(self, "Missing information", "Please select an output folder.")
            return
        out_dir = Path(out_dir_str)
        rasters = self._selected_rasters()
        if not rasters:
            QMessageBox.warning(self, "Missing information", "No open image to export.")
            return
        if not self.visual_box.isChecked() and not self.vector_box.isChecked():
            QMessageBox.warning(self, "Missing information", "Select at least one export type (Visual or GIS).")
            return

        formats = set()
        if self.vector_box.isChecked():
            if self.shp_checkbox.isChecked():
                formats.add("shp")
            if self.csv_checkbox.isChecked():
                formats.add("csv")
            if self.geojson_checkbox.isChecked():
                formats.add("geojson")
            if self.gpkg_checkbox.isChecked():
                formats.add("gpkg")
            if not formats:
                QMessageBox.warning(self, "Missing information", "Select at least one format for GIS export.")
                return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        outputs: list[Path] = []
        errors: list[str] = []
        try:
            if self.visual_box.isChecked():
                ext = _VISUAL_EXTS[self.visual_format_combo.currentText()]
                for pr in rasters:
                    try:
                        if self.radio_full.isChecked():
                            outputs.append(export_manager.export_visual_full(pr, out_dir, self.project_state.classes, ext=ext))
                        else:
                            outputs.extend(export_manager.export_visual_tiles(pr, out_dir, self.project_state.classes, ext=ext))
                    except Exception as exc:
                        errors.append(f"{pr.name}: {exc}")

            if self.vector_box.isChecked():
                try:
                    stem = rasters[0].path.stem if len(rasters) == 1 else "all_images"
                    outputs.extend(export_manager.export_vector(rasters, self.project_state.classes, out_dir, stem, formats))
                except Exception as exc:
                    errors.append(f"GIS export: {exc}")
        finally:
            QApplication.restoreOverrideCursor()

        self._last_out_dir = out_dir
        message = f"{len(outputs)} files created:\n" + "\n".join(p.name for p in outputs[:20])
        if len(outputs) > 20:
            message += f"\n... (+{len(outputs) - 20} more files)"
        if errors:
            message += "\n\nErrors:\n" + "\n".join(errors)
        box = QMessageBox(self)
        box.setWindowTitle("Export complete" if not errors else "Export partially complete")
        box.setText(message)
        open_btn = box.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() == open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_dir)))

        self.accept()
