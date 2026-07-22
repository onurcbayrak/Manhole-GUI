"""Sol panel: açık ortofotoların küçük önizlemesi + ismi."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu, QVBoxLayout, QWidget

from sas_manhole_gui.project_state import ProjectState


class ThumbnailPanel(QWidget):
    def __init__(self, project_state: ProjectState, parent=None):
        super().__init__(parent)
        self.project_state = project_state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(96, 96))
        self.list_widget.setSpacing(4)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list_widget)

        project_state.rasters_changed.connect(self.refresh)
        project_state.active_raster_changed.connect(self._sync_selection)

    def refresh(self) -> None:
        self.list_widget.clear()
        for path, pr in self.project_state.rasters.items():
            try:
                thumb = pr.layer.thumbnail(120)
                pixmap = QPixmap.fromImage(thumb)
            except Exception:
                pixmap = QPixmap()
            item = QListWidgetItem(QIcon(pixmap), pr.name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.list_widget.addItem(item)
        self._sync_selection(self.project_state.active_raster_path or "")

    def _sync_selection(self, active_path: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) == active_path)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        self.project_state.set_active_raster(path)

    def _on_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        remove_action = menu.addAction("Kaldır")
        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen == remove_action:
            self.project_state.remove_raster(path)
