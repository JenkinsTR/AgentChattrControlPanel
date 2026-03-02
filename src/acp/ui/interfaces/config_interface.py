from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QListWidget,
    QPushButton,
    QComboBox,
    QCheckBox,
    QPlainTextEdit,
)
from tomlkit import document, dumps, parse

from qfluentwidgets import (
    ScrollArea,
    SettingCardGroup,
    PushSettingCard,
    PrimaryPushSettingCard,
    InfoBar,
    InfoBarPosition,
    FluentIcon as FIF,
    LineEdit,
)
from qfluentwidgets.components.widgets.label import CaptionLabel

from ...core.state import AppState, save_state
from ...core.toml_config import (
    AGENT_KNOWN_FIELDS,
    AgentDef,
    apply_workspace_single,
    build_default_config,
    builtin_agent_presets,
    list_agent_defs,
    load_toml,
    remove_agent,
    save_toml,
    set_mcp,
    set_server,
    upsert_agent,
)


class ConfigInterface(ScrollArea):
    def __init__(self, parent, state: AppState):
        super().__init__(parent)
        self.state = state
        self.setObjectName("config")

        self._preset_data: dict[str, dict[str, Any]] = {}

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.setWidgetResizable(True)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(24, 24, 24, 24)
        self.v.setSpacing(18)

        hint = CaptionLabel(
            "Manage server settings and configure any number of agents from config.toml.",
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
            "Apply",
            FIF.SAVE,
            "Apply active workspace to all agents",
            "Writes the active workspace path into each [agents.*].cwd in config.toml.",
            parent=self.container,
        )
        self.applyWSCard.clicked.connect(self.apply_workspace)
        self.group.addSettingCard(self.applyWSCard)

        self.writeDefaultCard = PushSettingCard(
            "Write",
            FIF.DOCUMENT,
            "Write default config.toml",
            "Creates a clean multi-agent config (Codex, Gemini, Claude).",
            parent=self.container,
        )
        self.writeDefaultCard.clicked.connect(self.write_default)
        self.group.addSettingCard(self.writeDefaultCard)

        self.saveServerCard = PushSettingCard(
            "Save",
            FIF.SAVE,
            "Save host/port/MCP ports",
            "Updates [server] + [mcp] sections in config.toml.",
            parent=self.container,
        )
        self.saveServerCard.clicked.connect(self.save_server)
        self.group.addSettingCard(self.saveServerCard)

        self.agentHint = CaptionLabel(
            "Agents editor: add/edit/delete [agents.*] entries and manage reusable presets.",
            self.container,
        )
        self.agentHint.setStyleSheet("color: gray; padding-top: 6px;")
        self.v.addWidget(self.agentHint)

        self.agentPanel = QWidget(self.container)
        self.agentPanelLayout = QVBoxLayout(self.agentPanel)
        self.agentPanelLayout.setContentsMargins(0, 0, 0, 0)
        self.agentPanelLayout.setSpacing(10)
        self.v.addWidget(self.agentPanel)

        presetRow = QHBoxLayout()
        self.presetCombo = QComboBox(self.agentPanel)
        self.presetCombo.setMinimumWidth(260)
        self.applyPresetBtn = QPushButton("Apply preset", self.agentPanel)
        self.applyPresetBtn.clicked.connect(self.apply_selected_preset)
        self.presetNameEdit = LineEdit(self.agentPanel)
        self.presetNameEdit.setPlaceholderText("Custom preset name")
        self.savePresetBtn = QPushButton("Save as preset", self.agentPanel)
        self.savePresetBtn.clicked.connect(self.save_current_as_preset)
        self.deletePresetBtn = QPushButton("Delete preset", self.agentPanel)
        self.deletePresetBtn.clicked.connect(self.delete_selected_preset)

        presetRow.addWidget(self.presetCombo)
        presetRow.addWidget(self.applyPresetBtn)
        presetRow.addWidget(self.presetNameEdit, 1)
        presetRow.addWidget(self.savePresetBtn)
        presetRow.addWidget(self.deletePresetBtn)
        self.agentPanelLayout.addLayout(presetRow)

        body = QHBoxLayout()
        body.setSpacing(12)

        leftPane = QVBoxLayout()
        self.agentList = QListWidget(self.agentPanel)
        self.agentList.currentTextChanged.connect(self._on_agent_selected)
        leftPane.addWidget(self.agentList, 1)

        leftBtns = QHBoxLayout()
        self.newAgentBtn = QPushButton("New", self.agentPanel)
        self.newAgentBtn.clicked.connect(self.new_agent)
        self.reloadAgentsBtn = QPushButton("Reload", self.agentPanel)
        self.reloadAgentsBtn.clicked.connect(self.reload_agents)
        self.deleteAgentBtn = QPushButton("Delete", self.agentPanel)
        self.deleteAgentBtn.clicked.connect(self.delete_agent)
        leftBtns.addWidget(self.newAgentBtn)
        leftBtns.addWidget(self.reloadAgentsBtn)
        leftBtns.addWidget(self.deleteAgentBtn)
        leftPane.addLayout(leftBtns)

        body.addLayout(leftPane, 1)

        rightPane = QVBoxLayout()
        form = QFormLayout()

        self.agentNameEdit = LineEdit(self.agentPanel)
        self.commandEdit = LineEdit(self.agentPanel)
        self.commandEdit.setPlaceholderText("CLI command on PATH (e.g. codex, gemini, claude)")
        self.labelEdit = LineEdit(self.agentPanel)
        self.cwdEdit = LineEdit(self.agentPanel)
        self.cwdEdit.setPlaceholderText("Working directory for this agent")
        self.colorEdit = LineEdit(self.agentPanel)
        self.colorEdit.setPlaceholderText("#RRGGBB")
        self.resumeFlagEdit = LineEdit(self.agentPanel)
        self.resumeFlagEdit.setPlaceholderText("resume flag text, e.g. --resume or exec resume")

        self.writeAccessCheck = QCheckBox("write_access", self.agentPanel)
        self.writeAccessCheck.setChecked(True)

        self.extraArgsEdit = QPlainTextEdit(self.agentPanel)
        self.extraArgsEdit.setPlaceholderText("extra_args: one argument per line")
        self.extraArgsEdit.setFixedHeight(90)

        self.stripEnvEdit = QPlainTextEdit(self.agentPanel)
        self.stripEnvEdit.setPlaceholderText("strip_env: one environment variable per line")
        self.stripEnvEdit.setFixedHeight(70)

        self.additionalOptionsEdit = QPlainTextEdit(self.agentPanel)
        self.additionalOptionsEdit.setPlaceholderText(
            'Additional per-agent TOML options (key/value pairs), e.g.:\nmodel = "gpt-5"\ntimeout = 60'
        )
        self.additionalOptionsEdit.setFixedHeight(110)

        form.addRow("Agent name", self.agentNameEdit)
        form.addRow("Command", self.commandEdit)
        form.addRow("Label", self.labelEdit)
        form.addRow("CWD", self.cwdEdit)
        form.addRow("Color", self.colorEdit)
        form.addRow("Resume flag", self.resumeFlagEdit)
        form.addRow("Write access", self.writeAccessCheck)
        form.addRow("Extra args", self.extraArgsEdit)
        form.addRow("Strip env", self.stripEnvEdit)
        form.addRow("Additional TOML options", self.additionalOptionsEdit)

        rightPane.addLayout(form)

        saveRow = QHBoxLayout()
        saveRow.addStretch(1)
        self.saveAgentBtn = QPushButton("Save agent", self.agentPanel)
        self.saveAgentBtn.clicked.connect(self.save_agent)
        saveRow.addWidget(self.saveAgentBtn)
        rightPane.addLayout(saveRow)

        body.addLayout(rightPane, 2)
        self.agentPanelLayout.addLayout(body)

        self.refresh_presets()
        self.reload_agents()

    def info(self, ok: bool, title: str, msg: str):
        (InfoBar.success if ok else InfoBar.error)(
            title,
            msg,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000 if ok else 6000,
        )

    def _repo_root(self) -> Path | None:
        p = self.state.agentchattr_root.strip()
        return Path(p) if p else None

    def _config_path(self) -> Path | None:
        root = self._repo_root()
        if not root:
            return None
        return root / "config.toml"

    def _parse_int(self, text: str, default: int) -> int:
        try:
            return int(text.strip())
        except Exception:
            return default

    def _split_lines(self, text: str) -> list[str]:
        out: list[str] = []
        for line in text.splitlines():
            token = line.strip()
            if token:
                out.append(token)
        return out

    def _to_plain_value(self, value: Any) -> Any:
        unwrap = getattr(value, "unwrap", None)
        if callable(unwrap):
            try:
                value = unwrap()
            except Exception:
                pass
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                out[str(k)] = self._to_plain_value(v)
            return out
        if isinstance(value, list):
            return [self._to_plain_value(v) for v in value]
        return value

    def _additional_options_to_text(self, additional_options: dict[str, Any]) -> str:
        if not additional_options:
            return ""
        doc = document()
        for key in sorted(additional_options.keys()):
            doc[key] = additional_options[key]
        return dumps(doc).strip()

    def _parse_additional_options(self, text: str) -> dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}
        try:
            doc = parse(raw)
        except Exception as e:
            raise ValueError(f"Invalid additional TOML options: {e}") from e
        out: dict[str, Any] = {}
        for k, v in doc.items():
            key = str(k).strip()
            if not key:
                continue
            if key in AGENT_KNOWN_FIELDS:
                raise ValueError(
                    f"'{key}' is managed by dedicated fields. Remove it from Additional TOML options."
                )
            out[key] = self._to_plain_value(v)
        return out

    def _ensure_doc(self) -> tuple[Path | None, Any | None]:
        cfg = self._config_path()
        if not cfg:
            return None, None
        if not cfg.exists():
            doc = build_default_config(
                host=self.hostEdit.text().strip() or "127.0.0.1",
                port=self._parse_int(self.portEdit.text(), 8300),
                http_port=int(self.state.mcp_http_port),
                sse_port=int(self.state.mcp_sse_port),
            )
            save_toml(cfg, doc)
        return cfg, load_toml(cfg)

    def _selected_agent_name(self) -> str:
        item = self.agentList.currentItem()
        return item.text().strip() if item else ""

    def _set_form_from_agent(self, agent: AgentDef):
        self.agentNameEdit.setText(agent.name)
        self.commandEdit.setText(agent.command)
        self.labelEdit.setText(agent.label)
        self.cwdEdit.setText(agent.cwd)
        self.colorEdit.setText(agent.color)
        self.resumeFlagEdit.setText(agent.resume_flag)
        self.writeAccessCheck.setChecked(bool(agent.write_access))
        self.extraArgsEdit.setPlainText("\n".join(agent.extra_args or []))
        self.stripEnvEdit.setPlainText("\n".join(agent.strip_env or []))
        self.additionalOptionsEdit.setPlainText(self._additional_options_to_text(agent.additional_options))

    def _form_to_agent(self) -> AgentDef:
        name = self.agentNameEdit.text().strip()
        if not name:
            raise ValueError("Agent name is required.")
        command = self.commandEdit.text().strip() or name
        label = self.labelEdit.text().strip() or name
        cwd = self.cwdEdit.text().strip() or "."
        color = self.colorEdit.text().strip() or "#888888"
        resume_flag = self.resumeFlagEdit.text().strip()
        write_access = self.writeAccessCheck.isChecked()
        extra_args = self._split_lines(self.extraArgsEdit.toPlainText())
        strip_env = self._split_lines(self.stripEnvEdit.toPlainText())
        additional_options = self._parse_additional_options(self.additionalOptionsEdit.toPlainText())
        return AgentDef(
            name=name,
            command=command,
            cwd=cwd,
            color=color,
            label=label,
            resume_flag=resume_flag,
            write_access=write_access,
            extra_args=extra_args,
            strip_env=strip_env,
            additional_options=additional_options,
        )

    def refresh_presets(self, select_key: str | None = None):
        self._preset_data = {}
        self.presetCombo.clear()

        for p in builtin_agent_presets():
            key = f"builtin:{p.get('id', p.get('name', ''))}"
            self._preset_data[key] = dict(p)
            self.presetCombo.addItem(str(p.get("name", "Built-in")), key)

        for custom in self.state.agent_presets:
            name = str(custom.get("name", "")).strip()
            if not name:
                continue
            key = f"custom:{name.lower()}"
            preset = {
                "id": key,
                "name": f"{name} (Custom)",
                "command": str(custom.get("command", "")).strip(),
                "label": str(custom.get("label", "")).strip(),
                "color": str(custom.get("color", "")).strip(),
                "resume_flag": str(custom.get("resume_flag", "")).strip(),
                "write_access": bool(custom.get("write_access", True)),
                "extra_args": list(custom.get("extra_args", []) or []),
                "strip_env": list(custom.get("strip_env", []) or []),
                "additional_options": dict(custom.get("additional_options", {}) or {}),
                "custom_name": name,
            }
            self._preset_data[key] = preset
            self.presetCombo.addItem(preset["name"], key)

        if select_key:
            idx = self.presetCombo.findData(select_key)
            if idx >= 0:
                self.presetCombo.setCurrentIndex(idx)

    def _get_selected_preset(self) -> dict[str, Any] | None:
        key = self.presetCombo.currentData()
        if key is None:
            return None
        return self._preset_data.get(str(key))

    def apply_selected_preset(self):
        preset = self._get_selected_preset()
        if not preset:
            self.info(False, "No preset", "Select a preset first.")
            return

        current_name = self.agentNameEdit.text().strip()
        self.commandEdit.setText(str(preset.get("command", "")))
        self.labelEdit.setText(str(preset.get("label", "")))
        self.colorEdit.setText(str(preset.get("color", "")))
        self.resumeFlagEdit.setText(str(preset.get("resume_flag", "")))
        self.writeAccessCheck.setChecked(bool(preset.get("write_access", True)))
        self.extraArgsEdit.setPlainText("\n".join(str(x) for x in preset.get("extra_args", []) or []))
        self.stripEnvEdit.setPlainText("\n".join(str(x) for x in preset.get("strip_env", []) or []))
        self.additionalOptionsEdit.setPlainText(
            self._additional_options_to_text(dict(preset.get("additional_options", {}) or {}))
        )

        if not current_name:
            seed = str(preset.get("command", "agent")).strip() or "agent"
            self.agentNameEdit.setText(seed)
            self.cwdEdit.setText(self.state.active_workspace.strip() or "..")

        self.info(True, "Preset applied", str(preset.get("name", "Preset")))

    def save_current_as_preset(self):
        preset_name = self.presetNameEdit.text().strip()
        if not preset_name:
            self.info(False, "Missing preset name", "Enter a name for the custom preset.")
            return
        try:
            agent = self._form_to_agent()
        except Exception as e:
            self.info(False, "Invalid agent", str(e))
            return

        custom = {
            "name": preset_name,
            "command": agent.command,
            "label": agent.label,
            "color": agent.color,
            "resume_flag": agent.resume_flag,
            "write_access": bool(agent.write_access),
            "extra_args": list(agent.extra_args),
            "strip_env": list(agent.strip_env),
            "additional_options": dict(agent.additional_options),
        }

        updated: list[dict[str, Any]] = []
        replaced = False
        for p in self.state.agent_presets:
            if str(p.get("name", "")).strip().lower() == preset_name.lower():
                updated.append(custom)
                replaced = True
            else:
                updated.append(p)
        if not replaced:
            updated.append(custom)

        self.state.agent_presets = updated
        save_state(self.state)
        select_key = f"custom:{preset_name.lower()}"
        self.refresh_presets(select_key=select_key)
        self.info(True, "Preset saved", preset_name)

    def delete_selected_preset(self):
        preset = self._get_selected_preset()
        if not preset:
            self.info(False, "No preset", "Select a preset first.")
            return
        key = str(self.presetCombo.currentData() or "")
        if not key.startswith("custom:"):
            self.info(False, "Built-in preset", "Built-in presets cannot be deleted.")
            return

        target = str(preset.get("custom_name", "")).strip().lower()
        self.state.agent_presets = [
            p
            for p in self.state.agent_presets
            if str(p.get("name", "")).strip().lower() != target
        ]
        save_state(self.state)
        self.refresh_presets()
        self.info(True, "Preset deleted", preset.get("name", "custom preset"))

    def reload_agents(self, select_name: str | None = None):
        cfg, doc = self._ensure_doc()
        if not cfg or doc is None:
            self.agentList.clear()
            return

        names_before = [self.agentList.item(i).text() for i in range(self.agentList.count())]
        if select_name is None:
            select_name = self._selected_agent_name() or (names_before[0] if names_before else "")

        self.agentList.blockSignals(True)
        self.agentList.clear()
        for a in list_agent_defs(doc):
            self.agentList.addItem(a.name)
        self.agentList.blockSignals(False)

        if self.agentList.count() == 0:
            self.new_agent()
            return

        if select_name:
            matches = self.agentList.findItems(select_name, Qt.MatchFlag.MatchExactly)
            if matches:
                self.agentList.setCurrentItem(matches[0])
                self._on_agent_selected(matches[0].text())
                return

        self.agentList.setCurrentRow(0)
        self._on_agent_selected(self.agentList.currentItem().text())

    def _on_agent_selected(self, name: str):
        cfg, doc = self._ensure_doc()
        if not cfg or doc is None or not name:
            return
        for agent in list_agent_defs(doc):
            if agent.name == name:
                self._set_form_from_agent(agent)
                return

    def new_agent(self):
        ws = self.state.active_workspace.strip() or ".."
        self.agentNameEdit.setText("")
        self.commandEdit.setText("")
        self.labelEdit.setText("")
        self.cwdEdit.setText(ws)
        self.colorEdit.setText("#888888")
        self.resumeFlagEdit.setText("--resume")
        self.writeAccessCheck.setChecked(True)
        self.extraArgsEdit.setPlainText("")
        self.stripEnvEdit.setPlainText("")
        self.additionalOptionsEdit.setPlainText("")

    def save_agent(self):
        cfg, doc = self._ensure_doc()
        if not cfg or doc is None:
            self.info(False, "Missing agentchattr root", "Set it in Setup first.")
            return

        old_name = self._selected_agent_name()
        try:
            agent = self._form_to_agent()
        except Exception as e:
            self.info(False, "Invalid agent", str(e))
            return

        if old_name and old_name != agent.name:
            remove_agent(doc, old_name)
        upsert_agent(doc, agent)
        save_toml(cfg, doc)
        self.reload_agents(select_name=agent.name)
        self.info(True, "Agent saved", agent.name)

    def delete_agent(self):
        cfg, doc = self._ensure_doc()
        if not cfg or doc is None:
            self.info(False, "Missing agentchattr root", "Set it in Setup first.")
            return
        name = self._selected_agent_name()
        if not name:
            self.info(False, "No agent selected", "Select an agent from the list first.")
            return
        remove_agent(doc, name)
        save_toml(cfg, doc)
        self.reload_agents()
        self.info(True, "Agent removed", name)

    def write_default(self):
        cfg = self._config_path()
        if not cfg:
            self.info(False, "Missing agentchattr root", "Set it in Setup first.")
            return
        doc = build_default_config(
            host=self.hostEdit.text().strip() or "127.0.0.1",
            port=self._parse_int(self.portEdit.text(), 8300),
            http_port=int(self.state.mcp_http_port),
            sse_port=int(self.state.mcp_sse_port),
        )
        save_toml(cfg, doc)
        self.reload_agents()
        self.info(True, "Wrote config.toml", str(cfg))

    def save_server(self):
        cfg, doc = self._ensure_doc()
        if not cfg or doc is None:
            self.info(False, "Missing agentchattr root", "Set it in Setup first.")
            return

        host = self.hostEdit.text().strip() or "127.0.0.1"
        port = self._parse_int(self.portEdit.text(), 8300)
        set_server(doc, host, port)
        set_mcp(doc, int(self.state.mcp_http_port), int(self.state.mcp_sse_port))
        save_toml(cfg, doc)

        self.state.server_host = host
        self.state.server_port = port
        save_state(self.state)

        self.info(True, "Saved server settings", f"{host}:{port}")

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_presets()
        self.reload_agents()

    def apply_workspace(self):
        cfg, doc = self._ensure_doc()
        if not cfg or doc is None:
            self.info(False, "Missing config.toml", "Use 'Write default' first.")
            return
        ws = self.state.active_workspace.strip()
        if not ws:
            self.info(False, "No active workspace", "Add/select a workspace first.")
            return
        apply_workspace_single(doc, ws, agents=None)
        save_toml(cfg, doc)
        self.reload_agents(select_name=self._selected_agent_name())
        self.info(True, "Applied workspace", ws)
