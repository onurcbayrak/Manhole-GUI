"""Aktif görüntüdeki tespitlerin listesi -- canvas seçimiyle senkron."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from sas_manhole_gui.project_state import ProjectState


class DetectionListPanel(QWidget):
    detection_activated = Signal(object)  # det_id

    def __init__(self, project_state: ProjectState, parent=None):
        super().__init__(parent)
        self.project_state = project_state
        self._raster_path: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.title_label = QLabel("Tespitler (0)")
        layout.addWidget(self.title_label)
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget)

        project_state.active_raster_changed.connect(self._on_active_changed)
        project_state.detections_changed.connect(self._on_detections_changed)
        project_state.classes_changed.connect(self.refresh)

    def _on_active_changed(self, path: str) -> None:
        self._raster_path = path or None
        self.refresh()

    def _on_detections_changed(self, path: str) -> None:
        if path == self._raster_path:
            self.refresh()

    def refresh(self) -> None:
        self.list_widget.clear()
        pr = self.project_state.rasters.get(self._raster_path) if self._raster_path else None
        detections = pr.detections if pr else []
        self.title_label.setText(f"Tespitler ({len(detections)})")
        for det in detections:
            color = self.project_state.class_color(det.class_id)
            name = self.project_state.class_name(det.class_id)
            pix = QPixmap(12, 12)
            pix.fill(QColor(color))
            suffix = " *" if det.edited else ""
            if det.source == "model":
                label = f"{name}  {det.confidence:.2f}{suffix}"
            else:
                label = f"{name}  (elle){suffix}"
            item = QListWidgetItem(QIcon(pix), label)
            item.setData(Qt.ItemDataRole.UserRole, det.det_id)
            self.list_widget.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.detection_activated.emit(item.data(Qt.ItemDataRole.UserRole))

    def select_detection(self, det_id) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) == det_id)
