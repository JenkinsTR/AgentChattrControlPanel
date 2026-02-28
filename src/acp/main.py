from __future__ import annotations

import sys

from PyQt6.QtCore import qInstallMessageHandler
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from .core.state import load_state
from .ui.main_window import MainWindow


_prev_qt_handler = None

def _qt_message_handler(mode, context, message: str):
    # Filter a noisy but harmless warning that can be produced by some widget/font styling paths:
    # "QFont::setPointSize: Point size <= 0 (-1), must be greater than 0"
    if message and message.startswith("QFont::setPointSize: Point size <= 0"):
        return
    if _prev_qt_handler is not None:
        try:
            _prev_qt_handler(mode, context, message)
        except Exception:
            # If previous handler fails, fall back to default behavior (silence)
            pass


def main() -> int:
    global _prev_qt_handler

    app = QApplication(sys.argv)

    # Set an explicit, valid point-size application font to reduce inheritance weirdness
    app.setFont(QFont("Segoe UI", 10))

    # Install Qt log filter (keeps your console/logs clean)
    _prev_qt_handler = qInstallMessageHandler(_qt_message_handler)

    st = load_state()
    w = MainWindow(st)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
