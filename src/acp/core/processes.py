from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .agentchattr import start_server, stop_process_tree, is_port_listening

TOKEN_RE = re.compile(r"Session token:\s*([0-9a-fA-F]{64})")

@dataclass
class ServerHandle:
    pid: int
    host: str
    port: int

class ServerRunner:
    def __init__(self):
        self._proc = None
        self._thread = None
        self._spawn_thread = None
        self._stop = threading.Event()

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(
        self,
        root: Path,
        host: str,
        port: int,
        allow_network: bool,
        on_line: Callable[[str], None],
        on_token: Callable[[str], None],
        on_exit: Callable[[int], None],
        on_spawned: Callable[[], None] | None = None,
    ) -> None:
        if self.running():
            return
        self._stop.clear()

        def do_spawn():
            try:
                proc = start_server(root=root, host=host, port=port, allow_network=allow_network)
                if self._stop.is_set():
                    try:
                        stop_process_tree(proc.pid)
                    except Exception:
                        pass
                    return
                self._proc = proc

                if on_spawned:
                    on_spawned()

                def pump():
                    try:
                        for line in self._proc.stdout:
                            if self._stop.is_set():
                                break
                            on_line(line.rstrip("\n"))
                            m = TOKEN_RE.search(line)
                            if m:
                                on_token(m.group(1))
                        code = self._proc.wait()
                        on_exit(code)
                    except Exception:
                        try:
                            code = self._proc.poll() or 1
                        except Exception:
                            code = 1
                        on_exit(code)

                self._thread = threading.Thread(target=pump, daemon=True)
                self._thread.start()
            except Exception:
                on_exit(1)

        self._spawn_thread = threading.Thread(target=do_spawn, daemon=True)
        self._spawn_thread.start()

    def stop(self) -> None:
        if not self._proc:
            return
        self._stop.set()
        try:
            stop_process_tree(self._proc.pid)
        finally:
            self._proc = None
            self._thread = None
