from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass
class SamTextResult:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]
    polygon: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class LoadedSam:
    path: Path
    model: object
    kind: str

    def query_text(
        self, image_np: np.ndarray, text: str, conf_threshold: float = 0.25
    ) -> list[SamTextResult]:
        results = self._call_with_text(image_np, text)
        return self._extract_results(results, text, image_np.shape[:2], conf_threshold)

    def _call_with_text(self, image_np: np.ndarray, text: str):
        errors = []
        for kwargs in (
            {"texts": [text]},
            {"text": text},
            {"prompt": text},
            {"prompts": [text]},
        ):
            try:
                return self.model(image_np, verbose=False, **kwargs)
            except TypeError as exc:
                errors.append(str(exc))
                continue
            except Exception as exc:
                errors.append(str(exc))
                continue
        raise RuntimeError(
            "This model did not accept a text prompt. "
            "SAM3 text queries require a text-capable checkpoint.\n"
            "Last error: " + (errors[-1] if errors else "unknown")
        )

    def _extract_results(
        self,
        results,
        text: str,
        img_shape: tuple[int, int],
        conf_threshold: float,
    ) -> list[SamTextResult]:
        img_h, img_w = img_shape
        output: list[SamTextResult] = []
        if not results:
            return output
        r = results[0]

        masks_obj = getattr(r, "masks", None)
        boxes_obj = getattr(r, "boxes", None)

        scores = None
        if boxes_obj is not None:
            conf_attr = getattr(boxes_obj, "conf", None)
            if conf_attr is not None:
                try:
                    scores = conf_attr.detach().cpu().numpy()
                except Exception:
                    scores = np.array(conf_attr)

        if masks_obj is not None and getattr(masks_obj, "data", None) is not None:
            try:
                masks_np = masks_obj.data.detach().cpu().numpy()
            except Exception:
                masks_np = np.array(masks_obj.data)

            for i in range(len(masks_np)):
                conf = float(scores[i]) if scores is not None and i < len(scores) else 1.0
                if conf < conf_threshold:
                    continue
                binary = (masks_np[i] > 0.5).astype(np.uint8)
                if not binary.any():
                    continue
                mask_h, mask_w = binary.shape[:2]
                sx = img_w / mask_w if mask_w else 1.0
                sy = img_h / mask_h if mask_h else 1.0

                contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_KCOS)
                if not contours:
                    continue
                contour = max(contours, key=cv2.contourArea)
                if len(contour) < 3:
                    continue
                polygon = [(float(p[0][0] * sx), float(p[0][1] * sy)) for p in contour]

                ys, xs = np.where(binary)
                bbox = (
                    float(xs.min() * sx),
                    float(ys.min() * sy),
                    float(xs.max() * sx),
                    float(ys.max() * sy),
                )
                output.append(SamTextResult(text=text, confidence=conf, bbox=bbox, polygon=polygon))
            return output

        if boxes_obj is not None and len(boxes_obj) > 0:
            xyxy = boxes_obj.xyxy.detach().cpu().numpy()
            for i in range(len(xyxy)):
                conf = float(scores[i]) if scores is not None and i < len(scores) else 1.0
                if conf < conf_threshold:
                    continue
                x1, y1, x2, y2 = xyxy[i][:4]
                polygon = [(float(x1), float(y1)), (float(x2), float(y1)), (float(x2), float(y2)), (float(x1), float(y2))]
                output.append(
                    SamTextResult(text=text, confidence=conf, bbox=(float(x1), float(y1), float(x2), float(y2)), polygon=polygon)
                )
            return output

        return output


def load_sam(path: Path) -> LoadedSam:
    try:
        from ultralytics import SAM

        model = SAM(str(path))
        return LoadedSam(path=path, model=model, kind="sam")
    except Exception:
        from ultralytics import YOLO

        model = YOLO(str(path))
        return LoadedSam(path=path, model=model, kind="yolo")
