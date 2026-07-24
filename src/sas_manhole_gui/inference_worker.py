from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from sas_manhole_gui.model_manager import LoadedModel
from sas_manhole_gui.project_state import Detection, ProjectState, SamRegion
from sas_manhole_gui.tiler import generate_tiles

RawDetection = tuple[int, float, float, float, float, float]

SAM_FILTER_NONE = "none"
SAM_FILTER_INSIDE = "inside"
SAM_FILTER_OUTSIDE = "outside"


def _iou(a: RawDetection, b: RawDetection) -> float:
    ax1, ay1, ax2, ay2 = a[2], a[3], a[4], a[5]
    bx1, by1, bx2, by2 = b[2], b[3], b[4], b[5]
    inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    inter_w, inter_h = max(0.0, inter_x2 - inter_x1), max(0.0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def merge_detections(detections: list[RawDetection], iou_threshold: float = 0.5) -> list[RawDetection]:
    by_class: dict[int, list[RawDetection]] = {}
    for det in detections:
        by_class.setdefault(det[0], []).append(det)
    kept: list[RawDetection] = []
    for items in by_class.values():
        items = sorted(items, key=lambda d: d[1], reverse=True)
        chosen: list[RawDetection] = []
        for cand in items:
            if all(_iou(cand, c) < iou_threshold for c in chosen):
                chosen.append(cand)
        kept.extend(chosen)
    return kept


def _point_in_any_region(x: float, y: float, regions: list[SamRegion]) -> bool:
    for r in regions:
        if r.contains_point(x, y):
            return True
    return False


def apply_sam_filter(
    detections: list[RawDetection], regions: list[SamRegion], mode: str
) -> list[RawDetection]:
    if mode == SAM_FILTER_NONE or not regions:
        return detections
    kept: list[RawDetection] = []
    for d in detections:
        cx = (d[2] + d[4]) / 2.0
        cy = (d[3] + d[5]) / 2.0
        inside = _point_in_any_region(cx, cy, regions)
        if mode == SAM_FILTER_INSIDE and inside:
            kept.append(d)
        elif mode == SAM_FILTER_OUTSIDE and not inside:
            kept.append(d)
    return kept


class InferenceWorker(QThread):
    progress = Signal(int, int, str)
    raster_finished = Signal(str, list)
    raster_error = Signal(str, str)
    state_changed = Signal(str)
    all_finished = Signal()

    def __init__(
        self,
        project_state: ProjectState,
        raster_paths: list[str],
        model: LoadedModel,
        tile_size: int = 640,
        overlap: float = 0.2,
        conf: float = 0.25,
        iou: float = 0.45,
        merge_iou: float = 0.5,
        sam_filter_mode: str = SAM_FILTER_NONE,
        parent=None,
    ):
        super().__init__(parent)
        self.project_state = project_state
        self.raster_paths = raster_paths
        self.model = model
        self.tile_size = tile_size
        self.overlap = overlap
        self.conf = conf
        self.iou = iou
        self.merge_iou = merge_iou
        self.sam_filter_mode = sam_filter_mode
        self._cancelled = False
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._paused = False

    def cancel(self) -> None:
        self._cancelled = True
        self._resume_event.set()

    def pause(self) -> None:
        if self._paused or self._cancelled:
            return
        self._paused = True
        self._resume_event.clear()
        self.state_changed.emit("paused")

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        self._resume_event.set()
        self.state_changed.emit("running")

    def is_paused(self) -> bool:
        return self._paused

    def _wait_if_paused(self) -> None:
        if not self._resume_event.is_set():
            self._resume_event.wait()

    def run(self) -> None:
        self.state_changed.emit("running")
        tiles_per_raster: dict[str, list] = {}
        total = 0
        for path in self.raster_paths:
            pr = self.project_state.rasters.get(path)
            if pr is None:
                continue
            tiles = generate_tiles(pr.layer.width, pr.layer.height, self.tile_size, self.overlap)
            tiles_per_raster[path] = tiles
            total += len(tiles)

        done = 0
        for path in self.raster_paths:
            if self._cancelled:
                break
            pr = self.project_state.rasters.get(path)
            if pr is None:
                continue
            raw: list[RawDetection] = []
            for window in tiles_per_raster.get(path, []):
                self._wait_if_paused()
                if self._cancelled:
                    break
                try:
                    tile_array = pr.layer.read_tile_array(window, self.tile_size)
                    preds = self.model.predict_tile(tile_array, conf=self.conf, iou=self.iou)
                except Exception as exc:
                    self.raster_error.emit(path, str(exc))
                    preds = []

                scale_x = window.width / self.tile_size
                scale_y = window.height / self.tile_size
                for cls_id, confidence, x1, y1, x2, y2 in preds:
                    raw.append(
                        (
                            cls_id,
                            confidence,
                            window.col_off + x1 * scale_x,
                            window.row_off + y1 * scale_y,
                            window.col_off + x2 * scale_x,
                            window.row_off + y2 * scale_y,
                        )
                    )
                done += 1
                self.progress.emit(done, max(total, 1), pr.name)

            if self._cancelled:
                break

            merged = merge_detections(raw, self.merge_iou)
            filtered = apply_sam_filter(merged, pr.sam_regions, self.sam_filter_mode)
            detections = [
                Detection(class_id=c, confidence=conf_, x_min=x1, y_min=y1, x_max=x2, y_max=y2, source="model")
                for c, conf_, x1, y1, x2, y2 in filtered
            ]
            self.raster_finished.emit(path, detections)

        self.state_changed.emit("stopped" if self._cancelled else "finished")
        self.all_finished.emit()
