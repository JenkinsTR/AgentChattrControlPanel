from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from .utils import CmdResult, run_cmd, ensure_dir

AGENTCHATTR_REPO = "https://github.com/bcurts/agentchattr"

@dataclass(frozen=True)
class RepoPaths:
    root: Path
    config_toml: Path
    run_py: Path
    app_py: Path
    wrapper_py: Path
    requirements_txt: Path
    venv_python: Path

def repo_paths(root: Path) -> RepoPaths:
    return RepoPaths(
        root=root,
        config_toml=root / "config.toml",
        run_py=root / "run.py",
        app_py=root / "app.py",
        wrapper_py=root / "wrapper.py",
        requirements_txt=root / "requirements.txt",
        venv_python=root / ".venv" / "Scripts" / "python.exe",
    )

def clone_repo(dst: Path) -> CmdResult:
    ensure_dir(dst.parent)
    return run_cmd(["git", "clone", AGENTCHATTR_REPO, str(dst)], cwd=dst.parent)

def pull_repo(root: Path) -> CmdResult:
    return run_cmd(["git", "pull", "--ff-only"], cwd=root)

def ensure_venv(root: Path) -> CmdResult:
    # Create .venv if missing
    venv_dir = root / ".venv"
    if not venv_dir.exists():
        r = run_cmd([sys.executable, "-m", "venv", str(venv_dir)], cwd=root)
        if r.code != 0:
            return r
    py = root / ".venv" / "Scripts" / "python.exe"
    pip = root / ".venv" / "Scripts" / "pip.exe"
    if not py.exists() or not pip.exists():
        return CmdResult(1, "", f"venv python/pip missing in {venv_dir}")
    # Install requirements
    req = root / "requirements.txt"
    if not req.exists():
        return CmdResult(1, "", "requirements.txt missing in agentchattr repo")
    r = run_cmd([str(pip), "install", "-r", str(req)], cwd=root)
    return r

def npm_install_global(pkg: str) -> CmdResult:
    # requires npm on PATH
    return run_cmd(["npm", "install", "-g", pkg], cwd=None)

def npm_install_global_gemini() -> CmdResult:
    return npm_install_global("@google/gemini-cli")

def npm_install_global_codex() -> CmdResult:
    return npm_install_global("@openai/codex")

def start_server(
    root: Path,
    host: str,
    port: int,
    allow_network: bool,
) -> subprocess.Popen:
    py = repo_paths(root).venv_python
    if not py.exists():
        raise FileNotFoundError("agentchattr venv python not found, run Setup first")
    cmd = [str(py), str(root / "run.py"), "--host", host, "--port", str(port)]
    if allow_network:
        cmd.append("--allow-network")
    # Keep pipes so ACP can parse token and show logs
    return subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    """Check if port is open. Uses socket (no admin needed); falls back to psutil."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((host, port)) == 0:
                return True
    except Exception:
        pass
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
                return True
    except Exception:
        pass
    return False

def stop_process_tree(pid: int) -> None:
    """Kill process and its children. Ignores NoSuchProcess/AccessDenied (process may already be gone)."""
    try:
        p = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return
    try:
        children = p.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []
    for ch in children:
        try:
            ch.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        p.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

def start_wrapper_console(root: Path, agent_name: str) -> None:
    # Open in new cmd window so console injection works reliably.
    # Use a batch file to avoid cmd.exe nested-quote parsing issues.
    py = repo_paths(root).venv_python
    if not py.exists():
        raise FileNotFoundError("agentchattr venv python not found")
    if os.name != "nt":
        raise RuntimeError("Console wrapper launcher is implemented for Windows only in this ACP scaffold")

    root = Path(root).resolve()
    bat = root / "_acp_wrapper_launch.bat"
    bat.write_text(
        f'@echo off\ncd /d "{root}"\n"{py}" "{root / "wrapper.py"}" {agent_name}\n',
        encoding="utf-8",
    )
    # Use empty title "" so start correctly treats the bat path as the command.
    # A title with spaces (e.g. "agentchattr codex") can cause start to misparse.
    # Pass path without manual quotes; subprocess handles it correctly.
    subprocess.Popen(["cmd", "/c", "start", "", str(bat)], cwd=str(root))

def find_wrapper_pids(agent_name: str) -> list[int]:
    pids = []
    needle1 = "wrapper.py"
    needle2 = f" {agent_name}"
    for p in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(p.info.get("cmdline") or [])
            if needle1 in cmdline and needle2 in cmdline:
                pids.append(p.info["pid"])
        except Exception:
            continue
    return pids


def get_running_wrapper_agents() -> set[str]:
    """Single pass over processes; returns set of agent names with running wrappers."""
    result: set[str] = set()
    agents = ("codex", "gemini", "claude", "codex_A", "gemini_A", "codex_B", "gemini_B")
    try:
        for p in psutil.process_iter(attrs=["pid", "cmdline"]):
            try:
                cmdline_list = p.info.get("cmdline") or []
                cmdline = " ".join(str(x) for x in cmdline_list).lower()
                if "wrapper.py" not in cmdline:
                    continue
                for a in agents:
                    a_lower = a.lower()
                    if f" {a_lower}" in cmdline or cmdline.endswith(a_lower) or f" {a_lower} " in cmdline:
                        result.add(a)
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return result
