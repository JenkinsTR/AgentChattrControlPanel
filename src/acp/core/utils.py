from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

def is_windows() -> bool:
    return os.name == "nt"

def quote_cmd(cmd: Iterable[str]) -> str:
    # For display only
    return " ".join(shlex.quote(c) for c in cmd)

@dataclass(frozen=True)
class CmdResult:
    code: int
    out: str
    err: str

def run_cmd(
    cmd: list[str],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int | None = None,
) -> CmdResult:
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return CmdResult(p.returncode, p.stdout, p.stderr)

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def readable_bool(v: bool) -> str:
    return "Yes" if v else "No"
