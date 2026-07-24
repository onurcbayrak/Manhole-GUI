from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from sas_manhole_gui.project_state import ProjectState
from sas_manhole_gui.style import SAM_COLOR


class SamPanel(QWidget):
    segment_requested = Signal(str, float, str)

    def __init__(self, project_state: ProjectState, parent=None):
        super().__init__(parent)
        self.project_state = project_state
        self._raster_path: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        self.status_label = QLabel("SAM: not loaded")
        self.status_label.setStyleSheet("color: #9aa0a8;")
        layout.addWidget(self.status_label)

        query_box = QGroupBox("Text Segmentation")
        q_form = QFormLayout(query_box)
        q_form.setContentsMargins(8, 12, 8, 8)

        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("e.g. road, vegetation, building")
        self.text_edit.returnPressed.connect(self._emit_segment)
        q_form.addRow("Prompt:", self.text_edit)

        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.05, 0.99)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.setValue(0.25)
        q_form.addRow("Confidence:", self.conf_spin)

        scope_row = QHBoxLayout()
        self.scope_visible = QRadioButton("Visible area")
        self.scope_visible.setChecked(True)
        self.scope_full = QRadioButton("Full image")
        self._scope_group = QButtonGroup(self)
        self._scope_group.addButton(self.scope_visible)
        self._scope_group.addButton(self.scope_full)
        scope_row.addWidget(self.scope_visible)
        scope_row.addWidget(self.scope_full)
        scope_row.addStretch(1)
        q_form.addRow("Region:", scope_row)

        self.segment_btn = QPushButton("Segment")
        self.segment_btn.setObjectName("primaryButton")
        self.segment_btn.clicked.connect(self._emit_segment)
        q_form.addRow(self.segment_btn)

        layout.addWidget(query_box)

        results_box = QGroupBox("SAM Regions (current image)")
        r_layout = QVBoxLayout(results_box)
        r_layout.setContentsMargins(8, 12, 8, 8)
        self.results_list = QListWidget()
        r_layout.addWidget(self.results_list)

        btn_row = QHBoxLayout()
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self._on_delete_selected)
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self._on_clear_all)
        btn_row.addWidget(self.delete_btn)
        btn_row.addWidget(self.clear_btn)
        r_layout.addLayout(btn_row)

        layout.addWidget(results_box, 1)

        project_state.sam_model_changed.connect(self._on_sam_model_changed)
        project_state.active_raster_changed.connect(self._on_active_changed)
        project_state.sam_regions_changed.connect(self._on_sam_regions_changed)

        self._on_sam_model_changed()
        self._update_button_state()

    def _on_sam_model_changed(self) -> None:
        sam = self.project_state.sam
        if sam is None:
            self.status_label.setText("SAM: not loaded — click 'Load SAM' in the toolbar.")
        else:
            self.status_label.setText(f"SAM: {sam.path.name}  ({sam.kind})")
        self._update_button_state()

    def _on_active_changed(self, path: str) -> None:
        self._raster_path = path or None
        self._refresh_results()

    def _on_sam_regions_changed(self, path: str) -> None:
        if path == self._raster_path:
            self._refresh_results()

    def _refresh_results(self) -> None:
        self.results_list.clear()
        pr = self.project_state.rasters.get(self._raster_path) if self._raster_path else None
        regions = pr.sam_regions if pr else []
        for region in regions:
            pix = QPixmap(12, 12)
            pix.fill(QColor(SAM_COLOR))
            label = f"{region.text or 'segment'}  {region.confidence:.2f}"
            item = QListWidgetItem(QIcon(pix), label)
            item.setData(Qt.ItemDataRole.UserRole, region.region_id)
            self.results_list.addItem(item)
        self._update_button_state()

    def _update_button_state(self) -> None:
        has_sam = self.project_state.sam is not None
        has_raster = self._raster_path is not None
        self.segment_btn.setEnabled(has_sam and has_raster)
        self.text_edit.setEnabled(has_sam and has_raster)
        count = self.results_list.count()
        self.delete_btn.setEnabled(count > 0)
        self.clear_btn.setEnabled(count > 0)

    def _emit_segment(self) -> None:
        text = self.text_edit.text().strip()
        if not text:
            return
        if self.project_state.sam is None or self._raster_path is None:
            return
        scope = "full" if self.scope_full.isChecked() else "visible"
        self.segment_requested.emit(text, float(self.conf_spin.value()), scope)

    def _on_delete_selected(self) -> None:
        item = self.results_list.currentItem()
        if item is None or self._raster_path is None:
            return
        region_id = item.data(Qt.ItemDataRole.UserRole)
        self.project_state.remove_sam_region(self._raster_path, region_id)

    def _on_clear_all(self) -> None:
        if self._raster_path is None:
            return
        self.project_state.clear_sam_regions(self._raster_path)
