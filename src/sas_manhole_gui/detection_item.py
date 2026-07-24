from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsSceneContextMenuEvent,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QMenu,
    QStyleOptionGraphicsItem,
    QWidget,
)


class DetectionItem(QGraphicsRectItem):
    MIN_SIZE = 4.0

    _CURSORS = {
        "tl": Qt.CursorShape.SizeFDiagCursor,
        "br": Qt.CursorShape.SizeFDiagCursor,
        "tr": Qt.CursorShape.SizeBDiagCursor,
        "bl": Qt.CursorShape.SizeBDiagCursor,
        "t": Qt.CursorShape.SizeVerCursor,
        "b": Qt.CursorShape.SizeVerCursor,
        "l": Qt.CursorShape.SizeHorCursor,
        "r": Qt.CursorShape.SizeHorCursor,
    }

    def __init__(
        self,
        det_id: int,
        rect: QRectF,
        color: str,
        label: str,
        on_change: Optional[Callable[[int, QRectF], None]] = None,
        on_delete: Optional[Callable[[int], None]] = None,
        on_class_change: Optional[Callable[[int, int], None]] = None,
        classes_provider: Optional[Callable[[], list[tuple[int, str, str]]]] = None,
    ):
        super().__init__(rect)
        self.det_id = det_id
        self.setPos(0, 0)
        self._color = QColor(color)
        self._label = label
        self._active_handle: Optional[str] = None
        self._drag_mode: Optional[str] = None
        self._drag_start_scene: Optional[QPointF] = None
        self._drag_start_rect: Optional[QRectF] = None
        self._on_change = on_change
        self._on_delete = on_delete
        self._on_class_change = on_class_change
        self._classes_provider = classes_provider
        self._hovered = False
        self._hover_enabled = True

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setZValue(10)

    def set_style(self, color: str, label: str) -> None:
        self._color = QColor(color)
        self._label = label
        self.update()

    def set_hover_enabled(self, enabled: bool) -> None:
        self._hover_enabled = enabled
        self.setAcceptHoverEvents(enabled)
        if not enabled and self._hovered:
            self._hovered = False
            self.update()

    def _view_scale(self) -> float:
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views:
                return max(views[0].transform().m11(), 0.0001)
        return 1.0

    def _handle_radius(self) -> float:
        return max(3.0, 7.0 / self._view_scale())

    def boundingRect(self) -> QRectF:
        margin = self._handle_radius() + 4
        return self.rect().adjusted(-margin, -margin - 20 / self._view_scale(), margin, margin)

    def _handle_points(self, r: QRectF) -> dict[str, QPointF]:
        cx, cy = r.center().x(), r.center().y()
        return {
            "tl": QPointF(r.left(), r.top()),
            "t": QPointF(cx, r.top()),
            "tr": QPointF(r.right(), r.top()),
            "r": QPointF(r.right(), cy),
            "br": QPointF(r.right(), r.bottom()),
            "b": QPointF(cx, r.bottom()),
            "bl": QPointF(r.left(), r.bottom()),
            "l": QPointF(r.left(), cy),
        }

    def _handle_at(self, pos: QPointF) -> Optional[str]:
        if not self.isSelected():
            return None
        hr = self._handle_radius() * 1.8
        for name, pt in self._handle_points(self.rect()).items():
            d = ((pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2) ** 0.5
            if d <= hr:
                return name
        return None

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None) -> None:
        r = self.rect()
        scale = self._view_scale()
        pen_width = max(1.0, 2.0 / scale)
        if self._hovered and not self.isSelected():
            pen_width *= 1.6
        painter.setPen(QPen(self._color, pen_width))
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawRect(r)

        if self.isSelected() or self._hovered:
            fill = QColor(self._color)
            fill.setAlpha(65 if self.isSelected() else 32)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fill))
            painter.drawRect(r)

        font = painter.font()
        font_size = max(6.0, 10.0 / scale)
        font.setPointSizeF(font_size)
        painter.setFont(font)
        label_h = font_size * 1.7
        label_w = max(r.width(), len(self._label) * font_size * 0.65)
        text_rect = QRectF(r.left(), r.top() - label_h, label_w, label_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawRect(text_rect)
        painter.setPen(QPen(QColor("#101010")))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self._label)

        if self.isSelected():
            hr = self._handle_radius()
            painter.setPen(QPen(QColor("#ffffff"), max(1.0, 1.0 / scale)))
            painter.setBrush(QBrush(self._color))
            for _, pt in self._handle_points(r).items():
                painter.drawEllipse(pt, hr, hr)

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        if self._hover_enabled:
            self._hovered = True
            self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        if self._hovered:
            self._hovered = False
            self.update()
        super().hoverLeaveEvent(event)

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        handle = self._handle_at(event.pos())
        if handle:
            self.setCursor(QCursor(self._CURSORS[handle]))
        elif self.isSelected():
            self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.setSelected(True)
            if event.button() == Qt.MouseButton.LeftButton:
                handle = self._handle_at(event.pos())
                self._drag_start_scene = event.scenePos()
                self._drag_start_rect = QRectF(self.rect())
                self._active_handle = handle
                self._drag_mode = "resize" if handle else "move"
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag_mode is None or self._drag_start_scene is None or self._drag_start_rect is None:
            super().mouseMoveEvent(event)
            return
        delta = event.scenePos() - self._drag_start_scene
        r = QRectF(self._drag_start_rect)
        if self._drag_mode == "move":
            r.translate(delta.x(), delta.y())
        else:
            self._apply_resize(r, self._active_handle, delta)
        if r.width() < self.MIN_SIZE:
            r.setWidth(self.MIN_SIZE)
        if r.height() < self.MIN_SIZE:
            r.setHeight(self.MIN_SIZE)
        self.prepareGeometryChange()
        self.setRect(r.normalized())
        event.accept()

    def _apply_resize(self, r: QRectF, handle: Optional[str], delta: QPointF) -> None:
        if handle in ("tl", "t", "tr"):
            r.setTop(r.top() + delta.y())
        if handle in ("bl", "b", "br"):
            r.setBottom(r.bottom() + delta.y())
        if handle in ("tl", "l", "bl"):
            r.setLeft(r.left() + delta.x())
        if handle in ("tr", "r", "br"):
            r.setRight(r.right() + delta.x())

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        had_drag = self._drag_mode is not None
        self._drag_mode = None
        self._active_handle = None
        self._drag_start_scene = None
        self._drag_start_rect = None
        if had_drag and self._on_change is not None:
            self._on_change(self.det_id, self.rect())
        event.accept()

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent) -> None:
        self.setSelected(True)
        menu = QMenu()
        delete_action = menu.addAction("Delete")
        class_menu = menu.addMenu("Change Class")
        class_actions = {}
        if self._classes_provider:
            for class_id, name, _color in self._classes_provider():
                act = class_menu.addAction(name)
                class_actions[act] = class_id
        chosen = menu.exec(event.screenPos())
        if chosen is None:
            return
        if chosen == delete_action and self._on_delete:
            self._on_delete(self.det_id)
        elif chosen in class_actions and self._on_class_change:
            self._on_class_change(self.det_id, class_actions[chosen])
