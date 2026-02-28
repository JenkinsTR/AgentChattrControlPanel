from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .utils import run_cmd

@dataclass(frozen=True)
class CheckResult:
    ok: bool
    label: str
    detail: str = ""

def check_python_311() -> CheckResult:
    ok = sys.version_info >= (3, 11)
    return CheckResult(ok, "Python 3.11+", f"Detected: {sys.version.split()[0]}")

def check_exe(name: str) -> CheckResult:
    p = shutil.which(name)
    return CheckResult(bool(p), f"{name} on PATH", p or "Not found")

def check_node_npm() -> list[CheckResult]:
    out = []
    out.append(check_exe("node"))
    out.append(check_exe("npm"))
    return out

def check_agentchattr_repo(root: Path) -> CheckResult:
    ok = (root / "run.py").exists() and (root / "config.toml").exists()
    return CheckResult(ok, "agentchattr repo present", str(root) if ok else "Not set or missing run.py/config.toml")

def check_agentchattr_venv(root: Path) -> CheckResult:
    py = root / ".venv" / "Scripts" / "python.exe"
    ok = py.exists()
    return CheckResult(ok, "agentchattr .venv present", str(py) if ok else "Missing .venv (use Setup actions)")

def check_codex_cli() -> CheckResult:
    # Codex CLI command is "codex"
    return check_exe("codex")

def check_gemini_cli() -> CheckResult:
    return check_exe("gemini")

def check_git_clean(root: Path) -> CheckResult:
    if not (root / ".git").exists():
        return CheckResult(False, "git repo", "Not a git checkout")
    r = run_cmd(["git", "status", "--porcelain"], cwd=root)
    ok = (r.code == 0 and r.out.strip() == "")
    detail = "Clean" if ok else (r.out.strip() or r.err.strip() or "Dirty or unknown")
    return CheckResult(ok, "agentchattr working tree clean", detail)
