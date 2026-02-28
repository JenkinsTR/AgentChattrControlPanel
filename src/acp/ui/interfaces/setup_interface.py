from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog

from qfluentwidgets import (
    ScrollArea, SettingCardGroup, PushSettingCard, PrimaryPushSettingCard,
    InfoBar, InfoBarPosition, FluentIcon as FIF, LineEdit, PushButton
)
from qfluentwidgets.components.widgets.label import CaptionLabel

from ...core.state import AppState, save_state
from ...core.checks import (
    check_python_311, check_exe, check_agentchattr_repo, check_agentchattr_venv,
    check_codex_cli, check_gemini_cli
)
from ...core.agentchattr import ensure_venv
from ..async_worker import CmdSpec, run_command_in_thread
from ..log_bus import LogBus


class SetupInterface(ScrollArea):
    """Installer + diagnostics UI.

    NPM note:
      npm can be quiet when output is piped. npm writes debug logs under a `_logs` directory
      inside the npm cache directory. (Docs: `npm config get cache`)
      ACP tails that log folder (best effort) while npm commands run to provide progress visibility.
    """

    def __init__(self, parent, state: AppState, bus: LogBus):
        super().__init__(parent)
        self.state = state
        self.bus = bus
        self.setObjectName("setup")

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.setWidgetResizable(True)

        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(24, 24, 24, 24)
        self.v.setSpacing(18)

        # Workflow hint
        self.workflowHint = CaptionLabel(
            "Workflow: Setup → Workspaces → Config → (optional) LAN → Run",
            self.container,
        )
        self.workflowHint.setStyleSheet("color: gray; padding-bottom: 4px;")
        self.v.addWidget(self.workflowHint)

        self._threads: list = []
        self._busy = False

        # Watchdog heartbeat
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(2000)
        self._watchdog.timeout.connect(self._on_watchdog_tick)
        self._cmd_label = ""
        self._cmd_start_ts = 0.0
        self._last_output_ts = 0.0

        # npm log tailing (best-effort)
        self._npm_tail_timer = QTimer(self)
        self._npm_tail_timer.setInterval(500)
        self._npm_tail_timer.timeout.connect(self._on_npm_tail_tick)
        self._npm_logs_dir: Path | None = None
        self._npm_log_file: Path | None = None
        self._npm_log_offset: int = 0

        # Root picker
        self.rootEdit = LineEdit(self.container)
        self.rootEdit.setPlaceholderText("Path to agentchattr repo (existing folder or empty folder to clone into)")
        self.rootEdit.setText(state.agentchattr_root)

        self.browseBtn = PushButton("Browse…", self.container)
        self.browseBtn.clicked.connect(self.on_browse_root)

        row = QHBoxLayout()
        row.addWidget(self.rootEdit, 1)
        row.addWidget(self.browseBtn, 0)
        self.v.addLayout(row)

        self.cards = SettingCardGroup("Setup checks & actions", self.container)
        self.v.addWidget(self.cards)

        self.cloneCard = PrimaryPushSettingCard(
            "Clone", FIF.DOWNLOAD, "Clone agentchattr",
            "Clones bcurts/agentchattr into the selected folder (must be empty).",
            parent=self.container,
        )
        self.cloneCard.clicked.connect(self.on_clone)
        self.cards.addSettingCard(self.cloneCard)

        self.updateCard = PushSettingCard(
            "Pull", getattr(FIF, "SYNC", FIF.ROTATE), "Update agentchattr",
            "Runs git pull --ff-only in agentchattr folder.",
            parent=self.container,
        )
        self.updateCard.clicked.connect(self.on_pull)
        self.cards.addSettingCard(self.updateCard)

        self.venvCard = PrimaryPushSettingCard(
            "Create/Repair", getattr(FIF, "DEVELOPER_TOOLS", FIF.SETTING),
            "Create/repair agentchattr venv + install deps",
            "Creates agentchattr/.venv and installs requirements.txt.",
            parent=self.container,
        )
        self.venvCard.clicked.connect(self.on_venv)
        self.cards.addSettingCard(self.venvCard)

        self.codexCard = PushSettingCard(
            "npm -g", getattr(FIF, "COMMAND_PROMPT", FIF.CODE),
            "Install Codex CLI (optional)",
            "Runs: npm install -g @openai/codex",
            parent=self.container,
        )
        self.codexCard.clicked.connect(self.on_install_codex)
        self.cards.addSettingCard(self.codexCard)

        self.geminiCard = PushSettingCard(
            "npm -g", getattr(FIF, "COMMAND_PROMPT", FIF.CODE),
            "Install Gemini CLI (optional)",
            "Runs: npm install -g @google/gemini-cli",
            parent=self.container,
        )
        self.geminiCard.clicked.connect(self.on_install_gemini)
        self.cards.addSettingCard(self.geminiCard)

        self.refreshCard = PushSettingCard(
            "Refresh", getattr(FIF, "ROTATE", FIF.SYNC), "Re-run checks",
            "Updates status indicators.",
            parent=self.container,
        )
        self.refreshCard.clicked.connect(self.refresh_checks)
        self.cards.addSettingCard(self.refreshCard)

        self.statusGroup = SettingCardGroup("Current status", self.container)
        self.v.addWidget(self.statusGroup)

        self.refresh_checks()

    # ---- Watchdog ----

    def _on_watchdog_tick(self):
        if not self._busy:
            return
        now = time.monotonic()
        if self._last_output_ts and (now - self._last_output_ts) >= 6.0:
            elapsed = (now - self._cmd_start_ts) if self._cmd_start_ts else 0.0
            self.bus.log(f"[SETUP] … still running: {self._cmd_label} ({elapsed:.0f}s elapsed)")
            self._last_output_ts = now

    # ---- npm log tailing ----

    def _compute_npm_logs_dir(self) -> Path | None:
        """Resolve npm _logs dir via 'npm config get cache' or fallback to common paths."""
        try:
            r = subprocess.run(
                ["npm", "config", "get", "cache"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            if r.returncode == 0 and r.stdout.strip():
                cache = Path(r.stdout.strip().strip('"').strip("'"))
                logs_dir = cache / "_logs"
                if logs_dir.exists():
                    return logs_dir
        except Exception:
            pass
        for base in [
            os.environ.get("LOCALAPPDATA"),
            os.environ.get("APPDATA"),
        ]:
            if base:
                p = Path(base) / "npm-cache" / "_logs"
                if p.exists():
                    return p
        return None

    def _start_npm_tail(self):
        self._npm_logs_dir = self._compute_npm_logs_dir()
        self._npm_log_file = None
        self._npm_log_offset = 0
        if self._npm_logs_dir:
            self.bus.log(f"[SETUP] Watching npm logs in: {self._npm_logs_dir}")
            self._npm_tail_timer.start()
            self._on_npm_tail_tick()  # immediate first read
        else:
            self.bus.log("[SETUP] (npm logs) Could not locate npm _logs folder; will rely on stdout only.")

    def _stop_npm_tail(self):
        self._npm_tail_timer.stop()
        self._npm_logs_dir = None
        self._npm_log_file = None
        self._npm_log_offset = 0

    def _on_npm_tail_tick(self):
        if not self._busy or not self._npm_logs_dir:
            return
        try:
            logs = sorted(self._npm_logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not logs:
                return
            newest = logs[0]
            # Switch to newest log if npm created a new one (e.g. at install start)
            if self._npm_log_file is None or (
                newest != self._npm_log_file and newest.stat().st_mtime > self._cmd_start_ts - 2
            ):
                self._npm_log_file = newest
                self._npm_log_offset = 0
                self.bus.log(f"[SETUP] Tailing npm log: {self._npm_log_file.name}")

            if self._npm_log_file and self._npm_log_file.exists():
                with self._npm_log_file.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._npm_log_offset)
                    chunk = f.read()
                    self._npm_log_offset = f.tell()
                if chunk:
                    self._last_output_ts = time.monotonic()
                    for line in chunk.splitlines():
                        if line.strip():
                            self.bus.log(f"[npm] {line}")
        except Exception:
            return

    # ---- Helpers ----

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._busy = busy
        self._cmd_label = label or self._cmd_label
        for w in (self.cloneCard, self.updateCard, self.venvCard, self.codexCard, self.geminiCard, self.refreshCard, self.browseBtn, self.rootEdit):
            try:
                w.setEnabled(not busy)
            except Exception:
                pass

        if busy:
            self.bus.log(f"[SETUP] Busy: {label}")
        else:
            self.bus.log("[SETUP] Ready")

    def _update_action_card(self, card, done: bool, action_label: str, action_icon):
        """Update action card button to show ✓ Done when already installed."""
        card.button.setText("✓ Done" if done else action_label)
        card.iconLabel.setIcon(getattr(FIF, "ACCEPT", FIF.CHECKBOX) if done else action_icon)

    def _infobar(self, ok: bool, title: str, content: str):
        # Truncate long content (e.g. full pip output) to avoid huge notifications
        max_len = 200
        if len(content) > max_len:
            content = content[: max_len - 20].rstrip() + "\n… (see Logs tab)"
        (InfoBar.success if ok else InfoBar.error)(
            title, content, parent=self, position=InfoBarPosition.TOP, duration=3000 if ok else 7000
        )

    def agentchattr_root(self) -> Path | None:
        p = self.rootEdit.text().strip()
        return Path(p) if p else None

    def is_setup_complete(self) -> bool:
        root = self.agentchattr_root()
        if not root:
            return False
        repo_ok = check_agentchattr_repo(root).ok
        venv_ok = check_agentchattr_venv(root).ok
        codex_ok = check_codex_cli().ok
        gemini_ok = check_gemini_cli().ok
        return repo_ok and venv_ok and (codex_ok or gemini_ok)

    def _cleanup_threads(self):
        alive = []
        for t in self._threads:
            try:
                if t.isRunning():
                    alive.append(t)
            except Exception:
                pass
        self._threads = alive

    def _start_cmd(self, spec: CmdSpec, label: str, on_done, tail_npm_logs: bool = False):
        self._set_busy(True, label)
        self._cmd_start_ts = time.monotonic()
        self._last_output_ts = self._cmd_start_ts
        self._watchdog.start()

        self.bus.log(f"[SETUP] CMD: {' '.join(map(str, spec.cmd))}")
        if spec.cwd:
            self.bus.log(f"[SETUP] CWD: {spec.cwd}")

        if tail_npm_logs:
            self._start_npm_tail()

        def _on_line(line: str):
            self._last_output_ts = time.monotonic()
            self.bus.log(line)

        def _on_done(code: int):
            try:
                self.bus.log(f"[SETUP] Done: {label} (exit={code})")
                on_done(code)
            finally:
                self._cleanup_threads()
                self._watchdog.stop()
                self._stop_npm_tail()
                self._set_busy(False)

        t = run_command_in_thread(spec, _on_line, _on_done)
        self._threads.append(t)

    # ---- UI Actions ----

    def on_browse_root(self):
        p = QFileDialog.getExistingDirectory(self, "Select agentchattr folder (existing or empty)")
        if p:
            self.rootEdit.setText(p)
            self.refresh_checks()

    def refresh_checks(self):
        root = self.agentchattr_root()
        if root:
            self.state.agentchattr_root = str(root)
            save_state(self.state)

        layout = self.statusGroup.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        py = check_python_311()
        git = check_exe("git")
        node = check_exe("node")
        npm = check_exe("npm")

        if root:
            repo = check_agentchattr_repo(root)
            venv = check_agentchattr_venv(root)
        else:
            repo = type(py)(False, "agentchattr repo present", "Not set")
            venv = type(py)(False, "agentchattr .venv present", "Not set")

        codex = check_codex_cli()
        gemini = check_gemini_cli()

        results = [py, git, node, npm, repo, venv, codex, gemini]
        for r in results:
            card = PushSettingCard(
                "✓" if r.ok else "Fix",
                getattr(FIF, "ACCEPT", FIF.CHECKBOX) if r.ok else FIF.CLOSE,
                r.label,
                r.detail,
                parent=self.container,
            )
            card.button.setEnabled(False)
            self.statusGroup.addSettingCard(card)

        # Update action cards with green ticks when already done
        self._update_action_card(self.cloneCard, repo.ok if root else False, "Clone", FIF.DOWNLOAD)
        self._update_action_card(self.updateCard, repo.ok if root else False, "Pull", getattr(FIF, "SYNC", FIF.ROTATE))
        self._update_action_card(self.venvCard, venv.ok if root else False, "Create/Repair", getattr(FIF, "DEVELOPER_TOOLS", FIF.SETTING))
        self._update_action_card(self.codexCard, codex.ok, "npm -g", getattr(FIF, "COMMAND_PROMPT", FIF.CODE))
        self._update_action_card(self.geminiCard, gemini.ok, "npm -g", getattr(FIF, "COMMAND_PROMPT", FIF.CODE))

    def on_clone(self):
        root = self.agentchattr_root()
        if not root:
            self._infobar(False, "Missing path", "Pick a folder path for agentchattr first.")
            return
        if root.exists() and any(root.iterdir()):
            self._infobar(False, "Folder not empty", "Choose an empty folder for cloning (or use Update).")
            return

        root.parent.mkdir(parents=True, exist_ok=True)
        spec = CmdSpec(cmd=["git", "clone", "https://github.com/bcurts/agentchattr", str(root)], cwd=root.parent)

        def done(code: int):
            ok = (code == 0)
            self._infobar(ok, "Clone complete" if ok else "Clone failed", f"Exit code: {code}")
            self.refresh_checks()

        self._start_cmd(spec, "Cloning agentchattr", done)

    def on_pull(self):
        root = self.agentchattr_root()
        if not root:
            self._infobar(False, "Missing path", "Set agentchattr root first.")
            return

        spec = CmdSpec(cmd=["git", "pull", "--ff-only"], cwd=root)

        def done(code: int):
            ok = (code == 0)
            self._infobar(ok, "Update complete" if ok else "Update failed", f"Exit code: {code}")
            self.refresh_checks()

        self._start_cmd(spec, "Updating agentchattr", done)

    def on_venv(self):
        root = self.agentchattr_root()
        if not root:
            self._infobar(False, "Missing path", "Set agentchattr root first.")
            return

        self._set_busy(True, "Creating/repairing venv")
        self.bus.log("[SETUP] Creating/repairing venv and installing deps…")

        class EnsureVenvWorker(QObject):
            result = pyqtSignal(object)  # CmdResult | Exception

            def run(self):
                try:
                    r = ensure_venv(root)
                    self.result.emit(r)
                except Exception as e:
                    self.result.emit(e)

        thread = QThread()
        worker = EnsureVenvWorker()
        worker.moveToThread(thread)

        def on_result(r):
            try:
                thread.quit()
                self._cleanup_threads()
                self._watchdog.stop()
                self._set_busy(False)
                if isinstance(r, Exception):
                    self.bus.log(f"[ERROR] {r}")
                    self._infobar(False, "Venv/deps failed", str(r))
                else:
                    if r.out.strip():
                        for line in r.out.strip().splitlines():
                            self.bus.log(line)
                    if r.err.strip():
                        for line in r.err.strip().splitlines():
                            self.bus.log(line)
                    ok = r.code == 0
                    summary = r.out.strip() or r.err.strip() or f"Exit code {r.code}"
                    self._infobar(ok, "Venv ready" if ok else "Venv/deps failed", summary)
                self.refresh_checks()
            finally:
                worker.deleteLater()
                thread.deleteLater()

        worker.result.connect(on_result)
        thread.started.connect(worker.run)
        self._threads.append(thread)
        self._watchdog.start()
        thread.start()

    def on_install_codex(self):
        # --no-progress: line-based output instead of \r progress bar (works when piped)
        # --color=always: ANSI colors; logs UI renders them via ansi_to_html
        # --loglevel=verbose: npm writes to _logs; tail shows it; stdout gets summary
        env = {"NPM_CONFIG_COLOR": "always"}
        spec = CmdSpec(
            cmd=["npm", "install", "-g", "@openai/codex", "--no-progress", "--color=always", "--loglevel=verbose"],
            cwd=None,
            env=env,
        )

        def done(code: int):
            ok = (code == 0)
            self._infobar(ok, "Codex installed" if ok else "Codex install failed", f"Exit code: {code}")
            self.refresh_checks()

        self._start_cmd(spec, "Installing Codex CLI", done, tail_npm_logs=True)

    def on_install_gemini(self):
        env = {"NPM_CONFIG_COLOR": "always"}
        spec = CmdSpec(
            cmd=["npm", "install", "-g", "@google/gemini-cli", "--no-progress", "--color=always", "--loglevel=verbose"],
            cwd=None,
            env=env,
        )

        def done(code: int):
            ok = (code == 0)
            self._infobar(ok, "Gemini installed" if ok else "Gemini install failed", f"Exit code: {code}")
            self.refresh_checks()

        self._start_cmd(spec, "Installing Gemini CLI", done, tail_npm_logs=True)
