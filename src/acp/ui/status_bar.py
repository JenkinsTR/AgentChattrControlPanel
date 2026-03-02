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
    """Bottom status bar with server and dynamic agent lights."""

    link_clicked = pyqtSignal(str)
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusBar")
        self.setFixedHeight(28)
        self.setStyleSheet(
            """
            #statusBar {
                background-color: rgba(0, 0, 0, 0.3);
                border-top: 1px solid rgba(255, 255, 255, 0.08);
            }
        """
        )

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(12, 4, 12, 4)
        self.layout.setSpacing(16)

        self.server_light = StatusLight(self)
        self.server_label = BodyLabel("Server", self)
        self.server_label.setStyleSheet("color: gray; font-size: 12px;")
        self.server_link = QLabel(self)
        self.server_link.setStyleSheet("color: #4CAF50; font-size: 12px; text-decoration: underline;")
        self.server_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.server_link.mousePressEvent = lambda e: self._on_server_link_click(e)
        self.server_link.hide()

        self.layout.addWidget(self.server_light)
        self.layout.addWidget(self.server_label)
        self.layout.addWidget(self.server_link)

        self.agent_container = QWidget(self)
        self.agent_layout = QHBoxLayout(self.agent_container)
        self.agent_layout.setContentsMargins(0, 0, 0, 0)
        self.agent_layout.setSpacing(10)
        self.layout.addWidget(self.agent_container)

        self.agent_widgets: dict[str, tuple[StatusLight, QLabel]] = {}

        self.layout.addStretch(1)
        self.refreshBtn = QToolButton(self)
        self.refreshBtn.setIcon(toQIcon(FIF.SYNC))
        self.refreshBtn.setToolTip("Refresh status")
        self.refreshBtn.setFixedSize(24, 24)
        self.refreshBtn.clicked.connect(self.refresh_requested.emit)
        self.layout.addWidget(self.refreshBtn)

    def _on_server_link_click(self, event):
        url = self.server_link.property("url")
        if url:
            webbrowser.open(url)

    def set_agents(self, agent_names: list[str]):
        existing = {name.lower(): name for name in self.agent_widgets.keys()}
        desired = [n.strip() for n in agent_names if n and n.strip()]
        desired_lower = {d.lower() for d in desired}

        for name in list(existing.values()):
            if name.lower() not in desired_lower:
                light, lbl = self.agent_widgets.pop(name)
                self.agent_layout.removeWidget(light)
                self.agent_layout.removeWidget(lbl)
                light.deleteLater()
                lbl.deleteLater()

        for name in desired:
            key_match = None
            for existing_name in self.agent_widgets.keys():
                if existing_name.lower() == name.lower():
                    key_match = existing_name
                    break
            if key_match is not None:
                continue

            light = StatusLight(self)
            lbl = BodyLabel(name, self)
            lbl.setStyleSheet("color: gray; font-size: 12px;")
            self.agent_layout.addWidget(light)
            self.agent_layout.addWidget(lbl)
            self.agent_widgets[name] = (light, lbl)

    def update_status(self, server_running: bool, server_url: str, agent_status: dict[str, bool]):
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

        names = list(agent_status.keys())
        self.set_agents(names)

        status_lower = {k.lower(): bool(v) for k, v in agent_status.items()}
        for name, (light, _) in self.agent_widgets.items():
            light.set_on(status_lower.get(name.lower(), False))
