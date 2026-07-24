from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CLASS_PRESETS: dict[str, dict[int, str]] = {
    "single": {0: "Manhole"},
    "3class": {0: "Manhole", 1: "Storm Drain", 2: "Rectangular"},
    "6class": {
        0: "Manhole",
        1: "Storm Drain",
        2: "Rectangular",
        3: "Manhole_Damaged",
        4: "Storm Drain_Damaged",
        5: "Rectangular_Damaged",
    },
}


@dataclass
class LoadedModel:
    path: Path
    model: object
    names: dict[int, str]

    def predict_tile(self, image_array, conf: float = 0.25, iou: float = 0.45):
        results = self.model.predict(source=image_array, conf=conf, iou=iou, verbose=False)
        detections = []
        if not results:
            return detections
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return detections
        for box in boxes:
            xyxy = box.xyxy[0].tolist()
            cls_id = int(box.cls[0].item())
            confidence = float(box.conf[0].item())
            detections.append((cls_id, confidence, xyxy[0], xyxy[1], xyxy[2], xyxy[3]))
        return detections


def load_model(path: Path) -> LoadedModel:
    from ultralytics import YOLO

    model = YOLO(str(path))
    raw_names = getattr(model, "names", None) or {}
    names = {int(k): str(v) for k, v in raw_names.items()}
    return LoadedModel(path=path, model=model, names=names)


def parse_data_yaml(path: Path) -> dict[int, str]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    raw_names = data.get("names", {})
    if isinstance(raw_names, list):
        return {i: str(name) for i, name in enumerate(raw_names)}
    return {int(k): str(v) for k, v in raw_names.items()}
