from __future__ import annotations

import socket
from pathlib import Path

import psutil

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    ScrollArea, SettingCardGroup, PrimaryPushSettingCard, PushSettingCard,
    InfoBar, InfoBarPosition, FluentIcon as FIF, ComboBox, LineEdit
)
from qfluentwidgets.components.widgets.label import CaptionLabel

from ...core.state import AppState, save_state
from ...core.patching import patch_allowed_origins, unpatch, status as patch_status

class NetworkInterface(ScrollArea):
    def __init__(self, parent, state: AppState):
        super().__init__(parent)
        self.state = state
        self.setObjectName("network")

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.setWidgetResizable(True)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(24, 24, 24, 24)
        self.v.setSpacing(18)

        hint = CaptionLabel(
            "For LAN access: set host to your IP, patch app.py, then restart server with --allow-network.",
            self.container,
        )
        hint.setStyleSheet("color: gray; padding-bottom: 4px;")
        self.v.addWidget(hint)

        self.group = SettingCardGroup("LAN & Security helpers", self.container)
        self.v.addWidget(self.group)

        self.ipCombo = ComboBox(self.container)
        self._populate_ips()
        self.hostEdit = LineEdit(self.container)
        self.hostEdit.setText(state.server_host)
        self.hostEdit.setPlaceholderText("Recommended: set to your LAN IP (e.g. 192.168.0.172), not 0.0.0.0")

        row = QHBoxLayout()
        row.addWidget(self.ipCombo)
        row.addWidget(self.hostEdit)
        self.v.addLayout(row)

        self.applyHostCard = PrimaryPushSettingCard(
            "Apply", FIF.WIFI, "Set server.host to selected IP",
            "Updates ACP state only. Use Config tab to write into agentchattr/config.toml.", parent=self.container
        )
        self.applyHostCard.clicked.connect(self.apply_host)
        self.group.addSettingCard(self.applyHostCard)

        self.patchCard = PrimaryPushSettingCard(
            "Patch", getattr(FIF, "SHIELD", FIF.INFO), "Patch app.py allowed origins",
            "Required for browsing the chat UI from another device via LAN IP.", parent=self.container
        )
        self.patchCard.clicked.connect(self.patch)
        self.group.addSettingCard(self.patchCard)

        self.unpatchCard = PushSettingCard(
            "Unpatch", FIF.RETURN, "Unpatch (restore backup)", "Restores app.py from ACP backup.", parent=self.container
        )
        self.unpatchCard.clicked.connect(self.unpatch)
        self.group.addSettingCard(self.unpatchCard)

        self.refreshCard = PushSettingCard(
            "Refresh", FIF.ROTATE, "Refresh patch status", "Checks whether app.py is patched and backup exists.", parent=self.container
        )
        self.refreshCard.clicked.connect(self.refresh_status)
        self.group.addSettingCard(self.refreshCard)

        self.statusGroup = SettingCardGroup("Patch status", self.container)
        self.v.addWidget(self.statusGroup)
        self.refresh_status()

    def info(self, ok: bool, title: str, msg: str):
        (InfoBar.success if ok else InfoBar.warning)(title, msg, parent=self, position=InfoBarPosition.TOP, duration=3000 if ok else 6000)

    def _repo_root(self) -> Path | None:
        p = self.state.agentchattr_root.strip()
        return Path(p) if p else None

    def _app_py(self) -> Path | None:
        r = self._repo_root()
        return (r / "app.py") if r else None

    def _populate_ips(self):
        ips = []
        for iface, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    ips.append(a.address)
        ips = sorted(set(ips))
        if not ips:
            ips = ["192.168.0.172"]  # placeholder
        self.ipCombo.addItems(ips)

    def apply_host(self):
        ip = self.ipCombo.currentText().strip()
        if ip:
            self.hostEdit.setText(ip)
        host = self.hostEdit.text().strip() or "127.0.0.1"
        self.state.server_host = host
        save_state(self.state)
        self.info(True, "Host saved", host)

    def refresh_status(self):
        while self.statusGroup.layout().count():
            item = self.statusGroup.layout().takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        app_py = self._app_py()
        if not app_py or not app_py.exists():
            from qfluentwidgets import PushSettingCard
            card = PushSettingCard("N/A", FIF.CLOSE, "app.py not found", "Set agentchattr root in Setup.", parent=self.container)
            card.button.setEnabled(False)
            self.statusGroup.addSettingCard(card)
            return
        st = patch_status(app_py)
        from qfluentwidgets import PushSettingCard
        card1 = PushSettingCard("OK" if st.patched else "No", FIF.CHECKBOX if st.patched else FIF.CLOSE, "Patched", str(st.patched), parent=self.container)
        card1.button.setEnabled(False)
        card2 = PushSettingCard("OK" if st.backup_exists else "No", FIF.CHECKBOX if st.backup_exists else FIF.CLOSE, "Backup exists", str(st.backup_path), parent=self.container)
        card2.button.setEnabled(False)
        self.statusGroup.addSettingCard(card1)
        self.statusGroup.addSettingCard(card2)

    def patch(self):
        app_py = self._app_py()
        if not app_py or not app_py.exists():
            self.info(False, "Missing app.py", "Set agentchattr root in Setup.")
            return
        try:
            patch_allowed_origins(app_py)
            self.info(True, "Patched", "app.py updated; you can browse via LAN IP now (after restarting server).")
        except Exception as e:
            self.info(False, "Patch failed", str(e))
        self.refresh_status()

    def unpatch(self):
        app_py = self._app_py()
        if not app_py or not app_py.exists():
            self.info(False, "Missing app.py", "Set agentchattr root in Setup.")
            return
        try:
            unpatch(app_py)
            self.info(True, "Unpatched", "app.py restored from backup.")
        except Exception as e:
            self.info(False, "Unpatch failed", str(e))
        self.refresh_status()
