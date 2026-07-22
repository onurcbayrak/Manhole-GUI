"""Ortofoto görüntüleme + tespit düzenleme tuvali (QGIS/ArcGIS benzeri pan/zoom)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTransform, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)
from PySide6.QtGui import QPixmap

from sas_manhole_gui.detection_item import DetectionItem
from sas_manhole_gui.project_state import Detection, ProjectState
from sas_manhole_gui.raster_layer import PixelWindow
from sas_manhole_gui.style import BG_DARK


class RasterCanvas(QGraphicsView):
    detection_selected = Signal(object)  # Optional[int]

    def __init__(self, project_state: ProjectState, parent=None):
        super().__init__(parent)
        self.project_state = project_state

        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor(BG_DARK))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self._raster = None
        self._raster_path: Optional[str] = None
        self._base_item: Optional[QGraphicsPixmapItem] = None
        self._detail_item: Optional[QGraphicsPixmapItem] = None
        self._detection_items: dict[int, DetectionItem] = {}

        self._lod_timer = QTimer(self)
        self._lod_timer.setSingleShot(True)
        self._lod_timer.setInterval(150)
        self._lod_timer.timeout.connect(self._refresh_detail_lod)

        self._draw_mode = False
        self._draw_class_id = 0
        self._drawing = False
        self._draw_start: Optional[QPointF] = None
        self._draw_temp_item: Optional[QGraphicsRectItem] = None

        self._panning = False
        self._pan_start = None

        self.horizontalScrollBar().valueChanged.connect(self._schedule_lod_refresh)
        self.verticalScrollBar().valueChanged.connect(self._schedule_lod_refresh)
        self.scene_.selectionChanged.connect(self._emit_selection)

        project_state.active_raster_changed.connect(self.set_active_raster)
        project_state.detections_changed.connect(self._on_detections_changed)
        project_state.classes_changed.connect(self._on_classes_changed)

    # --- raster yükleme --------------------------------------------------
    def set_active_raster(self, path: str) -> None:
        self._raster_path = path or None
        self.scene_.clear()
        self._detection_items.clear()
        self._base_item = None
        self._detail_item = None

        pr = self.project_state.rasters.get(path) if path else None
        if pr is None:
            self._raster = None
            return

        self._raster = pr.layer
        self.scene_.setSceneRect(0, 0, self._raster.width, self._raster.height)

        img = self._raster.full_view_qimage(max_dim=2048)
        pix = QPixmap.fromImage(img)
        self._base_item = QGraphicsPixmapItem(pix)
        if pix.width() and pix.height():
            self._base_item.setTransform(
                QTransform().scale(self._raster.width / pix.width(), self._raster.height / pix.height())
            )
        self._base_item.setZValue(0)
        self.scene_.addItem(self._base_item)

        self._rebuild_detection_items(pr.detections)
        self.fitInView(self.scene_.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._schedule_lod_refresh()

    # --- tespit item senkronizasyonu --------------------------------------
    def _current_detections(self) -> list[Detection]:
        pr = self.project_state.rasters.get(self._raster_path) if self._raster_path else None
        return pr.detections if pr else []

    def _find_detection(self, det_id: int) -> Optional[Detection]:
        for d in self._current_detections():
            if d.det_id == det_id:
                return d
        return None

    def _rebuild_detection_items(self, detections: list[Detection]) -> None:
        for det in detections:
            self._add_detection_item(det)

    def _add_detection_item(self, det: Detection) -> None:
        color = self.project_state.class_color(det.class_id)
        name = self.project_state.class_name(det.class_id)
        label = f"{name} {det.confidence:.2f}" if det.source == "model" else name
        rect = QRectF(det.x_min, det.y_min, det.width(), det.height())
        item = DetectionItem(
            det.det_id,
            rect,
            color,
            label,
            on_change=self._handle_item_changed,
            on_delete=self._handle_item_delete,
            on_class_change=self._handle_item_class_change,
            classes_provider=self._classes_for_menu,
        )
        self.scene_.addItem(item)
        self._detection_items[det.det_id] = item

    def _classes_for_menu(self) -> list[tuple[int, str, str]]:
        return [(c.class_id, c.name, c.color) for c in self.project_state.classes]

    def _handle_item_changed(self, det_id: int, rect: QRectF) -> None:
        det = self._find_detection(det_id)
        if det is None or self._raster is None or self._raster_path is None:
            return
        raster_rect = QRectF(0, 0, self._raster.width, self._raster.height)
        clamped = rect.intersected(raster_rect)
        det.x_min, det.y_min, det.x_max, det.y_max = clamped.left(), clamped.top(), clamped.right(), clamped.bottom()
        det.edited = True
        self.project_state.notify_detections_edited(self._raster_path)

    def _handle_item_delete(self, det_id: int) -> None:
        if self._raster_path is None:
            return
        self.project_state.remove_detection(self._raster_path, det_id)

    def _handle_item_class_change(self, det_id: int, class_id: int) -> None:
        det = self._find_detection(det_id)
        if det is None or self._raster_path is None:
            return
        det.class_id = class_id
        det.edited = True
        self.project_state.notify_detections_edited(self._raster_path)

    def _on_detections_changed(self, raster_path: str) -> None:
        if raster_path != self._raster_path:
            return
        QTimer.singleShot(0, self._sync_detection_items)

    def _sync_detection_items(self) -> None:
        if self._raster_path is None:
            return
        for item in list(self._detection_items.values()):
            self.scene_.removeItem(item)
        self._detection_items.clear()
        self._rebuild_detection_items(self._current_detections())

    def _on_classes_changed(self) -> None:
        for det_id, item in self._detection_items.items():
            det = self._find_detection(det_id)
            if det is None:
                continue
            name = self.project_state.class_name(det.class_id)
            label = f"{name} {det.confidence:.2f}" if det.source == "model" else name
            item.set_style(self.project_state.class_color(det.class_id), label)

    def _emit_selection(self) -> None:
        selected = [item.det_id for item in self.scene_.selectedItems() if isinstance(item, DetectionItem)]
        self.detection_selected.emit(selected[0] if selected else None)

    def select_detection(self, det_id: Optional[int]) -> None:
        for did, item in self._detection_items.items():
            item.setSelected(did == det_id)
        if det_id is not None and det_id in self._detection_items:
            self.centerOn(self._detection_items[det_id])

    # --- çizim modu (yeni kutu) --------------------------------------------
    def set_draw_mode(self, enabled: bool, class_id: int = 0) -> None:
        self._draw_mode = enabled
        self._draw_class_id = class_id
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)
        if not enabled:
            self._cancel_draw()

    def _start_draw(self, view_pos) -> None:
        scene_pos = self.mapToScene(view_pos)
        self._drawing = True
        self._draw_start = scene_pos
        rect = QRectF(scene_pos, scene_pos)
        self._draw_temp_item = QGraphicsRectItem(rect)
        pen = QPen(QColor(self.project_state.class_color(self._draw_class_id)), 2, Qt.PenStyle.DashLine)
        self._draw_temp_item.setPen(pen)
        self._draw_temp_item.setZValue(20)
        self.scene_.addItem(self._draw_temp_item)

    def _update_draw(self, view_pos) -> None:
        if not self._drawing or self._draw_temp_item is None or self._draw_start is None:
            return
        scene_pos = self.mapToScene(view_pos)
        rect = QRectF(self._draw_start, scene_pos).normalized()
        self._draw_temp_item.setRect(rect)

    def _finish_draw(self, view_pos) -> None:
        if not self._drawing:
            return
        self._update_draw(view_pos)
        rect = self._draw_temp_item.rect() if self._draw_temp_item else QRectF()
        self._cancel_draw()
        if self._raster is None or self._raster_path is None:
            return
        if rect.width() < 3 or rect.height() < 3:
            return
        raster_rect = QRectF(0, 0, self._raster.width, self._raster.height)
        rect = rect.intersected(raster_rect)
        det = Detection(
            class_id=self._draw_class_id,
            x_min=rect.left(),
            y_min=rect.top(),
            x_max=rect.right(),
            y_max=rect.bottom(),
            confidence=1.0,
            source="manual",
            edited=True,
        )
        self.project_state.add_detection(self._raster_path, det)

    def _cancel_draw(self) -> None:
        self._drawing = False
        self._draw_start = None
        if self._draw_temp_item is not None:
            self.scene_.removeItem(self._draw_temp_item)
            self._draw_temp_item = None

    # --- fare / klavye --------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if self._raster is None:
            super().mousePressEvent(event)
            return
        if self._draw_mode and event.button() == Qt.MouseButton.LeftButton:
            self._start_draw(event.pos())
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drawing:
            self._update_draw(event.pos())
            event.accept()
            return
        if self._panning and self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drawing and event.button() == Qt.MouseButton.LeftButton:
            self._finish_draw(event.pos())
            event.accept()
            return
        if self._panning and event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.CursorShape.CrossCursor if self._draw_mode else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._schedule_lod_refresh()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            selected = [item for item in self.scene_.selectedItems() if isinstance(item, DetectionItem)]
            for item in selected:
                self._handle_item_delete(item.det_id)
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._raster is None:
            super().wheelEvent(event)
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._schedule_lod_refresh()
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_lod_refresh()

    # --- zoom yardımcıları (toolbar) -------------------------------------
    def zoom_in(self) -> None:
        self.scale(1.25, 1.25)
        self._schedule_lod_refresh()

    def zoom_out(self) -> None:
        self.scale(0.8, 0.8)
        self._schedule_lod_refresh()

    def zoom_fit(self) -> None:
        if self._raster is None:
            return
        self.fitInView(QRectF(0, 0, self._raster.width, self._raster.height), Qt.AspectRatioMode.KeepAspectRatio)
        self._schedule_lod_refresh()

    # --- yüksek çözünürlük görünüm penceresi (LOD) --------------------------
    def _schedule_lod_refresh(self) -> None:
        self._lod_timer.start()

    def _refresh_detail_lod(self) -> None:
        if self._raster is None or self._base_item is None:
            return
        viewport_rect = self.viewport().rect()
        visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()
        raster_rect = QRectF(0, 0, self._raster.width, self._raster.height)
        visible = visible_scene_rect.intersected(raster_rect)
        if visible.isEmpty() or visible.width() < 1 or visible.height() < 1:
            return

        out_w = min(2048, max(64, viewport_rect.width()))
        out_h = min(2048, max(64, viewport_rect.height()))
        window = PixelWindow(visible.x(), visible.y(), visible.width(), visible.height())
        try:
            img = self._raster.read_region_as_qimage(window, out_w, out_h)
        except Exception:
            return
        pix = QPixmap.fromImage(img)
        if self._detail_item is None:
            self._detail_item = QGraphicsPixmapItem()
            self._detail_item.setZValue(1)
            self.scene_.addItem(self._detail_item)
        self._detail_item.setPixmap(pix)
        self._detail_item.setPos(visible.x(), visible.y())
        if pix.width() and pix.height():
            self._detail_item.setTransform(
                QTransform().scale(visible.width() / pix.width(), visible.height() / pix.height())
            )
