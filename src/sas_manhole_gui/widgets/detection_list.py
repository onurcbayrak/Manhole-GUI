from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sas_manhole_gui.project_state import ProjectState


class DetectionListPanel(QWidget):
    detection_activated = Signal(object)
    active_class_changed = Signal(int)

    def __init__(self, project_state: ProjectState, parent=None):
        super().__init__(parent)
        self.project_state = project_state
        self._raster_path: str | None = None
        self._suppress_combo_signal = False
        self._refresh_pending = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.title_label = QLabel("Detections (0)")
        layout.addWidget(self.title_label)

        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.list_widget)

        class_row = QHBoxLayout()
        class_row.addWidget(QLabel("Class:"))
        self.class_combo = QComboBox()
        self.class_combo.setToolTip(
            "Class of the selected detection. With nothing selected this is the class used for new boxes."
        )
        self.class_combo.currentIndexChanged.connect(self._on_combo_class_changed)
        class_row.addWidget(self.class_combo, 1)
        layout.addLayout(class_row)

        self.delete_btn = QPushButton("Delete Selected  (Del)")
        self.delete_btn.clicked.connect(self._on_delete_selected)
        layout.addWidget(self.delete_btn)

        project_state.active_raster_changed.connect(self._on_active_changed)
        project_state.detections_changed.connect(self._on_detections_changed)
        project_state.classes_changed.connect(self._on_classes_changed)

        self._refresh_class_combo()
        self._update_action_state()

    def _on_active_changed(self, path: str) -> None:
        self._raster_path = path or None
        self.refresh()

    def _on_detections_changed(self, path: str) -> None:
        if path != self._raster_path or self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._deferred_refresh)

    def _deferred_refresh(self) -> None:
        self._refresh_pending = False
        self.refresh()

    def _on_classes_changed(self) -> None:
        self._refresh_class_combo()
        self.refresh()

    def _refresh_class_combo(self) -> None:
        self._suppress_combo_signal = True
        try:
            self.class_combo.clear()
            for c in self.project_state.classes:
                self.class_combo.addItem(c.name, c.class_id)
        finally:
            self._suppress_combo_signal = False

    def refresh(self) -> None:
        previous_id = self._selected_det_id()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        pr = self.project_state.rasters.get(self._raster_path) if self._raster_path else None
        detections = pr.detections if pr else []
        self.title_label.setText(f"Detections ({len(detections)})")
        for det in detections:
            color = self.project_state.class_color(det.class_id)
            name = self.project_state.class_name(det.class_id)
            pix = QPixmap(12, 12)
            pix.fill(QColor(color))
            suffix = " *" if det.edited else ""
            if det.source == "model":
                label = f"{name}  {det.confidence:.2f}{suffix}"
            else:
                label = f"{name}  (manual){suffix}"
            item = QListWidgetItem(QIcon(pix), label)
            item.setData(Qt.ItemDataRole.UserRole, det.det_id)
            self.list_widget.addItem(item)
            if det.det_id == previous_id:
                self.list_widget.setCurrentItem(item)
                item.setSelected(True)
        self.list_widget.blockSignals(False)
        self._update_action_state()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.detection_activated.emit(item.data(Qt.ItemDataRole.UserRole))

    def _on_current_changed(self, _current: QListWidgetItem, _previous: QListWidgetItem) -> None:
        self._update_action_state()

    def _update_action_state(self) -> None:
        item = self.list_widget.currentItem()
        has_selection = item is not None
        self.delete_btn.setEnabled(has_selection)
        self.class_combo.setEnabled(self.class_combo.count() > 0)
        if not has_selection:
            return
        det_id = item.data(Qt.ItemDataRole.UserRole)
        pr = self.project_state.rasters.get(self._raster_path) if self._raster_path else None
        det = next((d for d in pr.detections if d.det_id == det_id), None) if pr else None
        if det is not None:
            idx = self.class_combo.findData(det.class_id)
            if idx >= 0 and self.class_combo.currentIndex() != idx:
                self._suppress_combo_signal = True
                try:
                    self.class_combo.setCurrentIndex(idx)
                finally:
                    self._suppress_combo_signal = False
                self.active_class_changed.emit(det.class_id)

    def _selected_det_id(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_delete_selected(self) -> None:
        det_id = self._selected_det_id()
        if det_id is None or self._raster_path is None:
            return
        self.project_state.remove_detection(self._raster_path, det_id)

    def current_class_id(self) -> int | None:
        return self.class_combo.currentData()

    def set_current_class(self, class_id: int) -> None:
        idx = self.class_combo.findData(class_id)
        if idx < 0 or idx == self.class_combo.currentIndex():
            return
        self._suppress_combo_signal = True
        try:
            self.class_combo.setCurrentIndex(idx)
        finally:
            self._suppress_combo_signal = False

    def _on_combo_class_changed(self, idx: int) -> None:
        if self._suppress_combo_signal or idx < 0:
            return
        class_id = self.class_combo.itemData(idx)
        if class_id is None:
            return

        self.active_class_changed.emit(class_id)

        det_id = self._selected_det_id()
        if det_id is None or self._raster_path is None:
            return
        pr = self.project_state.rasters.get(self._raster_path)
        det = next((d for d in pr.detections if d.det_id == det_id), None) if pr else None
        if det is not None and det.class_id == class_id:
            return
        self.project_state.update_detection_class(self._raster_path, det_id, class_id)

    def select_detection(self, det_id) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            match = item.data(Qt.ItemDataRole.UserRole) == det_id
            item.setSelected(match)
            if match:
                self.list_widget.setCurrentItem(item)
        if det_id is None:
            self.list_widget.setCurrentItem(None)
        self._update_action_state()
