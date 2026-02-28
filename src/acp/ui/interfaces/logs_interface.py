from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout

from qfluentwidgets import ScrollArea, SettingCardGroup, PlainTextEdit, PushSettingCard, FluentIcon as FIF

from ...core.state import AppState
from ..log_bus import LogBus
from ..ansi import ansi_to_html


class LogsInterface(ScrollArea):
    def __init__(self, parent, state: AppState, bus: LogBus):
        super().__init__(parent)
        self.state = state
        self.bus = bus
        self.setObjectName("logs")

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.setWidgetResizable(True)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(24, 24, 24, 24)
        self.v.setSpacing(18)

        self.group = SettingCardGroup("Logs", self.container)
        self.v.addWidget(self.group)

        self.log = PlainTextEdit(self.container)
        self.log.setReadOnly(True)
        self.v.addWidget(self.log)

        self.note = PushSettingCard(
            "Note",
            FIF.INFO,
            "What shows up here",
            "ACP streams command output here (git/pip/npm) and server stdout when started from ACP. "
            "Wrappers run in separate consoles by design (for reliable console injection).",
            parent=self.container
        )
        self.note.button.setEnabled(False)
        self.group.addSettingCard(self.note)

        self.bus.line.connect(self.append)

    def append(self, line: str):
        html = ansi_to_html(line)
        self.log.appendHtml(html)
