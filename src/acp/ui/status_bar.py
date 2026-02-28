"""Status bar with server and agent running indicators."""

from __future__ import annotations

import webbrowser

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from qfluentwidgets import BodyLabel, FluentIcon as FIF
from qfluentwidgets.common.icon import toQIcon


class StatusLight(QFrame):
    """Small circular indicator (green=on, gray=off)."""

    def __init__(self, parent=None, size: int = 8):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._on = False

    def set_on(self, on: bool):
        if self._on != on:
            self._on = on
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(76, 175, 80) if self._on else QColor(100, 100, 100)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, self.width() - 2, self.height() - 2)


class StatusBar(QFrame):
    """Bottom status bar with server and agent lights."""

    link_clicked = pyqtSignal(str)
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusBar")
        self.setFixedHeight(28)
        self.setStyleSheet("""
            #statusBar {
                background-color: rgba(0, 0, 0, 0.3);
                border-top: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)

        self.server_light = StatusLight(self)
        self.server_label = BodyLabel("Server", self)
        self.server_label.setStyleSheet("color: gray; font-size: 12px;")
        self.server_link = QLabel(self)
        self.server_link.setStyleSheet(
            "color: #4CAF50; font-size: 12px; text-decoration: underline;"
        )
        self.server_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.server_link.mousePressEvent = lambda e: self._on_server_link_click(e)
        self.server_link.hide()

        layout.addWidget(self.server_light)
        layout.addWidget(self.server_label)
        layout.addWidget(self.server_link)

        self.agent_widgets: dict[str, tuple[StatusLight, QLabel]] = {}
        for name in ("Codex", "Gemini"):
            light = StatusLight(self)
            lbl = BodyLabel(name, self)
            lbl.setStyleSheet("color: gray; font-size: 12px;")
            layout.addSpacing(8)
            layout.addWidget(light)
            layout.addWidget(lbl)
            self.agent_widgets[name.lower()] = (light, lbl)

        layout.addStretch(1)
        self.refreshBtn = QToolButton(self)
        self.refreshBtn.setIcon(toQIcon(FIF.SYNC))
        self.refreshBtn.setToolTip("Refresh status")
        self.refreshBtn.setFixedSize(24, 24)
        self.refreshBtn.clicked.connect(self.refresh_requested.emit)
        layout.addWidget(self.refreshBtn)

    def _on_server_link_click(self, event):
        url = self.server_link.property("url")
        if url:
            webbrowser.open(url)

    def update_status(
        self,
        server_running: bool,
        server_url: str,
        codex_running: bool,
        gemini_running: bool,
    ):
        self.server_light.set_on(server_running)
        if server_running and server_url:
            self.server_label.setText("Server running at")
            self.server_link.setText(server_url)
            self.server_link.setProperty("url", f"http://{server_url}")
            self.server_link.setToolTip("Click to open in browser")
            self.server_link.show()
        else:
            self.server_label.setText("Server")
            self.server_link.hide()

        for name, (light, _) in self.agent_widgets.items():
            light.set_on(
                codex_running if name == "codex" else gemini_running
            )
