from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QFileDialog

from qfluentwidgets import (
    ScrollArea, SettingCardGroup, PrimaryPushButton, PushButton,
    InfoBar, InfoBarPosition, FluentIcon as FIF, LineEdit
)
from qfluentwidgets.components.widgets.label import CaptionLabel

from ...core.state import AppState, WorkspaceProfile, save_state
from ...core.workspaces import add_workspace, remove_workspace, set_active_workspace, create_workspace_folder

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

    def refresh(self):
        self.list.clear()
        for ws in self.state.workspaces:
            label = f"{ws.name}  —  {ws.path}"
            if ws.path == self.state.active_workspace:
                label += "   (ACTIVE)"
            it = QListWidgetItem(label)
            it.setData(0, ws.path)
            self.list.addItem(it)
