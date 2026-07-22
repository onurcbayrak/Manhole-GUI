"""Arka planda tiling + YOLO inference + NMS birleştirme çalıştıran QThread worker'ı."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from sas_manhole_gui.model_manager import LoadedModel
from sas_manhole_gui.project_state import Detection, ProjectState
from sas_manhole_gui.tiler import generate_tiles

RawDetection = tuple[int, float, float, float, float, float]  # class_id, conf, x1, y1, x2, y2


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
    """Kesitler arası örtüşmeden kaynaklanan tekrar tespitleri sınıf bazlı NMS ile birleştirir."""
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


class InferenceWorker(QThread):
    progress = Signal(int, int, str)  # tamamlanan, toplam, aktif görüntü adı
    raster_finished = Signal(str, list)  # raster_path, list[Detection]
    raster_error = Signal(str, str)
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
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
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
                if self._cancelled:
                    break
                try:
                    tile_array = pr.layer.read_tile_array(window, self.tile_size)
                    preds = self.model.predict_tile(tile_array, conf=self.conf, iou=self.iou)
                except Exception as exc:  # noqa: BLE001 - worker thread'de tüm hataları raporla
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
            detections = [
                Detection(class_id=c, confidence=conf_, x_min=x1, y_min=y1, x_max=x2, y_max=y2, source="model")
                for c, conf_, x1, y1, x2, y2 in merged
            ]
            self.raster_finished.emit(path, detections)

        self.all_finished.emit()
