from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from qfluentwidgets import (
    ScrollArea,
    SettingCardGroup,
    PrimaryPushSettingCard,
    PushSettingCard,
    InfoBar,
    InfoBarPosition,
    FluentIcon as FIF,
)
from qfluentwidgets.components.widgets.label import CaptionLabel

from ...core.state import AppState, save_state
from ...core.processes import ServerRunner
from ...core.agentchattr import (
    find_wrapper_pids,
    get_running_wrapper_agents,
    is_port_listening,
    start_wrapper_console,
    stop_process_tree,
)
from ...core.checks import check_agentchattr_repo, check_agentchattr_venv
from ...core.codex_windows_acl import inspect_workspace_acl_for_codex
from ...core.toml_config import is_codex_agent, list_agent_defs, load_toml
from ..log_bus import LogBus


STYLE_RUNNING = "background-color: #2ecc71; color: white;"
STYLE_STOP = "background-color: #e74c3c; color: white;"
STYLE_STOP_DISABLED = "background-color: #555; color: #888;"


class RunInterface(ScrollArea):
    status_changed = pyqtSignal()
    _status_ready = pyqtSignal(object)

    def __init__(self, parent, state: AppState, bus: LogBus):
        super().__init__(parent)
        self._last_status: tuple[bool, str, dict[str, bool]] | None = None
        self._gathering = False
        self._status_ready.connect(self._apply_run_status)

        self.state = state
        self.bus = bus
        self.setObjectName("run")

        self._configured_agents: list[dict[str, str]] = []
        self._agent_rows: dict[str, dict[str, Any]] = {}

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.setWidgetResizable(True)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(24, 24, 24, 24)
        self.v.setSpacing(18)

        hint = CaptionLabel(
            "Start server, open chat, then launch wrappers for any configured agents.",
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

        self.reloadAgentsCard = PushSettingCard(
            "Reload",
            getattr(FIF, "SYNC", FIF.ROTATE),
            "Reload agents from config.toml",
            "Refreshes wrapper controls from current [agents] config.",
            parent=self.container,
        )
        self.reloadAgentsCard.clicked.connect(self.reload_agents)
        self.group.addSettingCard(self.reloadAgentsCard)

        self.stopWrappersCard = PushSettingCard(
            "Stop",
            getattr(FIF, "CLOSE", FIF.CANCEL),
            "Stop wrappers (best-effort)",
            "Finds wrapper.py processes and kills them.",
            parent=self.container,
        )
        self.stopWrappersCard.clicked.connect(self.stop_wrappers)
        self.group.addSettingCard(self.stopWrappersCard)

        self.agentHint = CaptionLabel("Wrapper controls for each [agents.*] entry", self.container)
        self.agentHint.setStyleSheet("color: gray;")
        self.v.addWidget(self.agentHint)

        self.agentRowsHost = QWidget(self.container)
        self.agentRowsLayout = QVBoxLayout(self.agentRowsHost)
        self.agentRowsLayout.setContentsMargins(0, 0, 0, 0)
        self.agentRowsLayout.setSpacing(8)
        self.v.addWidget(self.agentRowsHost)

        self.reload_agents()
        self._refresh_run_status()

    def showEvent(self, event):
        super().showEvent(event)
        self.reload_agents()
        self._refresh_run_status()

    def _config_path(self) -> Path | None:
        p = self.state.agentchattr_root.strip()
        if not p:
            return None
        return Path(p) / "config.toml"

    def _load_agents_from_config(self) -> list[dict[str, str]]:
        cfg = self._config_path()
        if not cfg or not cfg.exists():
            return []
        try:
            doc = load_toml(cfg)
            out: list[dict[str, str]] = []
            for a in list_agent_defs(doc):
                out.append(
                    {
                        "name": a.name,
                        "command": a.command,
                        "label": a.label,
                        "cwd": a.cwd,
                    }
                )
            return out
        except Exception as e:
            self.bus.log(f"[RUN] Failed to load agents from config: {e}")
            return []

    def _clear_agent_rows(self):
        for row in self._agent_rows.values():
            widget = row.get("widget")
            if widget is not None:
                self.agentRowsLayout.removeWidget(widget)
                widget.deleteLater()
        self._agent_rows = {}

    def _rebuild_agent_rows(self):
        self._clear_agent_rows()
        if not self._configured_agents:
            empty = QLabel("No agents configured. Go to Config tab and add at least one agent.", self.agentRowsHost)
            empty.setStyleSheet("color: gray;")
            self.agentRowsLayout.addWidget(empty)
            self._agent_rows["__empty__"] = {"widget": empty}
            return

        for agent in self._configured_agents:
            name = agent["name"]
            command = agent["command"]
            label_text = agent.get("label", "").strip() or name
            if label_text.lower() == name.lower():
                display_text = f"{name} ({command})"
            else:
                display_text = f"{label_text} [{name}] ({command})"

            row_widget = QWidget(self.agentRowsHost)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            label = QLabel(display_text, row_widget)
            label.setMinimumWidth(240)
            status = QLabel("Stopped", row_widget)
            status.setStyleSheet("color: gray;")

            start_btn = QPushButton("Start", row_widget)
            start_btn.clicked.connect(lambda _=False, n=name: self.start_wrapper(n))
            stop_btn = QPushButton("Stop", row_widget)
            stop_btn.clicked.connect(lambda _=False, n=name: self.stop_wrapper(n))

            row_layout.addWidget(label, 1)
            row_layout.addWidget(status)
            row_layout.addWidget(start_btn)
            row_layout.addWidget(stop_btn)

            self.agentRowsLayout.addWidget(row_widget)
            self._agent_rows[name] = {
                "widget": row_widget,
                "status": status,
                "start": start_btn,
                "stop": stop_btn,
            }

    def reload_agents(self):
        self._configured_agents = self._load_agents_from_config()
        self._rebuild_agent_rows()
        self._refresh_run_status()

    def _wrapper_running(self, agent: str) -> bool:
        return len(find_wrapper_pids(agent)) > 0

    def _gather_status(self) -> dict[str, Any]:
        try:
            port = int(self.state.server_port)
        except (ValueError, TypeError):
            port = 8300
        host = self.state.server_host.strip() or "127.0.0.1"

        server_running = self.server.running() or is_port_listening(port, host)
        running_wrappers = get_running_wrapper_agents()
        running_lower = {name.lower() for name in running_wrappers}

        configured = self._load_agents_from_config()
        configured_names = [a["name"] for a in configured]
        configured_lower = {n.lower() for n in configured_names}

        agent_status: dict[str, bool] = {}
        for name in configured_names:
            agent_status[name] = name.lower() in running_lower
        for running_name in sorted(running_wrappers):
            if running_name.lower() not in configured_lower:
                agent_status[running_name] = True

        return {
            "server_running": server_running,
            "server_url": f"{host}:{port}" if server_running else "",
            "wrappers_running": bool(running_wrappers),
            "agent_status": agent_status,
            "configured_agents": configured,
        }

    def _apply_run_status(self, payload: object) -> None:
        self._gathering = False
        if not isinstance(payload, dict):
            return

        configured = payload.get("configured_agents", []) or []
        if isinstance(configured, list):
            desired = [
                {
                    "name": str(a.get("name", "")),
                    "command": str(a.get("command", "")),
                    "label": str(a.get("label", "")),
                    "cwd": str(a.get("cwd", "")),
                }
                for a in configured
                if str(a.get("name", "")).strip()
            ]
            if desired != self._configured_agents:
                self._configured_agents = desired
                self._rebuild_agent_rows()

        server_running = bool(payload.get("server_running", False))
        server_url = str(payload.get("server_url", ""))
        wrappers_running = bool(payload.get("wrappers_running", False))

        agent_status_raw = payload.get("agent_status", {})
        agent_status: dict[str, bool] = {}
        if isinstance(agent_status_raw, dict):
            for k, v in agent_status_raw.items():
                agent_status[str(k)] = bool(v)

        self._last_status = (server_running, server_url, agent_status)

        if server_running:
            self.startServerCard.button.setText("Running")
            self.startServerCard.button.setEnabled(False)
            self.startServerCard.button.setStyleSheet(STYLE_RUNNING)
        else:
            self.startServerCard.button.setText("Start")
            self.startServerCard.button.setEnabled(True)
            self.startServerCard.button.setStyleSheet("")

        self.stopServerCard.button.setEnabled(server_running)
        self.stopServerCard.button.setStyleSheet(STYLE_STOP if server_running else STYLE_STOP_DISABLED)

        self.stopWrappersCard.button.setEnabled(wrappers_running)
        self.stopWrappersCard.button.setStyleSheet(STYLE_STOP if wrappers_running else STYLE_STOP_DISABLED)

        lower_status = {k.lower(): v for k, v in agent_status.items()}
        for name, row in self._agent_rows.items():
            if name == "__empty__":
                continue
            running = lower_status.get(name.lower(), False)
            status_lbl = row["status"]
            start_btn = row["start"]
            stop_btn = row["stop"]

            status_lbl.setText("Running" if running else "Stopped")
            status_lbl.setStyleSheet("color: #2ecc71;" if running else "color: gray;")
            start_btn.setEnabled(not running)
            stop_btn.setEnabled(running)

        self.status_changed.emit()

    def _refresh_run_status(self) -> None:
        if self._gathering:
            return
        self._gathering = True

        def do_gather():
            try:
                data = self._gather_status()
                self._status_ready.emit(data)
            except Exception:
                QTimer.singleShot(0, lambda: setattr(self, "_gathering", False))

        threading.Thread(target=do_gather, daemon=True).start()

    def get_status(self) -> tuple[bool, str, dict[str, bool]]:
        if self._last_status is not None:
            return self._last_status
        try:
            port = int(self.state.server_port)
        except (ValueError, TypeError):
            port = 8300
        host = self.state.server_host.strip() or "127.0.0.1"
        server_running = self.server.running() or is_port_listening(port)
        running = get_running_wrapper_agents()
        status = {name: True for name in running}
        return (server_running, f"{host}:{port}" if server_running else "", status)

    def info(self, ok: bool, title: str, msg: str):
        (InfoBar.success if ok else InfoBar.error)(
            title,
            msg,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2500 if ok else 6500,
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
            self.info(False, "Missing agentchattr venv", "Use Setup -> Create/repair venv first.")
            return

        host = self.state.server_host.strip() or "127.0.0.1"
        port = int(self.state.server_port)
        allow_network = host not in ("127.0.0.1", "localhost", "::1")

        self.bus.log(f"[RUN] Starting server at http://{host}:{port} (allow_network={allow_network})")
        self.info(True, "Starting...", "Spawning server process...")
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
                self.bus.log("[RUN] Server process spawned; waiting for session token...")
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

    def _agent_command(self, agent_name: str) -> str:
        for a in self._configured_agents:
            if a["name"].lower() == agent_name.lower():
                return a["command"]
        return ""

    def _agent_config(self, agent_name: str) -> dict[str, str] | None:
        for a in self._configured_agents:
            if a["name"].lower() == agent_name.lower():
                return a
        return None

    def _agent_workspace(self, root: Path, agent_name: str) -> str:
        cfg = self._agent_config(agent_name) or {}
        cwd = str(cfg.get("cwd", "")).strip()
        if not cwd:
            return ""
        path = Path(cwd)
        if not path.is_absolute():
            path = root / path
        try:
            return str(path.resolve())
        except Exception:
            return str(path)

    def start_wrapper(self, agent_name: str):
        if self._wrapper_running(agent_name):
            self.info(False, "Already running", f"{agent_name} wrapper is already running.")
            return

        root = self.repo_root()
        if not root:
            self.info(False, "Missing agentchattr path", "Set it in Setup.")
            return

        command = self._agent_command(agent_name)
        ws = self._agent_workspace(root, agent_name) or self.state.active_workspace.strip()
        if ws and is_codex_agent(agent_name, command):
            acl = inspect_workspace_acl_for_codex(ws)
            if not acl.ok:
                self.bus.log(f"[RUN] Codex ACL preflight blocked launch: {acl.title} | {acl.detail}")
                self.info(False, "Codex ACL preflight failed", f"{acl.title}: {self._short_msg(acl.detail)}")
                return

        try:
            start_wrapper_console(root, agent_name)
            self.bus.log(f"[RUN] Wrapper launched: {agent_name}")
            self.info(True, "Wrapper launched", agent_name)
            QTimer.singleShot(500, self._refresh_run_status)
            QTimer.singleShot(1500, self._refresh_run_status)
        except Exception as e:
            self.bus.log(f"[ERROR] {e}")
            self.info(False, "Failed", str(e))

    def stop_wrapper(self, agent_name: str):
        def do_stop_one():
            killed = 0
            for pid in find_wrapper_pids(agent_name):
                stop_process_tree(pid)
                killed += 1

            def on_done():
                self.bus.log(f"[RUN] Wrapper stop requested for {agent_name}; killed {killed}")
                self.info(True, "Wrapper stopped", f"{agent_name}: killed {killed} process trees (best effort).")
                self._refresh_run_status()

            QTimer.singleShot(0, on_done)

        threading.Thread(target=do_stop_one, daemon=True).start()

    def _short_msg(self, text: str, max_len: int = 220) -> str:
        t = (text or "").replace("\r", " ").replace("\n", " ").strip()
        if len(t) <= max_len:
            return t
        return t[: max_len - 3] + "..."

    def stop_wrappers(self):
        def do_stop():
            killed = 0
            targets = set(get_running_wrapper_agents())
            targets.update(a["name"] for a in self._configured_agents)
            for agent in targets:
                for pid in find_wrapper_pids(agent):
                    stop_process_tree(pid)
                    killed += 1

            def on_done():
                self.bus.log(f"[RUN] Wrappers stop requested; killed {killed} process trees")
                self.info(True, "Wrappers stopped", f"Killed {killed} process trees (best effort).")
                self._refresh_run_status()

            QTimer.singleShot(0, on_done)

        threading.Thread(target=do_stop, daemon=True).start()
