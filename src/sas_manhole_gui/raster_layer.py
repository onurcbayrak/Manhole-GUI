"""rasterio tabanlı .tif/.tiff sarmalayıcısı.

Büyük ortofotoları tam çözünürlükte belleğe yüklemeden, istenen pencere ve
çözünürlükte (decimated read) okuyarak QImage üretir -- QGIS/ArcGIS'teki gibi
akıcı pan/zoom sağlar. Piksel<->dünya koordinat dönüşümleri raster'ın affine
transform'unu kullanır.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from PySide6.QtGui import QImage
from rasterio.windows import Window


@dataclass
class PixelWindow:
    """Tam görüntü piksel koordinatlarında bir pencere (sol-üst dahil, sağ-alt hariç)."""

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

    @classmethod
    def open(cls, path: Path) -> "RasterLayer":
        dataset = rasterio.open(str(path))
        return cls(path=path, dataset=dataset)

    def close(self) -> None:
        try:
            self.dataset.close()
        except Exception:
            pass

    # --- temel özellikler ------------------------------------------------
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

    # --- koordinat dönüşümleri --------------------------------------------
    def pixel_to_world(self, col: float, row: float) -> tuple[float, float]:
        x, y = self.transform * (col, row)
        return x, y

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        col, row = ~self.transform * (x, y)
        return col, row

    # --- görüntüleme ---------------------------------------------------
    def _compute_stretch(self, sample_size: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """8-bit olmayan veriler için hızlı bir 2-98 persentil kontrast germesi hesaplar."""
        if self._stretch_cache is not None:
            return self._stretch_cache
        bands = min(self.count, 3)
        out_shape = (bands, min(sample_size, self.height), min(sample_size, self.width))
        sample = self.dataset.read(indexes=list(range(1, bands + 1)), out_shape=out_shape, resampling=rasterio.enums.Resampling.average)
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
        """Verilen piksel penceresini istenen çıktı boyutuna decimate ederek okur."""
        out_width = max(1, int(out_width))
        out_height = max(1, int(out_height))
        bands = min(self.count, 3)
        rio_window = window.to_rasterio_window()
        try:
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
        return image.copy()  # numpy buffer'dan bağımsızlaştır

    def full_view_qimage(self, max_dim: int = 2048) -> QImage:
        scale = min(1.0, max_dim / max(self.width, self.height))
        out_w = max(1, int(self.width * scale))
        out_h = max(1, int(self.height * scale))
        window = PixelWindow(0, 0, self.width, self.height)
        return self.read_region_as_qimage(window, out_w, out_h)

    def thumbnail(self, max_size: int = 160) -> QImage:
        return self.full_view_qimage(max_dim=max_size)

    # --- inference için ham veri okuma --------------------------------------
    def read_tile_array(self, window: PixelWindow, target_size: int) -> np.ndarray:
        """YOLO'ya verilecek RGB uint8 kare kesit (target_size x target_size)."""
        bands = min(self.count, 3)
        rio_window = window.to_rasterio_window()
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
