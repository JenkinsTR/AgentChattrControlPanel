from __future__ import annotations

import webbrowser
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout

from qfluentwidgets import (
    ScrollArea, SettingCardGroup, PrimaryPushSettingCard, PushSettingCard,
    InfoBar, InfoBarPosition, FluentIcon as FIF
)
from qfluentwidgets.components.widgets.label import CaptionLabel

from ...core.state import AppState, save_state
from ...core.processes import ServerRunner
from ...core.agentchattr import is_port_listening, start_wrapper_console, find_wrapper_pids, stop_process_tree
from ...core.checks import check_agentchattr_venv, check_agentchattr_repo
from ..log_bus import LogBus


class RunInterface(ScrollArea):
    def __init__(self, parent, state: AppState, bus: LogBus):
        super().__init__(parent)
        self.state = state
        self.bus = bus
        self.setObjectName("run")

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.setWidgetResizable(True)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(24, 24, 24, 24)
        self.v.setSpacing(18)

        hint = CaptionLabel(
            "Start server → Open chat → Start Codex/Gemini wrappers in separate consoles.",
            self.container,
        )
        hint.setStyleSheet("color: gray; padding-bottom: 4px;")
        self.v.addWidget(hint)

        self.group = SettingCardGroup("Run control", self.container)
        self.v.addWidget(self.group)

        self.server = ServerRunner()

        self.startServerCard = PrimaryPushSettingCard(
            "Start",
            FIF.PLAY,
            "Start agentchattr server",
            "Starts run.py (adds --allow-network if server.host is not localhost).",
            parent=self.container,
        )
        self.startServerCard.clicked.connect(self.start_server)
        self.group.addSettingCard(self.startServerCard)

        self.stopServerCard = PushSettingCard(
            "Stop",
            getattr(FIF, "PAUSE", FIF.CLOSE),
            "Stop agentchattr server",
            "Kills the server process tree.",
            parent=self.container,
        )
        self.stopServerCard.clicked.connect(self.stop_server)
        self.group.addSettingCard(self.stopServerCard)

        self.openChatCard = PushSettingCard(
            "Open",
            getattr(FIF, "LINK", FIF.GLOBE),
            "Open chat in browser",
            "Opens http://<host>:<port>.",
            parent=self.container,
        )
        self.openChatCard.clicked.connect(self.open_chat)
        self.group.addSettingCard(self.openChatCard)

        self.startCodexCard = PrimaryPushSettingCard(
            "Start",
            getattr(FIF, "ROBOT", FIF.IOT),
            "Start Codex wrapper",
            "Opens a console window running: python wrapper.py codex",
            parent=self.container,
        )
        self.startCodexCard.clicked.connect(lambda: self.start_wrapper("codex"))
        self.group.addSettingCard(self.startCodexCard)

        self.startGeminiCard = PrimaryPushSettingCard(
            "Start",
            getattr(FIF, "ROBOT", FIF.IOT),
            "Start Gemini wrapper",
            "Opens a console window running: python wrapper.py gemini",
            parent=self.container,
        )
        self.startGeminiCard.clicked.connect(lambda: self.start_wrapper("gemini"))
        self.group.addSettingCard(self.startGeminiCard)

        self.stopWrappersCard = PushSettingCard(
            "Stop",
            getattr(FIF, "CLOSE", FIF.CANCEL),
            "Stop wrappers (best-effort)",
            "Finds wrapper.py processes and kills them.",
            parent=self.container,
        )
        self.stopWrappersCard.clicked.connect(self.stop_wrappers)
        self.group.addSettingCard(self.stopWrappersCard)

    def info(self, ok: bool, title: str, msg: str):
        (InfoBar.success if ok else InfoBar.error)(
            title, msg, parent=self, position=InfoBarPosition.TOP, duration=2500 if ok else 6500
        )

    def repo_root(self) -> Path | None:
        p = self.state.agentchattr_root.strip()
        return Path(p) if p else None

    def start_server(self):
        root = self.repo_root()
        if not root:
            self.info(False, "Missing agentchattr path", "Set it in Setup.")
            return
        if not check_agentchattr_repo(root).ok:
            self.info(False, "Not an agentchattr repo", "run.py/config.toml missing.")
            return
        if not check_agentchattr_venv(root).ok:
            self.info(False, "Missing agentchattr venv", "Use Setup → Create/repair venv first.")
            return

        host = self.state.server_host.strip() or "127.0.0.1"
        port = int(self.state.server_port)
        allow_network = host not in ("127.0.0.1", "localhost", "::1")

        self.bus.log(f"[RUN] Starting server at http://{host}:{port} (allow_network={allow_network})")

        def on_line(line: str):
            self.bus.log(f"[SERVER] {line}")

        def on_token(tok: str):
            self.state.last_session_token = tok
            save_state(self.state)
            self.info(True, "Server started", "Session token captured (see state.json).")
            self.bus.log("[RUN] Session token captured")

        def on_exit(code: int):
            self.bus.log(f"[RUN] Server exited with code {code}")
            self.info(code == 0, "Server stopped" if code == 0 else "Server exited", f"Exit code: {code}")

        self.server.start(
            root=root,
            host=host,
            port=port,
            allow_network=allow_network,
            on_line=on_line,
            on_token=on_token,
            on_exit=on_exit,
        )

    def stop_server(self):
        self.server.stop()
        self.bus.log("[RUN] Server stop requested")
        self.info(True, "Stopped", "Server process terminated (best effort).")

    def open_chat(self):
        host = self.state.server_host.strip() or "127.0.0.1"
        port = int(self.state.server_port)
        self.bus.log(f"[RUN] Open browser http://{host}:{port}")
        webbrowser.open(f"http://{host}:{port}")

    def start_wrapper(self, agent_name: str):
        root = self.repo_root()
        if not root:
            self.info(False, "Missing agentchattr path", "Set it in Setup.")
            return
        try:
            start_wrapper_console(root, agent_name)
            self.bus.log(f"[RUN] Wrapper launched: {agent_name}")
            self.info(True, "Wrapper launched", f"{agent_name}")
        except Exception as e:
            self.bus.log(f"[ERROR] {e}")
            self.info(False, "Failed", str(e))

    def stop_wrappers(self):
        killed = 0
        for agent in ("codex", "gemini", "claude", "codex_A", "gemini_A", "codex_B", "gemini_B"):
            for pid in find_wrapper_pids(agent):
                stop_process_tree(pid)
                killed += 1
        self.bus.log(f"[RUN] Wrappers stop requested; killed {killed} process trees")
        self.info(True, "Wrappers stopped", f"Killed {killed} process trees (best effort).")
