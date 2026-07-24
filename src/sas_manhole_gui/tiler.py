from __future__ import annotations

from sas_manhole_gui.raster_layer import PixelWindow


def _axis_offsets(total: int, tile_size: int, stride: int) -> list[int]:
    if total <= tile_size:
        return [0]
    offsets = list(range(0, total - tile_size + 1, stride))
    last = total - tile_size
    if offsets[-1] != last:
        offsets.append(last)
    return offsets


def generate_tiles_indexed(
    width: int, height: int, tile_size: int = 640, overlap: float = 0.2
) -> list[tuple[int, int, PixelWindow]]:
    tile_size = max(1, tile_size)
    stride = max(1, int(tile_size * (1 - overlap)))
    xs = _axis_offsets(width, tile_size, stride)
    ys = _axis_offsets(height, tile_size, stride)
    tiles = []
    for row_idx, y in enumerate(ys):
        for col_idx, x in enumerate(xs):
            w = min(tile_size, width - x)
            h = min(tile_size, height - y)
            tiles.append((row_idx, col_idx, PixelWindow(col_off=x, row_off=y, width=w, height=h)))
    return tiles


def generate_tiles(width: int, height: int, tile_size: int = 640, overlap: float = 0.2) -> list[PixelWindow]:
    return [window for _row, _col, window in generate_tiles_indexed(width, height, tile_size, overlap)]
