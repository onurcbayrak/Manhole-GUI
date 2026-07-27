from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QPainter, QPen, QPixmap, QPolygonF, QTransform, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QStyleOptionGraphicsItem,
    QWidget,
)

from sas_manhole_gui.detection_item import DetectionItem
from sas_manhole_gui.project_state import Detection, ProjectState, SamRegion
from sas_manhole_gui.raster_layer import PixelWindow
from sas_manhole_gui.style import BG_DARK, SAM_COLOR


class SamRegionItem(QGraphicsPolygonItem):
    def __init__(self, region: SamRegion):
        if region.polygon and len(region.polygon) >= 3:
            polygon = QPolygonF([QPointF(x, y) for x, y in region.polygon])
        else:
            polygon = QPolygonF(
                [
                    QPointF(region.x_min, region.y_min),
                    QPointF(region.x_max, region.y_min),
                    QPointF(region.x_max, region.y_max),
                    QPointF(region.x_min, region.y_max),
                ]
            )
        super().__init__(polygon)
        self.region_id = region.region_id
        self._text = region.text
        self._confidence = region.confidence
        self._top_left = QPointF(region.x_min, region.y_min)
        self.setZValue(5)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        color = QColor(SAM_COLOR)
        self.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
        fill = QColor(color)
        fill.setAlpha(45)
        self.setBrush(QBrush(fill))

    def _view_scale(self) -> float:
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views:
                return max(views[0].transform().m11(), 0.0001)
        return 1.0

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None) -> None:
        super().paint(painter, option, widget)
        if not self._text:
            return
        scale = self._view_scale()
        font = painter.font()
        font_size = max(6.0, 10.0 / scale)
        font.setPointSizeF(font_size)
        painter.setFont(font)
        label = f"{self._text}  {self._confidence:.2f}"
        label_h = font_size * 1.7
        label_w = max(font_size * len(label) * 0.55, 40 / scale)
        text_rect = QRectF(self._top_left.x(), self._top_left.y() - label_h, label_w, label_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(SAM_COLOR)))
        painter.drawRect(text_rect)
        painter.setPen(QPen(QColor("#101010")))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)


class RasterCanvas(QGraphicsView):
    detection_selected = Signal(object)

    MIN_SCALE = 0.02
    MAX_SCALE = 40.0

    def __init__(self, project_state: ProjectState, parent=None):
        super().__init__(parent)
        self.project_state = project_state

        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor(BG_DARK))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self._raster = None
        self._raster_path: Optional[str] = None
        self._base_item: Optional[QGraphicsPixmapItem] = None
        self._detail_item: Optional[QGraphicsPixmapItem] = None
        self._detection_items: dict[int, DetectionItem] = {}
        self._sam_items: dict[int, SamRegionItem] = {}
        self._h_crosshair: Optional[QGraphicsLineItem] = None
        self._v_crosshair: Optional[QGraphicsLineItem] = None
        self._syncing = False
        self._detection_sync_pending = False
        self._sam_sync_pending = False

        self._lod_timer = QTimer(self)
        self._lod_timer.setSingleShot(True)
        self._lod_timer.setInterval(150)
        self._lod_timer.timeout.connect(self._refresh_detail_lod)

        self._draw_mode = False
        self._draw_class_id = 0
        self._drawing = False
        self._draw_start: Optional[QPointF] = None
        self._draw_temp_item: Optional[QGraphicsRectItem] = None

        self._pan_mode = False
        self._panning = False
        self._pan_start = None

        self.horizontalScrollBar().valueChanged.connect(self._schedule_lod_refresh)
        self.verticalScrollBar().valueChanged.connect(self._schedule_lod_refresh)
        self.scene_.selectionChanged.connect(self._emit_selection)

        project_state.active_raster_changed.connect(self.set_active_raster)
        project_state.detections_changed.connect(self._on_detections_changed)
        project_state.sam_regions_changed.connect(self._on_sam_regions_changed)
        project_state.classes_changed.connect(self._on_classes_changed)

    def set_active_raster(self, path: str) -> None:
        self._raster_path = path or None
        self._cancel_draw()
        self._panning = False
        self._pan_start = None
        self._syncing = True
        try:
            self.scene_.clear()
        finally:
            self._syncing = False
        self._detection_items.clear()
        self._sam_items.clear()
        self._detection_sync_pending = False
        self._sam_sync_pending = False
        self._h_crosshair = None
        self._v_crosshair = None
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
        self._rebuild_sam_items(pr.sam_regions)
        if self._draw_mode:
            self._ensure_crosshair()
        self.fitInView(self.scene_.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._schedule_lod_refresh()

    def _current_detections(self) -> list[Detection]:
        pr = self.project_state.rasters.get(self._raster_path) if self._raster_path else None
        return pr.detections if pr else []

    def _current_sam_regions(self) -> list[SamRegion]:
        pr = self.project_state.rasters.get(self._raster_path) if self._raster_path else None
        return pr.sam_regions if pr else []

    def _find_detection(self, det_id: int) -> Optional[Detection]:
        for d in self._current_detections():
            if d.det_id == det_id:
                return d
        return None

    def _rebuild_detection_items(self, detections: list[Detection]) -> None:
        for det in detections:
            self._add_detection_item(det)

    def _rebuild_sam_items(self, regions: list[SamRegion]) -> None:
        for region in regions:
            self._add_sam_item(region)

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
        item.set_hover_enabled(not self._draw_mode)
        self.scene_.addItem(item)
        self._detection_items[det.det_id] = item

    def _add_sam_item(self, region: SamRegion) -> None:
        item = SamRegionItem(region)
        self.scene_.addItem(item)
        self._sam_items[region.region_id] = item

    def _classes_for_menu(self) -> list[tuple[int, str, str]]:
        return [(c.class_id, c.name, c.color) for c in self.project_state.classes]

    def _handle_item_changed(self, det_id: int, rect: QRectF) -> None:
        if self._raster is None or self._raster_path is None:
            return
        raster_rect = QRectF(0, 0, self._raster.width, self._raster.height)
        clamped = rect.intersected(raster_rect)
        self.project_state.update_detection_rect(
            self._raster_path, det_id, clamped.left(), clamped.top(), clamped.right(), clamped.bottom()
        )

    def _handle_item_delete(self, det_id: int) -> None:
        if self._raster_path is None:
            return
        self.project_state.remove_detection(self._raster_path, det_id)

    def _handle_item_class_change(self, det_id: int, class_id: int) -> None:
        if self._raster_path is None:
            return
        self.project_state.update_detection_class(self._raster_path, det_id, class_id)

    def _on_detections_changed(self, raster_path: str) -> None:
        if raster_path != self._raster_path:
            return
        if self._detection_sync_pending:
            return
        self._detection_sync_pending = True
        QTimer.singleShot(0, self._sync_detection_items)

    def _on_sam_regions_changed(self, raster_path: str) -> None:
        if raster_path != self._raster_path:
            return
        if self._sam_sync_pending:
            return
        self._sam_sync_pending = True
        QTimer.singleShot(0, self._sync_sam_items)

    def _detection_label(self, det: Detection) -> str:
        name = self.project_state.class_name(det.class_id)
        return f"{name} {det.confidence:.2f}" if det.source == "model" else name

    def _sync_detection_items(self) -> None:
        self._detection_sync_pending = False
        if self._raster_path is None or self._syncing:
            return
        self._syncing = True
        try:
            detections = self._current_detections()
            wanted = {d.det_id: d for d in detections}

            for det_id in [i for i in self._detection_items if i not in wanted]:
                item = self._detection_items.pop(det_id, None)
                if item is None:
                    continue
                try:
                    item.setSelected(False)
                    if item.scene() is self.scene_:
                        self.scene_.removeItem(item)
                except RuntimeError:
                    pass

            for det_id, det in wanted.items():
                item = self._detection_items.get(det_id)
                if item is None:
                    self._add_detection_item(det)
                    continue
                try:
                    item.apply_geometry(QRectF(det.x_min, det.y_min, det.width(), det.height()))
                    item.set_style(self.project_state.class_color(det.class_id), self._detection_label(det))
                    item.set_hover_enabled(not self._draw_mode)
                except RuntimeError:
                    self._detection_items.pop(det_id, None)
        finally:
            self._syncing = False

    def _sync_sam_items(self) -> None:
        self._sam_sync_pending = False
        if self._raster_path is None or self._syncing:
            return
        self._syncing = True
        try:
            regions = self._current_sam_regions()
            wanted = {r.region_id: r for r in regions}

            for region_id in [i for i in self._sam_items if i not in wanted]:
                item = self._sam_items.pop(region_id, None)
                if item is None:
                    continue
                try:
                    item.setSelected(False)
                    if item.scene() is self.scene_:
                        self.scene_.removeItem(item)
                except RuntimeError:
                    pass

            for region_id, region in wanted.items():
                if region_id not in self._sam_items:
                    self._add_sam_item(region)
        finally:
            self._syncing = False

    def _on_classes_changed(self) -> None:
        for det_id, item in list(self._detection_items.items()):
            det = self._find_detection(det_id)
            if det is None:
                continue
            try:
                item.set_style(self.project_state.class_color(det.class_id), self._detection_label(det))
            except RuntimeError:
                self._detection_items.pop(det_id, None)

    def _emit_selection(self) -> None:
        if self._syncing:
            return
        selected = []
        for item in self.scene_.selectedItems():
            if isinstance(item, DetectionItem):
                try:
                    selected.append(item.det_id)
                except RuntimeError:
                    continue
        self.detection_selected.emit(selected[0] if selected else None)

    def select_detection(self, det_id: Optional[int]) -> None:
        for did, item in self._detection_items.items():
            item.setSelected(did == det_id)
        if det_id is not None and det_id in self._detection_items:
            self.centerOn(self._detection_items[det_id])

    def set_draw_mode(self, enabled: bool, class_id: int = 0) -> None:
        if enabled and self._pan_mode:
            self.set_pan_mode(False)
        self._draw_mode = enabled
        self._draw_class_id = class_id
        self._update_cursor()
        for item in self._detection_items.values():
            item.set_hover_enabled(not enabled)
        if enabled:
            self._ensure_crosshair()
        else:
            self._remove_crosshair()
            self._cancel_draw()

    def set_pan_mode(self, enabled: bool) -> None:
        if enabled and self._draw_mode:
            self.set_draw_mode(False)
        self._pan_mode = enabled
        self._update_cursor()

    def _update_cursor(self) -> None:
        if self._panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._draw_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._pan_mode:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _ensure_crosshair(self) -> None:
        if self._raster is None:
            return
        if self._h_crosshair is not None and self._v_crosshair is not None:
            return
        pen = QPen(QColor(230, 230, 230, 180), 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self._h_crosshair = QGraphicsLineItem()
        self._h_crosshair.setPen(pen)
        self._h_crosshair.setZValue(50)
        self._h_crosshair.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, False)
        self.scene_.addItem(self._h_crosshair)
        self._v_crosshair = QGraphicsLineItem()
        self._v_crosshair.setPen(pen)
        self._v_crosshair.setZValue(50)
        self.scene_.addItem(self._v_crosshair)
        center = self.viewport().rect().center()
        self._update_crosshair(center)

    def _remove_crosshair(self) -> None:
        if self._h_crosshair is not None:
            self.scene_.removeItem(self._h_crosshair)
            self._h_crosshair = None
        if self._v_crosshair is not None:
            self.scene_.removeItem(self._v_crosshair)
            self._v_crosshair = None

    def _update_crosshair(self, view_pos) -> None:
        if self._h_crosshair is None or self._v_crosshair is None:
            return
        scene_pos = self.mapToScene(view_pos)
        r = self.scene_.sceneRect()
        self._h_crosshair.setLine(r.left(), scene_pos.y(), r.right(), scene_pos.y())
        self._v_crosshair.setLine(scene_pos.x(), r.top(), scene_pos.x(), r.bottom())

    def visible_pixel_window(self) -> Optional[PixelWindow]:
        if self._raster is None:
            return None
        viewport_rect = self.viewport().rect()
        visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()
        raster_rect = QRectF(0, 0, self._raster.width, self._raster.height)
        visible = visible_scene_rect.intersected(raster_rect)
        if visible.isEmpty() or visible.width() < 1 or visible.height() < 1:
            return None
        return PixelWindow(visible.x(), visible.y(), visible.width(), visible.height())

    def full_pixel_window(self) -> Optional[PixelWindow]:
        if self._raster is None:
            return None
        return PixelWindow(0, 0, self._raster.width, self._raster.height)

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

    def mousePressEvent(self, event) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self._raster is None:
            super().mousePressEvent(event)
            return
        if self._draw_mode and event.button() == Qt.MouseButton.LeftButton:
            self._start_draw(event.pos())
            event.accept()
            return
        if self._pan_mode and event.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_start = event.pos()
            self._update_cursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self._update_cursor()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._draw_mode:
            self._update_crosshair(event.pos())
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
        if self._panning and event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = False
            self._pan_start = None
            self._update_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._schedule_lod_refresh()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            det_ids = []
            region_ids = []
            for item in list(self.scene_.selectedItems()):
                try:
                    if isinstance(item, DetectionItem):
                        det_ids.append(item.det_id)
                    elif isinstance(item, SamRegionItem):
                        region_ids.append(item.region_id)
                except RuntimeError:
                    continue
            if det_ids or region_ids:
                for det_id in det_ids:
                    self._handle_item_delete(det_id)
                if self._raster_path is not None:
                    for region_id in region_ids:
                        self.project_state.remove_sam_region(self._raster_path, region_id)
                event.accept()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._raster is None:
            super().wheelEvent(event)
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._apply_zoom(factor)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_lod_refresh()

    def zoom_in(self) -> None:
        self._toolbar_zoom(1.25)

    def zoom_out(self) -> None:
        self._toolbar_zoom(0.8)

    def zoom_fit(self) -> None:
        if self._raster is None:
            return
        self.fitInView(QRectF(0, 0, self._raster.width, self._raster.height), Qt.AspectRatioMode.KeepAspectRatio)
        self._schedule_lod_refresh()

    def _apply_zoom(self, factor: float) -> None:
        current = self.transform().m11()
        target = current * factor
        if target < self.MIN_SCALE:
            factor = self.MIN_SCALE / current if current > 0 else 1.0
        elif target > self.MAX_SCALE:
            factor = self.MAX_SCALE / current if current > 0 else 1.0
        if abs(factor - 1.0) < 1e-6:
            return
        try:
            self.scale(factor, factor)
        except Exception:
            return
        self._schedule_lod_refresh()

    def _toolbar_zoom(self, factor: float) -> None:
        cursor_view = self.mapFromGlobal(QCursor.pos())
        if self.viewport().rect().contains(cursor_view):
            self._apply_zoom(factor)
            return
        previous_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        try:
            self._apply_zoom(factor)
        finally:
            self.setTransformationAnchor(previous_anchor)

    def _schedule_lod_refresh(self) -> None:
        self._lod_timer.start()

    def _refresh_detail_lod(self) -> None:
        try:
            self._do_refresh_detail_lod()
        except Exception:
            return

    def _do_refresh_detail_lod(self) -> None:
        if self._raster is None or self._base_item is None:
            return
        viewport_rect = self.viewport().rect()
        visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()
        raster_rect = QRectF(0, 0, self._raster.width, self._raster.height)
        visible = visible_scene_rect.intersected(raster_rect)
        if visible.isEmpty() or visible.width() < 1 or visible.height() < 1:
            return

        vp_w = max(64, viewport_rect.width())
        vp_h = max(64, viewport_rect.height())
        src_w = max(1.0, visible.width())
        src_h = max(1.0, visible.height())
        out_w = int(min(2048, vp_w, max(64.0, src_w * 2.0)))
        out_h = int(min(2048, vp_h, max(64.0, src_h * 2.0)))
        if out_w <= 0 or out_h <= 0:
            return
        window = PixelWindow(visible.x(), visible.y(), visible.width(), visible.height())
        img = self._raster.read_region_as_qimage(window, out_w, out_h)
        pix = QPixmap.fromImage(img)
        if pix.isNull() or pix.width() == 0 or pix.height() == 0:
            return
        if self._detail_item is None:
            self._detail_item = QGraphicsPixmapItem()
            self._detail_item.setZValue(1)
            self.scene_.addItem(self._detail_item)
        self._detail_item.setPixmap(pix)
        self._detail_item.setPos(visible.x(), visible.y())
        self._detail_item.setTransform(
            QTransform().scale(visible.width() / pix.width(), visible.height() / pix.height())
        )
