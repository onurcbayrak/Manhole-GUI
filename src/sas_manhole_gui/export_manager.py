from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import rasterio
from PIL import Image, ImageDraw
from PySide6.QtGui import QImage
from shapely.geometry import Polygon

from sas_manhole_gui.project_state import ClassDef, Detection, ProjectRaster
from sas_manhole_gui.raster_layer import PixelWindow, RasterLayer
from sas_manhole_gui.tiler import generate_tiles_indexed

VISUAL_NAME_FULL = "{stem}_detections{ext}"
VISUAL_NAME_TILE = "{stem}_tile_r{row:03d}_c{col:03d}_640x640{ext}"


def _class_lookup(classes: list[ClassDef]) -> dict[int, ClassDef]:
    return {c.class_id: c for c in classes}


def _draw_detections(
    image: Image.Image,
    detections: list[Detection],
    classes: list[ClassDef],
    scale_x: float,
    scale_y: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> None:
    lookup = _class_lookup(classes)
    draw = ImageDraw.Draw(image)
    for det in detections:
        cdef = lookup.get(det.class_id)
        color = cdef.color if cdef else "#ff5c5c"
        name = cdef.name if cdef else f"class_{det.class_id}"
        x1 = (det.x_min - offset_x) * scale_x
        y1 = (det.y_min - offset_y) * scale_y
        x2 = (det.x_max - offset_x) * scale_x
        y2 = (det.y_max - offset_y) * scale_y
        if x2 < 0 or y2 < 0 or x1 > image.width or y1 > image.height:
            continue
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        label = f"{name} {det.confidence:.2f}" if det.source == "model" else name
        label_w = max(1, 7 * len(label))
        ty = max(0, y1 - 12)
        draw.rectangle([x1, ty, x1 + label_w, ty + 12], fill=color)
        draw.text((x1 + 1, ty), label, fill="#101010")


def _qimage_to_pil(qimage: QImage) -> Image.Image:
    qimage = qimage.convertToFormat(QImage.Format.Format_RGB888)
    width, height = qimage.width(), qimage.height()
    bytes_per_line = qimage.bytesPerLine()
    buf = qimage.constBits()
    arr = np.frombuffer(buf, dtype=np.uint8, count=height * bytes_per_line).reshape(height, bytes_per_line)
    arr = arr[:, : width * 3].reshape(height, width, 3)
    return Image.fromarray(arr.copy(), mode="RGB")


def _save_as_geotiff(image: Image.Image, layer: RasterLayer, out_w: int, out_h: int, out_path: Path) -> None:
    arr = np.array(image.convert("RGB"))
    transform = layer.transform * rasterio.Affine.scale(layer.width / out_w, layer.height / out_h)
    profile = {
        "driver": "GTiff",
        "height": out_h,
        "width": out_w,
        "count": 3,
        "dtype": "uint8",
        "crs": layer.crs,
        "transform": transform,
    }
    with rasterio.open(str(out_path), "w", **profile) as dst:
        for i in range(3):
            dst.write(arr[:, :, i], i + 1)


def export_visual_full(
    pr: ProjectRaster, out_dir: Path, classes: list[ClassDef], ext: str = ".png", max_dim: int = 4096
) -> Path:
    layer = pr.layer
    scale = min(1.0, max_dim / max(layer.width, layer.height))
    out_w = max(1, int(layer.width * scale))
    out_h = max(1, int(layer.height * scale))
    qimage = layer.read_region_as_qimage(PixelWindow(0, 0, layer.width, layer.height), out_w, out_h)
    image = _qimage_to_pil(qimage)
    _draw_detections(image, pr.detections, classes, scale_x=out_w / layer.width, scale_y=out_h / layer.height)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / VISUAL_NAME_FULL.format(stem=pr.path.stem, ext=ext)

    if ext.lower() in (".tif", ".tiff"):
        _save_as_geotiff(image, layer, out_w, out_h, out_path)
    else:
        image.convert("RGB").save(out_path)
    return out_path


def export_visual_tiles(
    pr: ProjectRaster, out_dir: Path, classes: list[ClassDef], ext: str = ".png", tile_size: int = 640
) -> list[Path]:
    layer = pr.layer
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for row_idx, col_idx, window in generate_tiles_indexed(layer.width, layer.height, tile_size=tile_size, overlap=0.0):
        arr = layer.read_tile_array(window, tile_size)
        image = Image.fromarray(arr, mode="RGB")
        relevant = [
            d
            for d in pr.detections
            if not (
                d.x_max <= window.col_off
                or d.x_min >= window.col_off + window.width
                or d.y_max <= window.row_off
                or d.y_min >= window.row_off + window.height
            )
        ]
        scale_x = tile_size / window.width
        scale_y = tile_size / window.height
        _draw_detections(image, relevant, classes, scale_x=scale_x, scale_y=scale_y, offset_x=window.col_off, offset_y=window.row_off)
        out_path = out_dir / VISUAL_NAME_TILE.format(stem=pr.path.stem, row=row_idx, col=col_idx, ext=ext)
        image.save(out_path)
        paths.append(out_path)
    return paths


_VECTOR_COLUMNS = [
    "id",
    "image",
    "class_id",
    "class_name",
    "confidence",
    "col_px",
    "row_px",
    "w_px",
    "h_px",
    "bbox_px",
    "gsd_m",
    "w_m",
    "h_m",
    "area_m2",
    "edited",
    "source",
]


def _pixel_bbox_to_world_polygon(layer: RasterLayer, det: Detection) -> Polygon:
    corners = [
        (det.x_min, det.y_min),
        (det.x_max, det.y_min),
        (det.x_max, det.y_max),
        (det.x_min, det.y_max),
    ]
    world_corners = [layer.pixel_to_world(cx, cy) for cx, cy in corners]
    return Polygon(world_corners)


def build_detections_table(rasters: Iterable[ProjectRaster], classes: list[ClassDef]):
    import geopandas as gpd

    lookup = _class_lookup(classes)
    rows: list[dict] = []
    geometries: list[Polygon] = []
    crs = None
    for pr in rasters:
        if crs is None:
            crs = pr.layer.crs
        gsd = pr.layer.gsd_meters()
        for det in pr.detections:
            cdef = lookup.get(det.class_id)
            col_px = float(det.x_min)
            row_px = float(det.y_min)
            w_px = max(0.0, float(det.x_max - det.x_min))
            h_px = max(0.0, float(det.y_max - det.y_min))
            bbox_px = int(round(w_px * h_px))
            if gsd is not None and gsd > 0:
                w_m: Optional[float] = w_px * gsd
                h_m: Optional[float] = h_px * gsd
                area_m2: Optional[float] = w_m * h_m
            else:
                w_m = None
                h_m = None
                area_m2 = None
            rows.append(
                {
                    "id": det.det_id,
                    "image": pr.path.name,
                    "class_id": det.class_id,
                    "class_name": cdef.name if cdef else f"class_{det.class_id}",
                    "confidence": det.confidence,
                    "col_px": col_px,
                    "row_px": row_px,
                    "w_px": w_px,
                    "h_px": h_px,
                    "bbox_px": bbox_px,
                    "gsd_m": gsd,
                    "w_m": w_m,
                    "h_m": h_m,
                    "area_m2": area_m2,
                    "edited": det.edited,
                    "source": det.source,
                }
            )
            geometries.append(_pixel_bbox_to_world_polygon(pr.layer, det))

    if not rows:
        return gpd.GeoDataFrame(columns=_VECTOR_COLUMNS + ["geometry"], geometry="geometry", crs=crs)
    gdf = gpd.GeoDataFrame(rows, geometry=geometries, crs=crs)
    return gdf[_VECTOR_COLUMNS + ["geometry"]]


def export_vector(
    rasters: Iterable[ProjectRaster], classes: list[ClassDef], out_dir: Path, stem: str, formats: set[str]
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    gdf = build_detections_table(rasters, classes)
    outputs: list[Path] = []

    if "csv" in formats:
        csv_path = out_dir / f"{stem}_detections.csv"
        flat = gdf.copy()
        flat["geometry_wkt"] = flat.geometry.apply(lambda g: g.wkt if g is not None else "")
        flat.drop(columns="geometry").to_csv(csv_path, index=False, encoding="utf-8-sig")
        outputs.append(csv_path)

    if not gdf.empty:
        if "shp" in formats:
            shp_path = out_dir / f"{stem}_detections.shp"
            gdf.to_file(shp_path, driver="ESRI Shapefile")
            outputs.append(shp_path)
        if "geojson" in formats:
            geojson_path = out_dir / f"{stem}_detections.geojson"
            gdf.to_file(geojson_path, driver="GeoJSON")
            outputs.append(geojson_path)
        if "gpkg" in formats:
            gpkg_path = out_dir / f"{stem}_detections.gpkg"
            gdf.to_file(gpkg_path, driver="GPKG", layer="detections")
            outputs.append(gpkg_path)

    return outputs
