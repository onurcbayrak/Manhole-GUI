from __future__ import annotations

from collections import deque
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal


class UndoManager(QObject):
    stack_changed = Signal(int)

    MAX_STEPS = 3

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._stack: deque[tuple[str, Callable[[], None]]] = deque(maxlen=self.MAX_STEPS)

    def push(self, description: str, undo_fn: Callable[[], None]) -> None:
        self._stack.append((description, undo_fn))
        self.stack_changed.emit(len(self._stack))

    def undo(self) -> Optional[str]:
        if not self._stack:
            return None
        description, undo_fn = self._stack.pop()
        try:
            undo_fn()
        except Exception:
            return None
        self.stack_changed.emit(len(self._stack))
        return description

    def clear(self) -> None:
        self._stack.clear()
        self.stack_changed.emit(0)

    def depth(self) -> int:
        return len(self._stack)
