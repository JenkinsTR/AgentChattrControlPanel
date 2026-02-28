from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Callable

from PyQt6.QtCore import QObject, pyqtSignal, QThread


@dataclass(frozen=True)
class CmdSpec:
    cmd: Sequence[str]
    cwd: Path | None = None
    env: dict[str, str] | None = None   # environment overrides (merged into os.environ)


def _read_stream_to_lines(stream, on_line: Callable[[str], None]) -> None:
    """Read from stream in chunks, emit complete lines. Handles \\r and \\n from npm progress."""
    buf = ""
    while True:
        chunk = stream.read(256)
        if not chunk:
            break
        buf += chunk
        # Split on any newline variant; keep partial line in buf
        while "\n" in buf or "\r" in buf:
            for sep in ("\r\n", "\n", "\r"):
                idx = buf.find(sep)
                if idx >= 0:
                    line = buf[:idx].strip()
                    buf = buf[idx + len(sep) :]
                    if line:
                        on_line(line)
                    break
            else:
                break
    if buf.strip():
        on_line(buf.strip())


class CommandWorker(QObject):
    line = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, spec: CmdSpec):
        super().__init__()
        self.spec = spec

    def _merged_env(self) -> dict[str, str] | None:
        if self.spec.env is None:
            return None
        env = dict(os.environ)
        env.update(self.spec.env)
        return env

    def _spawn(self, cmd: list[str]) -> subprocess.Popen:
        env = self._merged_env()
        return subprocess.Popen(
            cmd,
            cwd=str(self.spec.cwd) if self.spec.cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def _wrap_cmd_if_needed(self, cmd: list[str]) -> list[str]:
        # If invoking a .cmd/.bat explicitly, run via cmd.exe for consistent behavior.
        exe = cmd[0]
        if exe.lower().endswith((".cmd", ".bat")):
            # /d disables AutoRun, /c runs and exits
            return ["cmd.exe", "/d", "/c"] + cmd
        return cmd

    def run(self):
        try:
            cmd = list(self.spec.cmd)

            # First attempt
            try:
                cmd2 = self._wrap_cmd_if_needed(cmd)
                p = self._spawn(cmd2)
            except FileNotFoundError:
                # Windows gotcha: npm is often npm.cmd. Try resolving via shutil.which and rerun.
                exe = cmd[0]
                resolved = shutil.which(exe)
                if resolved:
                    self.line.emit(f"[ACP] Resolved '{exe}' -> {resolved}")
                    cmd[0] = resolved
                    cmd2 = self._wrap_cmd_if_needed(cmd)
                    p = self._spawn(cmd2)
                else:
                    raise

            # Read stdout in a background thread so we don't block on line iteration.
            # npm uses \r for progress and may not flush newlines until done; chunked read
            # ensures we see output as it arrives.
            reader_done: list[Exception | None] = [None]

            def reader():
                try:
                    _read_stream_to_lines(p.stdout, lambda s: self.line.emit(s))
                except Exception as e:
                    reader_done[0] = e

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            t.join()
            if reader_done[0]:
                raise reader_done[0]
            code = p.wait()
            self.finished.emit(code)

        except FileNotFoundError as e:
            self.line.emit(f"ERROR: {e} (command not found on PATH)")
            self.finished.emit(1)
        except Exception as e:
            self.line.emit(f"ERROR: {e}")
            self.finished.emit(1)


def run_command_in_thread(spec: CmdSpec, on_line: Callable[[str], None], on_done: Callable[[int], None]) -> QThread:
    """Run a command in a QThread and stream output.

    IMPORTANT: We attach the worker to the thread instance to keep a strong reference.
    """
    thread = QThread()
    worker = CommandWorker(spec)
    worker.moveToThread(thread)

    thread._worker = worker  # type: ignore[attr-defined]
    thread._spec = spec      # type: ignore[attr-defined]

    worker.line.connect(on_line)
    worker.finished.connect(on_done)
    thread.started.connect(worker.run)

    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    thread.start()
    return thread
