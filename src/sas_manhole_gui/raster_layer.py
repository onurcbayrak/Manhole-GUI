from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from PySide6.QtGui import QImage
from rasterio.windows import Window


@dataclass
class PixelWindow:
    col_off: float
    row_off: float
    width: float
    height: float

    def to_rasterio_window(self) -> Window:
        return Window(self.col_off, self.row_off, self.width, self.height)


class RasterLayer:
    def __init__(self, path: Path, dataset: rasterio.DatasetReader):
        self.path = path
        self.dataset = dataset
        self._stretch_cache: Optional[tuple[np.ndarray, np.ndarray]] = None
        self._lock = threading.Lock()

    @classmethod
    def open(cls, path: Path) -> "RasterLayer":
        dataset = rasterio.open(str(path))
        return cls(path=path, dataset=dataset)

    def close(self) -> None:
        try:
            self.dataset.close()
        except Exception:
            pass

    @property
    def width(self) -> int:
        return self.dataset.width

    @property
    def height(self) -> int:
        return self.dataset.height

    @property
    def crs(self):
        return self.dataset.crs

    @property
    def transform(self):
        return self.dataset.transform

    @property
    def count(self) -> int:
        return self.dataset.count

    def pixel_to_world(self, col: float, row: float) -> tuple[float, float]:
        x, y = self.transform * (col, row)
        return x, y

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        col, row = ~self.transform * (x, y)
        return col, row

    def gsd_meters(self) -> Optional[float]:
        if self.crs is None:
            return None
        try:
            px_x = abs(self.transform.a)
            px_y = abs(self.transform.e)
        except Exception:
            return None
        try:
            is_projected = bool(getattr(self.crs, "is_projected", False))
        except Exception:
            is_projected = False
        if is_projected:
            if px_x <= 0 or px_y <= 0:
                return None
            return (px_x + px_y) / 2.0
        try:
            from pyproj import Transformer

            cx = self.width / 2.0
            cy = self.height / 2.0
            x0, y0 = self.pixel_to_world(cx, cy)
            xh, yh = self.pixel_to_world(cx + 1.0, cy)
            xv, yv = self.pixel_to_world(cx, cy + 1.0)
            zone = int((x0 + 180.0) / 6.0) + 1
            utm = f"EPSG:{32600 + zone}" if y0 >= 0 else f"EPSG:{32700 + zone}"
            transformer = Transformer.from_crs(self.crs, utm, always_xy=True)
            p0 = transformer.transform(x0, y0)
            ph = transformer.transform(xh, yh)
            pv = transformer.transform(xv, yv)
            dx = ((ph[0] - p0[0]) ** 2 + (ph[1] - p0[1]) ** 2) ** 0.5
            dy = ((pv[0] - p0[0]) ** 2 + (pv[1] - p0[1]) ** 2) ** 0.5
            if dx <= 0 or dy <= 0:
                return None
            return (dx + dy) / 2.0
        except Exception:
            return None

    def _compute_stretch(self, sample_size: int = 512) -> tuple[np.ndarray, np.ndarray]:
        if self._stretch_cache is not None:
            return self._stretch_cache
        bands = min(self.count, 3)
        out_shape = (bands, min(sample_size, self.height), min(sample_size, self.width))
        with self._lock:
            sample = self.dataset.read(
                indexes=list(range(1, bands + 1)), out_shape=out_shape, resampling=rasterio.enums.Resampling.average
            )
        lo = np.percentile(sample.reshape(bands, -1), 2, axis=1)
        hi = np.percentile(sample.reshape(bands, -1), 98, axis=1)
        hi = np.where(hi <= lo, lo + 1, hi)
        self._stretch_cache = (lo, hi)
        return self._stretch_cache

    def _to_uint8(self, arr: np.ndarray) -> np.ndarray:
        if arr.dtype == np.uint8:
            return arr
        lo, hi = self._compute_stretch()
        out = np.empty(arr.shape, dtype=np.uint8)
        for b in range(arr.shape[0]):
            band = arr[b].astype(np.float32)
            scaled = (band - lo[b]) / (hi[b] - lo[b]) * 255.0
            out[b] = np.clip(scaled, 0, 255).astype(np.uint8)
        return out

    def read_region_as_qimage(self, window: PixelWindow, out_width: int, out_height: int) -> QImage:
        out_width = max(1, int(out_width))
        out_height = max(1, int(out_height))
        bands = min(self.count, 3)
        rio_window = window.to_rasterio_window()
        try:
            with self._lock:
                arr = self.dataset.read(
                    indexes=list(range(1, bands + 1)),
                    window=rio_window,
                    out_shape=(bands, out_height, out_width),
                    resampling=rasterio.enums.Resampling.bilinear,
                    boundless=True,
                    fill_value=0,
                )
        except Exception:
            arr = np.zeros((bands, out_height, out_width), dtype=np.uint8)

        arr = self._to_uint8(arr)

        if bands == 1:
            gray = arr[0]
            rgb = np.stack([gray, gray, gray], axis=-1)
        elif bands == 2:
            rgb = np.stack([arr[0], arr[1], np.zeros_like(arr[0])], axis=-1)
        else:
            rgb = np.moveaxis(arr[:3], 0, -1)

        rgb = np.ascontiguousarray(rgb)
        h, w, _ = rgb.shape
        image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        return image.copy()

    def full_view_qimage(self, max_dim: int = 2048) -> QImage:
        scale = min(1.0, max_dim / max(self.width, self.height))
        out_w = max(1, int(self.width * scale))
        out_h = max(1, int(self.height * scale))
        window = PixelWindow(0, 0, self.width, self.height)
        return self.read_region_as_qimage(window, out_w, out_h)

    def thumbnail(self, max_size: int = 160) -> QImage:
        return self.full_view_qimage(max_dim=max_size)

    def read_centered_sam_tile(
        self, cx: float, cy: float, tile_size: int = 1024
    ) -> tuple[np.ndarray, tuple[float, float], tuple[int, int]]:
        x0 = max(0, int(cx - tile_size / 2))
        y0 = max(0, int(cy - tile_size / 2))
        if x0 + tile_size > self.width:
            x0 = max(0, self.width - tile_size)
        if y0 + tile_size > self.height:
            y0 = max(0, self.height - tile_size)
        w = min(tile_size, self.width - x0)
        h = min(tile_size, self.height - y0)
        window = PixelWindow(x0, y0, w, h)
        out_side = tile_size
        arr = self.read_tile_array(window, out_side)
        return arr, (float(x0), float(y0)), (w, h)

    def read_tile_array(self, window: PixelWindow, target_size: int) -> np.ndarray:
        bands = min(self.count, 3)
        rio_window = window.to_rasterio_window()
        with self._lock:
            arr = self.dataset.read(
                indexes=list(range(1, bands + 1)),
                window=rio_window,
                out_shape=(bands, target_size, target_size),
                resampling=rasterio.enums.Resampling.bilinear,
                boundless=True,
                fill_value=0,
            )
        arr = self._to_uint8(arr)
        if bands == 1:
            rgb = np.stack([arr[0]] * 3, axis=-1)
        elif bands == 2:
            rgb = np.stack([arr[0], arr[1], np.zeros_like(arr[0])], axis=-1)
        else:
            rgb = np.moveaxis(arr[:3], 0, -1)
        return np.ascontiguousarray(rgb)
