from __future__ import annotations

import numpy as np
from PySide6.QtCore import QThread, Signal

from sas_manhole_gui.sam_manager import LoadedSam, SamTextResult


class SamTextWorker(QThread):
    result = Signal(str, str, list)
    error = Signal(str, str)

    def __init__(
        self,
        raster_path: str,
        sam: LoadedSam,
        image_np: np.ndarray,
        text: str,
        confidence: float,
        offset_xy: tuple[float, float],
        native_size: tuple[int, int],
        parent=None,
    ):
        super().__init__(parent)
        self.raster_path = raster_path
        self.sam = sam
        self.image_np = image_np
        self.text = text
        self.confidence = confidence
        self.offset_xy = offset_xy
        self.native_size = native_size

    def run(self) -> None:
        try:
            results: list[SamTextResult] = self.sam.query_text(self.image_np, self.text, self.confidence)
        except Exception as exc:
            self.error.emit(self.raster_path, str(exc))
            return
        img_h, img_w = self.image_np.shape[:2]
        native_w, native_h = self.native_size
        sx = native_w / img_w if img_w else 1.0
        sy = native_h / img_h if img_h else 1.0
        ox, oy = self.offset_xy
        globalized: list[tuple[str, float, tuple[float, float, float, float], list[tuple[float, float]]]] = []
        for r in results:
            gx1 = ox + r.bbox[0] * sx
            gy1 = oy + r.bbox[1] * sy
            gx2 = ox + r.bbox[2] * sx
            gy2 = oy + r.bbox[3] * sy
            gpoly = [(ox + px * sx, oy + py * sy) for px, py in r.polygon]
            globalized.append((r.text, r.confidence, (gx1, gy1, gx2, gy2), gpoly))
        self.result.emit(self.raster_path, self.text, globalized)
