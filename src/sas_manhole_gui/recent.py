from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

_MAX_RECENT = 5
_KEY_FOLDERS = "recent/folders"
_KEY_FILES = "recent/files"
_KEY_LAST_DIR = "recent/last_dir"


def _settings() -> QSettings:
    return QSettings("SAS", "ManholeGUI")


def _load(key: str) -> list[str]:
    raw = _settings().value(key, [])
    if isinstance(raw, str):
        return [raw] if raw else []
    return [str(x) for x in raw or []]


def _save(key: str, values: list[str]) -> None:
    _settings().setValue(key, values[:_MAX_RECENT])


def add_folder(path: Path) -> None:
    p = str(path)
    items = [x for x in _load(_KEY_FOLDERS) if x != p]
    items.insert(0, p)
    _save(_KEY_FOLDERS, items)
    _settings().setValue(_KEY_LAST_DIR, p)


def add_files(paths: list[Path]) -> None:
    if not paths:
        return
    existing = _load(_KEY_FILES)
    strs = [str(p) for p in paths]
    combined = strs + [x for x in existing if x not in strs]
    _save(_KEY_FILES, combined)
    parent = str(paths[0].parent)
    _settings().setValue(_KEY_LAST_DIR, parent)


def recent_folders() -> list[str]:
    return [p for p in _load(_KEY_FOLDERS) if Path(p).exists()]


def recent_files() -> list[str]:
    return [p for p in _load(_KEY_FILES) if Path(p).exists()]


def last_directory() -> str:
    val = _settings().value(_KEY_LAST_DIR, "")
    return str(val) if val else ""


def clear_recent() -> None:
    s = _settings()
    s.remove(_KEY_FOLDERS)
    s.remove(_KEY_FILES)
