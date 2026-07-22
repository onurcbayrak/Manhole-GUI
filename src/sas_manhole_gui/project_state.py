"""Oturum boyunca bellekte tutulan proje durumu: açık rasterlar, aktif model, tespitler."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from sas_manhole_gui.raster_layer import RasterLayer
from sas_manhole_gui.style import class_color

_detection_id_counter = itertools.count(1)


@dataclass
class ClassDef:
    class_id: int
    name: str
    color: str = ""

    def __post_init__(self) -> None:
        if not self.color:
            self.color = class_color(self.class_id)


@dataclass
class Detection:
    """Tam görüntü piksel koordinatlarında (x_min, y_min, x_max, y_max) bir tespit kutusu."""

    class_id: int
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    confidence: float = 1.0
    source: str = "model"  # "model" | "manual"
    edited: bool = False
    det_id: int = field(default_factory=lambda: next(_detection_id_counter))

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x_min, self.y_min, self.x_max, self.y_max)

    def width(self) -> float:
        return self.x_max - self.x_min

    def height(self) -> float:
        return self.y_max - self.y_min


@dataclass
class ProjectRaster:
    path: Path
    layer: RasterLayer
    detections: list[Detection] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name


class ProjectState(QObject):
    """Uygulamanın tek gerçek durum kaynağı. Sinyaller, arayüz panellerini senkron tutar."""

    rasters_changed = Signal()
    active_raster_changed = Signal(str)  # path as str, "" ise seçim yok
    classes_changed = Signal()
    detections_changed = Signal(str)  # etkilenen raster path'i
    model_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.rasters: dict[str, ProjectRaster] = {}
        self.active_raster_path: Optional[str] = None
        self.classes: list[ClassDef] = []
        self.model_path: Optional[Path] = None
        self.model = None  # ModelManager.LoadedModel

    # --- rasterlar -----------------------------------------------------
    def add_raster(self, path: Path) -> Optional[ProjectRaster]:
        key = str(path)
        if key in self.rasters:
            return self.rasters[key]
        try:
            layer = RasterLayer.open(path)
        except Exception:
            return None
        pr = ProjectRaster(path=path, layer=layer)
        self.rasters[key] = pr
        self.rasters_changed.emit()
        if self.active_raster_path is None:
            self.set_active_raster(key)
        return pr

    def remove_raster(self, path: str) -> None:
        pr = self.rasters.pop(path, None)
        if pr:
            pr.layer.close()
        if self.active_raster_path == path:
            self.active_raster_path = next(iter(self.rasters), None)
            self.active_raster_changed.emit(self.active_raster_path or "")
        self.rasters_changed.emit()

    def set_active_raster(self, path: str) -> None:
        if path not in self.rasters:
            return
        self.active_raster_path = path
        self.active_raster_changed.emit(path)

    @property
    def active_raster(self) -> Optional[ProjectRaster]:
        if self.active_raster_path is None:
            return None
        return self.rasters.get(self.active_raster_path)

    # --- sınıflar --------------------------------------------------------
    def set_classes(self, names: dict[int, str]) -> None:
        self.classes = [ClassDef(class_id=cid, name=name) for cid, name in sorted(names.items())]
        self.classes_changed.emit()

    def class_name(self, class_id: int) -> str:
        for c in self.classes:
            if c.class_id == class_id:
                return c.name
        return f"class_{class_id}"

    def class_color(self, class_id: int) -> str:
        for c in self.classes:
            if c.class_id == class_id:
                return c.color
        return class_color(class_id)

    # --- tespitler ---------------------------------------------------------
    def set_detections(self, raster_path: str, detections: list[Detection]) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.detections = detections
        self.detections_changed.emit(raster_path)

    def add_detection(self, raster_path: str, detection: Detection) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.detections.append(detection)
        self.detections_changed.emit(raster_path)

    def remove_detection(self, raster_path: str, det_id: int) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.detections = [d for d in pr.detections if d.det_id != det_id]
        self.detections_changed.emit(raster_path)

    def notify_detections_edited(self, raster_path: str) -> None:
        self.detections_changed.emit(raster_path)
