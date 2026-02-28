from __future__ import annotations

import os
import threading
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QFileDialog

from qfluentwidgets import (
    ScrollArea, SettingCardGroup, PrimaryPushButton, PushButton,
    InfoBar, InfoBarPosition, FluentIcon as FIF, LineEdit,
    PushSettingCard, PrimaryPushSettingCard
)
from qfluentwidgets.components.widgets.label import CaptionLabel

from ...core.state import AppState
from ...core.workspaces import add_workspace, remove_workspace, set_active_workspace, create_workspace_folder
from ...core.codex_config import is_workspace_trusted, add_workspace_to_codex_trusted
from ...core.codex_windows_acl import (
    inspect_workspace_acl_for_codex,
    repair_workspace_acl_for_codex,
    probe_codex_sandbox_write,
)

class WorkspacesInterface(ScrollArea):
    def __init__(self, parent, state: AppState):
        super().__init__(parent)
        self.state = state
        self.setObjectName("workspaces")

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.setWidgetResizable(True)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(24, 24, 24, 24)
        self.v.setSpacing(18)

        hint = CaptionLabel(
            "Workspaces are folders where Codex/Gemini run. Set active → Config → Apply.",
            self.container,
        )
        hint.setStyleSheet("color: gray; padding-bottom: 4px;")
        self.v.addWidget(hint)

        self.group = SettingCardGroup("Workspace profiles", self.container)
        self.v.addWidget(self.group)

        self.list = QListWidget(self.container)
        self.list.setMinimumHeight(120)
        self.v.addWidget(self.list)

        # Add workspace row
        addRow = QHBoxLayout()
        self.nameEdit = LineEdit(self.container)
        self.nameEdit.setPlaceholderText("Name (e.g. MyNewTool)")
        self.pathEdit = LineEdit(self.container)
        self.pathEdit.setPlaceholderText("Folder path")
        self.pathEdit.setMinimumWidth(180)
        browse = PushButton("Browse", self.container)
        browse.clicked.connect(self.on_browse)
        mkBtn = PushButton("Create folder", self.container)
        mkBtn.clicked.connect(self.on_create_folder)
        addBtn = PrimaryPushButton("Add", self.container)
        addBtn.clicked.connect(self.on_add)
        addRow.addWidget(self.nameEdit)
        addRow.addWidget(self.pathEdit, 1)
        addRow.addWidget(browse)
        addRow.addWidget(mkBtn)
        addRow.addWidget(addBtn)
        self.v.addLayout(addRow)

        # List actions row
        listRow = QHBoxLayout()
        setBtn = PrimaryPushButton("Set active", self.container)
        setBtn.clicked.connect(self.on_set_active)
        delBtn = PushButton("Remove", self.container)
        delBtn.clicked.connect(self.on_remove)
        listRow.addWidget(setBtn)
        listRow.addWidget(delBtn)
        listRow.addStretch()
        self.v.addLayout(listRow)

        # Codex trusted section
        self.codexGroup = SettingCardGroup("Codex trusted", self.container)
        self.v.addWidget(self.codexGroup)
        self.codexStatusCard = PushSettingCard(
            "—",
            FIF.CHECKBOX,
            "Active workspace in Codex trusted projects",
            "Set an active workspace to see status.",
            parent=self.container,
        )
        self.codexStatusCard.button.setEnabled(False)
        self.codexGroup.addSettingCard(self.codexStatusCard)
        self.codexAddCard = PrimaryPushSettingCard(
            "Add to Codex trusted",
            getattr(FIF, "ADD", FIF.ADD_TO),
            "Add active workspace to ~/.codex/config.toml",
            "Required for Codex to load project .codex/config.toml (agentchattr MCP). Restart Codex after adding.",
            parent=self.container,
        )
        self.codexAddCard.clicked.connect(self.on_add_codex_trusted)
        self.codexGroup.addSettingCard(self.codexAddCard)

        # Codex Windows ACL section (Windows enforces ACLs; DENY entries block writes even with workspace-write)
        self.codexAclGroup = SettingCardGroup("Codex Windows sandbox ACL", self.container)
        self.v.addWidget(self.codexAclGroup)
        self.codexAclStatusCard = PushSettingCard(
            "—",
            getattr(FIF, "SHIELD", FIF.INFO),
            "Workspace ACL preflight",
            "Windows enforces ACLs on the folder; DENY entries block writes even when Codex has workspace-write. Repair removes those so Codex can write.",
            parent=self.container,
        )
        self.codexAclStatusCard.button.setEnabled(False)
        self.codexAclGroup.addSettingCard(self.codexAclStatusCard)

        self.codexAclRepairCard = PrimaryPushSettingCard(
            "Repair ACL (Admin)",
            getattr(FIF, "REPAIR", FIF.SYNC),
            "Repair workspace ACL for Codex sandbox",
            "Runs elevated icacls (uses UNC path if workspace is on a mapped drive so repair actually runs on the right folder).",
            parent=self.container,
        )
        self.codexAclRepairCard.clicked.connect(self.on_repair_codex_acl)
        self.codexAclGroup.addSettingCard(self.codexAclRepairCard)

        self.codexAclProbeCard = PushSettingCard(
            "Run probe",
            getattr(FIF, "PLAY", FIF.SYNC),
            "Verify write via Codex sandbox",
            "Runs a local write probe using 'codex sandbox windows --full-auto' in the active workspace.",
            parent=self.container,
        )
        self.codexAclProbeCard.clicked.connect(self.on_probe_codex_acl)
        self.codexAclGroup.addSettingCard(self.codexAclProbeCard)

        self.refresh()

    def info(self, ok: bool, title: str, msg: str):
        (InfoBar.success if ok else InfoBar.error)(title, msg, parent=self, position=InfoBarPosition.TOP, duration=3000 if ok else 6000)

    def on_browse(self):
        p = QFileDialog.getExistingDirectory(self, "Select workspace folder")
        if p:
            self.pathEdit.setText(p)

    def on_add(self):
        name = self.nameEdit.text().strip() or Path(self.pathEdit.text().strip() or "Workspace").name
        path = self.pathEdit.text().strip()
        if not path:
            self.info(False, "Missing path", "Pick a folder.")
            return
        add_workspace(self.state, name, path)
        self.info(True, "Added", f"{name} → {path}")
        self.refresh()

    def on_create_folder(self):
        path = self.pathEdit.text().strip()
        if not path:
            self.info(False, "Missing path", "Pick a folder path first.")
            return
        try:
            create_workspace_folder(path)
            self.info(True, "Created", path)
        except Exception as e:
            self.info(False, "Failed", str(e))

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_codex_trusted_on_show()

    def _ensure_codex_trusted_on_show(self):
        """On tab show: if active workspace exists and is not trusted, add it."""
        ws = self.state.active_workspace.strip()
        if not ws:
            self._refresh_codex_status()
            self._refresh_codex_acl_status()
            return
        if not is_workspace_trusted(ws):
            status, msg = add_workspace_to_codex_trusted(ws)
            if status == "added":
                self.info(True, "Codex trusted", msg)
        self._refresh_codex_status()
        self._refresh_codex_acl_status()

    def on_set_active(self):
        item = self.list.currentItem()
        if not item:
            self.info(False, "Select a workspace", "Choose a workspace from the list.")
            return
        path = item.data(0)
        set_active_workspace(self.state, path)
        self.info(True, "Active workspace", path)
        self.refresh()

    def on_remove(self):
        item = self.list.currentItem()
        if not item:
            self.info(False, "Select a workspace", "Choose a workspace from the list.")
            return
        path = item.data(0)
        remove_workspace(self.state, path)
        self.info(True, "Removed", path)
        self.refresh()

    def on_add_codex_trusted(self):
        ws = self.state.active_workspace.strip()
        if not ws:
            self.info(False, "No active workspace", "Set an active workspace first.")
            return
        status, msg = add_workspace_to_codex_trusted(ws)
        if status == "trusted":
            self.info(True, "Already trusted", msg)
        elif status == "added":
            self.info(True, "Added to Codex trusted", msg)
        else:
            self.info(False, "Failed", msg)
        self._refresh_codex_status()
        self._refresh_codex_acl_status()

    def _refresh_codex_status(self):
        ws = self.state.active_workspace.strip()
        if not ws:
            self.codexStatusCard.setTitle("Active workspace in Codex trusted projects")
            self.codexStatusCard.setContent("No active workspace — set one above to see status.")
            self.codexStatusCard.button.setText("—")
            self.codexStatusCard.button.setStyleSheet("")
            self.codexAddCard.setEnabled(False)
            return
        trusted = is_workspace_trusted(ws)
        if trusted:
            self.codexStatusCard.setTitle("Trusted")
            self.codexStatusCard.setContent(ws)
            self.codexStatusCard.button.setText("✓")
            self.codexStatusCard.button.setStyleSheet("background-color: #2ecc71; color: white;")
            self.codexAddCard.setEnabled(False)
        else:
            self.codexStatusCard.setTitle("Not trusted")
            self.codexStatusCard.setContent(ws)
            self.codexStatusCard.button.setText("!")
            self.codexStatusCard.button.setStyleSheet("background-color: #e67e22; color: white;")
            self.codexAddCard.setEnabled(True)

    def _short_result(self, text: str, max_len: int = 260) -> str:
        t = (text or "").strip().replace("\r", " ").replace("\n", " ")
        if len(t) <= max_len:
            return t
        return t[: max_len - 3] + "..."

    def _refresh_codex_acl_status(self):
        ws = self.state.active_workspace.strip()
        if not ws:
            self.codexAclStatusCard.setTitle("Workspace ACL preflight")
            self.codexAclStatusCard.setContent("No active workspace — set one above to run ACL checks.")
            self.codexAclStatusCard.button.setText("—")
            self.codexAclStatusCard.button.setStyleSheet("")
            self.codexAclRepairCard.setEnabled(False)
            self.codexAclProbeCard.setEnabled(False)
            return

        if os.name != "nt":
            self.codexAclStatusCard.setTitle("Not needed on this OS")
            self.codexAclStatusCard.setContent("Codex ACL repair/probe is only required on Windows.")
            self.codexAclStatusCard.button.setText("N/A")
            self.codexAclStatusCard.button.setStyleSheet("")
            self.codexAclRepairCard.setEnabled(False)
            self.codexAclProbeCard.setEnabled(False)
            return

        status = inspect_workspace_acl_for_codex(ws)
        if status.ok:
            self.codexAclStatusCard.setTitle("ACL looks compatible")
            self.codexAclStatusCard.setContent(status.detail)
            self.codexAclStatusCard.button.setText("✓")
            self.codexAclStatusCard.button.setStyleSheet("background-color: #2ecc71; color: white;")
            self.codexAclRepairCard.setEnabled(True)
            self.codexAclProbeCard.setEnabled(True)
        else:
            self.codexAclStatusCard.setTitle(status.title)
            self.codexAclStatusCard.setContent(status.detail)
            if status.risky_everyone_write:
                self.codexAclStatusCard.button.setText("!")
                self.codexAclStatusCard.button.setStyleSheet("background-color: #e67e22; color: white;")
            else:
                self.codexAclStatusCard.button.setText("✕")
                self.codexAclStatusCard.button.setStyleSheet("background-color: #e74c3c; color: white;")
            self.codexAclRepairCard.setEnabled(True)
            self.codexAclProbeCard.setEnabled(True)

    def on_repair_codex_acl(self):
        ws = self.state.active_workspace.strip()
        if not ws:
            self.info(False, "No active workspace", "Set an active workspace first.")
            return
        self.info(True, "Repair started", "If prompted, approve the UAC dialog to repair ACLs.")

        def worker():
            result = repair_workspace_acl_for_codex(ws)

            def on_main():
                ok = result.code == 0
                detail = self._short_result(result.err or result.out or "")
                if ok:
                    self.info(True, "ACL repaired", "Workspace ACL repair completed.")
                else:
                    self.info(False, "ACL repair failed", detail or "Repair failed or was cancelled.")
                self._refresh_codex_acl_status()

            QTimer.singleShot(0, on_main)

        threading.Thread(target=worker, daemon=True).start()

    def on_probe_codex_acl(self):
        ws = self.state.active_workspace.strip()
        if not ws:
            self.info(False, "No active workspace", "Set an active workspace first.")
            return
        self.info(True, "Running probe", "Testing Codex Windows sandbox write in active workspace...")

        def worker():
            result = probe_codex_sandbox_write(ws)

            def on_main():
                ok = result.code == 0
                detail = self._short_result(result.err or result.out or "")
                if ok:
                    self.info(True, "Probe passed", "Codex sandbox write probe succeeded.")
                else:
                    self.info(False, "Probe failed", detail or "Codex sandbox write probe failed.")
                self._refresh_codex_acl_status()

            QTimer.singleShot(0, on_main)

        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        self.list.clear()
        for ws in self.state.workspaces:
            label = f"{ws.name}  —  {ws.path}"
            if ws.path == self.state.active_workspace:
                label += "   (ACTIVE)"
            it = QListWidgetItem(label)
            it.setData(0, ws.path)
            self.list.addItem(it)
        self._refresh_codex_status()
        self._refresh_codex_acl_status()
