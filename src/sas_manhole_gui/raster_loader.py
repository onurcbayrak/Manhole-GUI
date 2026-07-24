from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from sas_manhole_gui.raster_layer import RasterLayer


class RasterOpenWorker(QThread):
    file_opened = Signal(str, object, object)
    file_failed = Signal(str, str)
    progress = Signal(int, int)
    finished_all = Signal()

    def __init__(self, paths: list[Path], parent=None):
        super().__init__(parent)
        self.paths = paths

    def run(self) -> None:
        total = len(self.paths)
        for i, path in enumerate(self.paths, start=1):
            try:
                layer = RasterLayer.open(path)
                thumbnail = layer.thumbnail(120)
            except Exception as exc:
                self.file_failed.emit(str(path), str(exc))
                self.progress.emit(i, total)
                continue
            self.file_opened.emit(str(path), layer, thumbnail)
            self.progress.emit(i, total)
        self.finished_all.emit()
