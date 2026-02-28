from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    ScrollArea, SettingCardGroup, PushSettingCard, PrimaryPushSettingCard,
    InfoBar, InfoBarPosition, FluentIcon as FIF, LineEdit
)
from qfluentwidgets.components.widgets.label import CaptionLabel

from ...core.state import AppState, save_state
from ...core.toml_config import load_toml, save_toml, build_default_config, set_server, set_mcp, set_routing, set_images, apply_workspace_single

class ConfigInterface(ScrollArea):
    def __init__(self, parent, state: AppState):
        super().__init__(parent)
        self.state = state
        self.setObjectName("config")

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.setWidgetResizable(True)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(24, 24, 24, 24)
        self.v.setSpacing(18)

        hint = CaptionLabel(
            "Apply workspace so Codex/Gemini run in the right folder. Save host/port for server.",
            self.container,
        )
        hint.setStyleSheet("color: gray; padding-bottom: 4px;")
        self.v.addWidget(hint)

        self.group = SettingCardGroup("agentchattr config.toml", self.container)
        self.v.addWidget(self.group)

        self.hostEdit = LineEdit(self.container)
        self.hostEdit.setText(state.server_host)
        self.hostEdit.setPlaceholderText("server.host (127.0.0.1 or LAN IP)")

        self.portEdit = LineEdit(self.container)
        self.portEdit.setText(str(state.server_port))
        self.portEdit.setPlaceholderText("server.port (web UI)")

        row1 = QHBoxLayout()
        row1.addWidget(self.hostEdit)
        row1.addWidget(self.portEdit)
        self.v.addLayout(row1)

        self.applyWSCard = PrimaryPushSettingCard(
            "Apply", FIF.SAVE, "Apply active workspace to Codex/Gemini cwd", 
            "Writes config.toml so both agents run in the active workspace folder.", parent=self.container
        )
        self.applyWSCard.clicked.connect(self.apply_workspace)
        self.group.addSettingCard(self.applyWSCard)

        self.writeDefaultCard = PushSettingCard(
            "Write", FIF.DOCUMENT, "Write a clean default config.toml",
            "Overwrites config.toml with a readable multi-line version (keeps only codex+gemini by default).",
            parent=self.container
        )
        self.writeDefaultCard.clicked.connect(self.write_default)
        self.group.addSettingCard(self.writeDefaultCard)

        self.saveServerCard = PushSettingCard(
            "Save", FIF.SAVE, "Save host/port/MCP ports to config.toml",
            "Updates [server] + [mcp] sections in config.toml.",
            parent=self.container
        )
        self.saveServerCard.clicked.connect(self.save_server)
        self.group.addSettingCard(self.saveServerCard)

    def info(self, ok: bool, title: str, msg: str):
        (InfoBar.success if ok else InfoBar.error)(title, msg, parent=self, position=InfoBarPosition.TOP, duration=3000 if ok else 6000)

    def _repo_root(self) -> Path | None:
        p = self.state.agentchattr_root.strip()
        return Path(p) if p else None

    def _config_path(self) -> Path | None:
        root = self._repo_root()
        if not root:
            return None
        return root / "config.toml"

    def write_default(self):
        cfg = self._config_path()
        if not cfg:
            self.info(False, "Missing agentchattr root", "Set it in Setup first.")
            return
        doc = build_default_config(
            host=self.hostEdit.text().strip() or "127.0.0.1",
            port=int(self.portEdit.text().strip() or "8300"),
            http_port=int(self.state.mcp_http_port),
            sse_port=int(self.state.mcp_sse_port),
        )
        save_toml(cfg, doc)
        self.info(True, "Wrote config.toml", str(cfg))

    def save_server(self):
        cfg = self._config_path()
        if not cfg:
            self.info(False, "Missing agentchattr root", "Set it in Setup first.")
            return
        if not cfg.exists():
            self.write_default()
            return
        doc = load_toml(cfg)
        host = self.hostEdit.text().strip() or "127.0.0.1"
        port = int(self.portEdit.text().strip() or "8300")
        set_server(doc, host, port)
        set_mcp(doc, self.state.mcp_http_port, self.state.mcp_sse_port)
        save_toml(cfg, doc)

        # Persist to ACP state
        self.state.server_host = host
        self.state.server_port = port
        save_state(self.state)

        self.info(True, "Saved server settings", f"{host}:{port}")

    def apply_workspace(self):
        cfg = self._config_path()
        if not cfg or not cfg.exists():
            self.info(False, "Missing config.toml", "Use 'Write default' first.")
            return
        ws = self.state.active_workspace.strip()
        if not ws:
            self.info(False, "No active workspace", "Add/select a workspace first.")
            return
        doc = load_toml(cfg)
        apply_workspace_single(doc, ws, agents=None)
        save_toml(cfg, doc)
        self.info(True, "Applied workspace", ws)
