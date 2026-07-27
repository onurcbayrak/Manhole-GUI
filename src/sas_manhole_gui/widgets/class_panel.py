from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from sas_manhole_gui.project_state import ProjectState


class ClassPanel(QWidget):
    current_class_changed = Signal(int)

    def __init__(self, project_state: ProjectState, parent=None):
        super().__init__(parent)
        self.project_state = project_state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        label = QLabel("Active class — used for new boxes (synced with the Detections tab):")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list_widget)

        project_state.classes_changed.connect(self.refresh)

    def refresh(self) -> None:
        self.list_widget.clear()
        for c in self.project_state.classes:
            pix = QPixmap(14, 14)
            pix.fill(QColor(c.color))
            item = QListWidgetItem(QIcon(pix), c.name)
            item.setData(Qt.ItemDataRole.UserRole, c.class_id)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.list_widget.item(row)
        if item is None:
            return
        self.current_class_changed.emit(item.data(Qt.ItemDataRole.UserRole))

    def current_class_id(self) -> int:
        item = self.list_widget.currentItem()
        if item is None:
            return 0
        return item.data(Qt.ItemDataRole.UserRole)

    def set_current_class(self, class_id: int) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) != class_id:
                continue
            if self.list_widget.currentRow() == row:
                return
            self.list_widget.blockSignals(True)
            try:
                self.list_widget.setCurrentRow(row)
            finally:
                self.list_widget.blockSignals(False)
            return
