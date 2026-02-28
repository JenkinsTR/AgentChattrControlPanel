from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from qfluentwidgets import (
    ScrollArea, SettingCardGroup, PrimaryPushSettingCard, PushSettingCard,
    InfoBar, InfoBarPosition, FluentIcon as FIF
)
from qfluentwidgets.components.widgets.label import CaptionLabel

from ...core.state import AppState, save_state
from ...core.processes import ServerRunner
from ...core.agentchattr import is_port_listening, start_wrapper_console, find_wrapper_pids, stop_process_tree, get_running_wrapper_agents
from ...core.checks import check_agentchattr_venv, check_agentchattr_repo
from ...core.codex_windows_acl import inspect_workspace_acl_for_codex
from ...core.toml_config import load_toml, save_toml, apply_workspace_single
from ..log_bus import LogBus


# Button color overrides for Run tab
STYLE_RUNNING = "background-color: #2ecc71; color: white;"
STYLE_STOP = "background-color: #e74c3c; color: white;"
STYLE_STOP_DISABLED = "background-color: #555; color: #888;"


class RunInterface(ScrollArea):
    status_changed = pyqtSignal()
    _status_ready = pyqtSignal(bool, bool, bool, bool)

    def __init__(self, parent, state: AppState, bus: LogBus):
        super().__init__(parent)
        self._last_status: tuple[bool, str, bool, bool] | None = None
        self._gathering = False
        self._status_ready.connect(self._apply_run_status)
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

        self._refresh_run_status()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_run_status()

    def _wrapper_running(self, agent: str) -> bool:
        return len(find_wrapper_pids(agent)) > 0

    def _any_wrappers_running(self) -> bool:
        for a in ("codex", "gemini", "claude", "codex_A", "gemini_A", "codex_B", "gemini_B"):
            if self._wrapper_running(a):
                return True
        return False

    def _gather_status(self) -> tuple[bool, bool, bool, bool]:
        """Expensive psutil calls - run in background thread. Single process iteration."""
        try:
            port = int(self.state.server_port)
        except (ValueError, TypeError):
            port = 8300
        host = self.state.server_host.strip() or "127.0.0.1"
        server_running = self.server.running() or is_port_listening(port, host)
        running = get_running_wrapper_agents()
        codex_running = "codex" in running
        gemini_running = "gemini" in running
        wrappers_running = len(running) > 0
        return (server_running, codex_running, gemini_running, wrappers_running)

    def _apply_run_status(
        self,
        server_running: bool,
        codex_running: bool,
        gemini_running: bool,
        wrappers_running: bool,
    ) -> None:
        """Update UI from pre-computed status. Must run on main thread (via signal)."""
        self._gathering = False
        host = self.state.server_host.strip() or "127.0.0.1"
        try:
            port = int(self.state.server_port)
        except (ValueError, TypeError):
            port = 8300
        server_url = f"{host}:{port}" if server_running else ""
        self._last_status = (server_running, server_url, codex_running, gemini_running)

        # Server Start button
        if server_running:
            self.startServerCard.button.setText("Running")
            self.startServerCard.button.setEnabled(False)
            self.startServerCard.button.setStyleSheet(STYLE_RUNNING)
        else:
            self.startServerCard.button.setText("Start")
            self.startServerCard.button.setEnabled(True)
            self.startServerCard.button.setStyleSheet("")

        # Stop server button
        self.stopServerCard.button.setEnabled(server_running)
        self.stopServerCard.button.setStyleSheet(
            STYLE_STOP if server_running else STYLE_STOP_DISABLED
        )

        # Codex Start button
        if codex_running:
            self.startCodexCard.button.setText("Running")
            self.startCodexCard.button.setEnabled(False)
            self.startCodexCard.button.setStyleSheet(STYLE_RUNNING)
        else:
            self.startCodexCard.button.setText("Start")
            self.startCodexCard.button.setEnabled(True)
            self.startCodexCard.button.setStyleSheet("")

        # Gemini Start button
        if gemini_running:
            self.startGeminiCard.button.setText("Running")
            self.startGeminiCard.button.setEnabled(False)
            self.startGeminiCard.button.setStyleSheet(STYLE_RUNNING)
        else:
            self.startGeminiCard.button.setText("Start")
            self.startGeminiCard.button.setEnabled(True)
            self.startGeminiCard.button.setStyleSheet("")

        # Stop wrappers button
        self.stopWrappersCard.button.setEnabled(wrappers_running)
        self.stopWrappersCard.button.setStyleSheet(
            STYLE_STOP if wrappers_running else STYLE_STOP_DISABLED
        )

        self.status_changed.emit()

    def _refresh_run_status(self) -> None:
        """Gather status in background thread, apply on main thread via signal. Debounced."""
        if self._gathering:
            return
        self._gathering = True

        def do_gather():
            try:
                data = self._gather_status()
                self._status_ready.emit(*data)
            except Exception:
                QTimer.singleShot(0, lambda: setattr(self, "_gathering", False))

        threading.Thread(target=do_gather, daemon=True).start()

    def get_status(self) -> tuple[bool, str, bool, bool]:
        """Return (server_running, server_url, codex_running, gemini_running). Uses cached value if available."""
        if self._last_status is not None:
            return self._last_status
        try:
            port = int(self.state.server_port)
        except (ValueError, TypeError):
            port = 8300
        host = self.state.server_host.strip() or "127.0.0.1"
        server_running = self.server.running() or is_port_listening(port)
        server_url = f"{host}:{port}" if server_running else ""
        return (
            server_running,
            server_url,
            self._wrapper_running("codex"),
            self._wrapper_running("gemini"),
        )

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
        self.info(True, "Starting…", "Spawning server process…")
        self.startServerCard.button.setText("Running")
        self.startServerCard.button.setEnabled(False)
        self.startServerCard.button.setStyleSheet(STYLE_RUNNING)

        def on_line(line: str):
            self.bus.log(f"[SERVER] {line}")

        def on_token(tok: str):
            def do_on_main():
                self.state.last_session_token = tok
                save_state(self.state)
                self.info(True, "Server started", "Session token captured (see state.json).")
                self.bus.log("[RUN] Session token captured")
                self._refresh_run_status()
            QTimer.singleShot(0, do_on_main)

        def on_exit(code: int):
            def do_on_main():
                self.bus.log(f"[RUN] Server exited with code {code}")
                self.info(code == 0, "Server stopped" if code == 0 else "Server exited", f"Exit code: {code}")
                self._refresh_run_status()
            QTimer.singleShot(0, do_on_main)

        def on_spawned():
            def do_on_main():
                self.bus.log("[RUN] Server process spawned; waiting for session token…")
                self.info(True, "Process started", "Server process running. Check Logs for output.")
            QTimer.singleShot(0, do_on_main)

        self.server.start(
            root=root,
            host=host,
            port=port,
            allow_network=allow_network,
            on_line=on_line,
            on_token=on_token,
            on_exit=on_exit,
            on_spawned=on_spawned,
        )

    def stop_server(self):
        self.server.stop()
        self.bus.log("[RUN] Server stop requested")
        self.info(True, "Stopped", "Server process terminated (best effort).")
        self._refresh_run_status()

    def open_chat(self):
        host = self.state.server_host.strip() or "127.0.0.1"
        port = int(self.state.server_port)
        self.bus.log(f"[RUN] Open browser http://{host}:{port}")
        webbrowser.open(f"http://{host}:{port}")

    def start_wrapper(self, agent_name: str):
        if self._wrapper_running(agent_name):
            self.info(False, "Already running", f"{agent_name} wrapper is already running.")
            return
        root = self.repo_root()
        if not root:
            self.info(False, "Missing agentchattr path", "Set it in Setup.")
            return
        ws = self.state.active_workspace.strip()
        if agent_name == "codex" and ws:
            acl = inspect_workspace_acl_for_codex(ws)
            if not acl.ok:
                self.bus.log(f"[RUN] Codex ACL preflight blocked launch: {acl.title} | {acl.detail}")
                self.info(False, "Codex ACL preflight failed", f"{acl.title}: {self._short_msg(acl.detail)}")
                return
        if ws:
            cfg = root / "config.toml"
            if cfg.exists():
                try:
                    doc = load_toml(cfg)
                    apply_workspace_single(doc, ws, agents=None)
                    save_toml(cfg, doc)
                    self.bus.log(f"[RUN] Applied workspace cwd: {ws}")
                except Exception as e:
                    self.bus.log(f"[RUN] Could not apply workspace: {e}")
        try:
            start_wrapper_console(root, agent_name)
            self.bus.log(f"[RUN] Wrapper launched: {agent_name}")
            self.info(True, "Wrapper launched", f"{agent_name}")
            # Optimistic update: show Running immediately for the started agent
            if agent_name in ("codex", "gemini"):
                sr = self._last_status[0] if self._last_status else False
                cr = agent_name == "codex" or (self._last_status[2] if self._last_status else False)
                gr = agent_name == "gemini" or (self._last_status[3] if self._last_status else False)
                self._status_ready.emit(sr, cr, gr, True)
            QTimer.singleShot(500, self._refresh_run_status)
            QTimer.singleShot(1500, self._refresh_run_status)
        except Exception as e:
            self.bus.log(f"[ERROR] {e}")
            self.info(False, "Failed", str(e))

    def _short_msg(self, text: str, max_len: int = 220) -> str:
        t = (text or "").replace("\r", " ").replace("\n", " ").strip()
        if len(t) <= max_len:
            return t
        return t[: max_len - 3] + "..."

    def stop_wrappers(self):
        def do_stop():
            killed = 0
            for agent in ("codex", "gemini", "claude", "codex_A", "gemini_A", "codex_B", "gemini_B"):
                for pid in find_wrapper_pids(agent):
                    stop_process_tree(pid)
                    killed += 1

            def on_done():
                self.bus.log(f"[RUN] Wrappers stop requested; killed {killed} process trees")
                self.info(True, "Wrappers stopped", f"Killed {killed} process trees (best effort).")
                self._refresh_run_status()

            QTimer.singleShot(0, on_done)

        threading.Thread(target=do_stop, daemon=True).start()
