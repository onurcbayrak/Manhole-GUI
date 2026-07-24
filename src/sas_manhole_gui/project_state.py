from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from sas_manhole_gui.raster_layer import RasterLayer
from sas_manhole_gui.style import class_color
from sas_manhole_gui.undo_manager import UndoManager

_detection_id_counter = itertools.count(1)
_sam_region_id_counter = itertools.count(1)


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
    class_id: int
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    confidence: float = 1.0
    source: str = "model"
    edited: bool = False
    det_id: int = field(default_factory=lambda: next(_detection_id_counter))

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x_min, self.y_min, self.x_max, self.y_max)

    def width(self) -> float:
        return self.x_max - self.x_min

    def height(self) -> float:
        return self.y_max - self.y_min

    def center(self) -> tuple[float, float]:
        return ((self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0)


@dataclass
class SamRegion:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    text: str = ""
    confidence: float = 1.0
    polygon: list[tuple[float, float]] = field(default_factory=list)
    region_id: int = field(default_factory=lambda: next(_sam_region_id_counter))

    def contains_point(self, x: float, y: float) -> bool:
        if not (self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max):
            return False
        if not self.polygon or len(self.polygon) < 3:
            return True
        inside = False
        n = len(self.polygon)
        j = n - 1
        for i in range(n):
            xi, yi = self.polygon[i]
            xj, yj = self.polygon[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside


@dataclass
class ProjectRaster:
    path: Path
    layer: RasterLayer
    thumbnail: Optional[QImage] = None
    detections: list[Detection] = field(default_factory=list)
    sam_regions: list[SamRegion] = field(default_factory=list)
    inference_done: bool = False

    @property
    def name(self) -> str:
        return self.path.name


class ProjectState(QObject):
    rasters_changed = Signal()
    raster_status_changed = Signal(str)
    active_raster_changed = Signal(str)
    classes_changed = Signal()
    detections_changed = Signal(str)
    sam_regions_changed = Signal(str)
    model_changed = Signal()
    sam_model_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.rasters: dict[str, ProjectRaster] = {}
        self.active_raster_path: Optional[str] = None
        self.classes: list[ClassDef] = []
        self.model_path: Optional[Path] = None
        self.model = None
        self.sam_path: Optional[Path] = None
        self.sam = None
        self.undo_manager = UndoManager(self)

    def add_raster(self, path: Path) -> Optional[ProjectRaster]:
        key = str(path)
        if key in self.rasters:
            return self.rasters[key]
        try:
            layer = RasterLayer.open(path)
            thumbnail = layer.thumbnail(120)
        except Exception:
            return None
        return self.add_raster_prebuilt(path, layer, thumbnail)

    def add_raster_prebuilt(
        self, path: Path, layer: RasterLayer, thumbnail: Optional[QImage], notify: bool = True
    ) -> ProjectRaster:
        key = str(path)
        pr = ProjectRaster(path=path, layer=layer, thumbnail=thumbnail)
        self.rasters[key] = pr
        if notify:
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

    def clear_rasters(self) -> None:
        if not self.rasters:
            return
        for pr in list(self.rasters.values()):
            try:
                pr.layer.close()
            except Exception:
                pass
        self.rasters.clear()
        self.active_raster_path = None
        self.undo_manager.clear()
        self.active_raster_changed.emit("")
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

    def mark_inference_done(self, raster_path: str, done: bool = True) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.inference_done = done
        self.raster_status_changed.emit(raster_path)

    def set_detections(self, raster_path: str, detections: list[Detection], record_undo: bool = False) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        if record_undo:
            previous = list(pr.detections)
            self.undo_manager.push(
                "Bulk replace detections",
                lambda: self._restore_detections(raster_path, previous),
            )
        pr.detections = detections
        self.detections_changed.emit(raster_path)

    def _restore_detections(self, raster_path: str, detections: list[Detection]) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.detections = list(detections)
        self.detections_changed.emit(raster_path)

    def add_detection(self, raster_path: str, detection: Detection, record_undo: bool = True) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.detections.append(detection)
        if record_undo:
            det_id = detection.det_id
            self.undo_manager.push(
                f"Add {self.class_name(detection.class_id)}",
                lambda: self._raw_remove_detection(raster_path, det_id),
            )
        self.detections_changed.emit(raster_path)

    def _raw_remove_detection(self, raster_path: str, det_id: int) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.detections = [d for d in pr.detections if d.det_id != det_id]
        self.detections_changed.emit(raster_path)

    def remove_detection(self, raster_path: str, det_id: int, record_undo: bool = True) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        removed = next((d for d in pr.detections if d.det_id == det_id), None)
        if removed is None:
            return
        pr.detections = [d for d in pr.detections if d.det_id != det_id]
        if record_undo:
            snapshot = copy.copy(removed)
            self.undo_manager.push(
                f"Delete {self.class_name(removed.class_id)}",
                lambda: self._raw_add_detection(raster_path, snapshot),
            )
        self.detections_changed.emit(raster_path)

    def _raw_add_detection(self, raster_path: str, detection: Detection) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.detections.append(detection)
        self.detections_changed.emit(raster_path)

    def update_detection_class(
        self, raster_path: str, det_id: int, class_id: int, record_undo: bool = True
    ) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        for det in pr.detections:
            if det.det_id == det_id:
                if det.class_id == class_id:
                    return
                previous_class = det.class_id
                previous_edited = det.edited
                det.class_id = class_id
                det.edited = True
                if record_undo:
                    self.undo_manager.push(
                        f"Change class to {self.class_name(class_id)}",
                        lambda: self._raw_update_class(raster_path, det_id, previous_class, previous_edited),
                    )
                break
        self.detections_changed.emit(raster_path)

    def _raw_update_class(self, raster_path: str, det_id: int, class_id: int, edited: bool) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        for det in pr.detections:
            if det.det_id == det_id:
                det.class_id = class_id
                det.edited = edited
                break
        self.detections_changed.emit(raster_path)

    def update_detection_rect(
        self,
        raster_path: str,
        det_id: int,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
        record_undo: bool = True,
    ) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        for det in pr.detections:
            if det.det_id == det_id:
                prev = (det.x_min, det.y_min, det.x_max, det.y_max, det.edited)
                det.x_min, det.y_min, det.x_max, det.y_max = x_min, y_min, x_max, y_max
                det.edited = True
                if record_undo:
                    self.undo_manager.push(
                        "Move / resize box",
                        lambda: self._raw_update_rect(raster_path, det_id, prev),
                    )
                break
        self.detections_changed.emit(raster_path)

    def _raw_update_rect(self, raster_path: str, det_id: int, prev: tuple) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        for det in pr.detections:
            if det.det_id == det_id:
                det.x_min, det.y_min, det.x_max, det.y_max, det.edited = prev
                break
        self.detections_changed.emit(raster_path)

    def notify_detections_edited(self, raster_path: str) -> None:
        self.detections_changed.emit(raster_path)

    def add_sam_region(self, raster_path: str, region: SamRegion, record_undo: bool = True) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.sam_regions.append(region)
        if record_undo:
            region_id = region.region_id
            self.undo_manager.push(
                "Add SAM region",
                lambda: self._raw_remove_sam(raster_path, region_id),
            )
        self.sam_regions_changed.emit(raster_path)

    def _raw_remove_sam(self, raster_path: str, region_id: int) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.sam_regions = [r for r in pr.sam_regions if r.region_id != region_id]
        self.sam_regions_changed.emit(raster_path)

    def remove_sam_region(self, raster_path: str, region_id: int, record_undo: bool = True) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        removed = next((r for r in pr.sam_regions if r.region_id == region_id), None)
        if removed is None:
            return
        pr.sam_regions = [r for r in pr.sam_regions if r.region_id != region_id]
        if record_undo:
            snapshot = copy.copy(removed)
            self.undo_manager.push(
                "Delete SAM region",
                lambda: self._raw_add_sam(raster_path, snapshot),
            )
        self.sam_regions_changed.emit(raster_path)

    def _raw_add_sam(self, raster_path: str, region: SamRegion) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.sam_regions.append(region)
        self.sam_regions_changed.emit(raster_path)

    def clear_sam_regions(self, raster_path: str, record_undo: bool = True) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None or not pr.sam_regions:
            return
        previous = list(pr.sam_regions)
        pr.sam_regions = []
        if record_undo:
            self.undo_manager.push(
                "Clear all SAM regions",
                lambda: self._restore_sam(raster_path, previous),
            )
        self.sam_regions_changed.emit(raster_path)

    def _restore_sam(self, raster_path: str, regions: list[SamRegion]) -> None:
        pr = self.rasters.get(raster_path)
        if pr is None:
            return
        pr.sam_regions = list(regions)
        self.sam_regions_changed.emit(raster_path)
