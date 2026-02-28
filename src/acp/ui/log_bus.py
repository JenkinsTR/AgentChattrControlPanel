from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

class LogBus(QObject):
    line = pyqtSignal(str)

    def log(self, msg: str) -> None:
        self.line.emit(msg)
