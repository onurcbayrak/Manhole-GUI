from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sas_manhole_gui.project_state import ProjectState
from sas_manhole_gui.style import ACCENT, SUCCESS


class ThumbnailPanel(QWidget):
    def __init__(self, project_state: ProjectState, parent=None):
        super().__init__(parent)
        self.project_state = project_state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(96, 96))
        self.list_widget.setSpacing(4)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemSelectionChanged.connect(self._update_button_state)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self._on_remove_selected)
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self._on_clear_all)
        btn_row.addWidget(self.remove_btn)
        btn_row.addWidget(self.clear_btn)
        layout.addLayout(btn_row)

        self._items_by_path: dict[str, QListWidgetItem] = {}
        self._badge_state: dict[str, tuple[bool, bool]] = {}
        self._syncing_selection = False

        project_state.rasters_changed.connect(self.refresh)
        project_state.active_raster_changed.connect(self._sync_selection)
        project_state.raster_status_changed.connect(self._refresh_one)
        project_state.detections_changed.connect(self._refresh_one)

        self._update_button_state()

    def refresh(self) -> None:
        self.list_widget.clear()
        self._items_by_path.clear()
        self._badge_state.clear()
        for path, pr in self.project_state.rasters.items():
            item = QListWidgetItem(pr.name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            state = (pr.inference_done, len(pr.detections) > 0)
            item.setIcon(self._build_icon(pr.thumbnail, state[0], state[1]))
            self._badge_state[path] = state
            self.list_widget.addItem(item)
            self._items_by_path[path] = item
        self._sync_selection(self.project_state.active_raster_path or "")
        self._update_button_state()

    def _refresh_one(self, path: str) -> None:
        item = self._items_by_path.get(path)
        pr = self.project_state.rasters.get(path)
        if item is None or pr is None:
            return
        state = (pr.inference_done, len(pr.detections) > 0)
        if self._badge_state.get(path) == state:
            return
        self._badge_state[path] = state
        item.setIcon(self._build_icon(pr.thumbnail, state[0], state[1]))

    def _build_icon(self, thumbnail, done: bool, has_detections: bool) -> QIcon:
        base = QPixmap.fromImage(thumbnail) if thumbnail is not None else QPixmap(96, 96)
        if base.isNull():
            base = QPixmap(96, 96)
            base.fill(Qt.GlobalColor.transparent)
        if not done:
            return QIcon(base)

        overlay = QPixmap(base)
        painter = QPainter(overlay)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = overlay.width()
        h = overlay.height()
        badge_r = max(12, int(min(w, h) * 0.18))
        cx = w - badge_r - 4
        cy = h - badge_r - 4

        if has_detections:
            painter.setPen(QPen(QColor("#101010"), 1))
            painter.setBrush(QBrush(QColor(SUCCESS)))
            painter.drawEllipse(QPointF(cx, cy), badge_r, badge_r)
            pen = QPen(QColor("#101010"))
            pen.setWidth(max(2, badge_r // 4))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            p1 = QPointF(cx - badge_r * 0.45, cy)
            p2 = QPointF(cx - badge_r * 0.1, cy + badge_r * 0.35)
            p3 = QPointF(cx + badge_r * 0.5, cy - badge_r * 0.35)
            painter.drawPolyline([p1, p2, p3])
        else:
            painter.setPen(QPen(QColor("#101010"), 1))
            painter.setBrush(QBrush(QColor(ACCENT)))
            painter.drawEllipse(QPointF(cx, cy), badge_r, badge_r)
            slash = QPen(QColor("#ffffff"))
            slash.setWidth(max(2, badge_r // 4))
            slash.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(slash)
            offset = badge_r * 0.55
            painter.drawLine(
                QPointF(cx - offset, cy - offset),
                QPointF(cx + offset, cy + offset),
            )
        painter.end()
        return QIcon(overlay)

    def _sync_selection(self, active_path: str) -> None:
        self._syncing_selection = True
        try:
            self.list_widget.clearSelection()
            if active_path:
                item = self._items_by_path.get(active_path)
                if item is not None:
                    item.setSelected(True)
                    self.list_widget.setCurrentItem(item)
        finally:
            self._syncing_selection = False

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            self._update_button_state()
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        self.project_state.set_active_raster(path)
        self._update_button_state()

    def _on_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        remove_action = menu.addAction("Remove")
        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen == remove_action:
            self.project_state.remove_raster(path)

    def _on_remove_selected(self) -> None:
        paths = [item.data(Qt.ItemDataRole.UserRole) for item in self.list_widget.selectedItems()]
        if not paths:
            return
        for path in paths:
            self.project_state.remove_raster(path)

    def _on_clear_all(self) -> None:
        if not self.project_state.rasters:
            return
        self.project_state.clear_rasters()

    def _update_button_state(self) -> None:
        has_any = bool(self.project_state.rasters)
        has_selection = len(self.list_widget.selectedItems()) > 0
        self.clear_btn.setEnabled(has_any)
        self.remove_btn.setEnabled(has_selection)
