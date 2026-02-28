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
    allow_network: bool,
) -> subprocess.Popen:
    py = repo_paths(root).venv_python
    if not py.exists():
        raise FileNotFoundError("agentchattr venv python not found, run Setup first")
    cmd = [str(py), str(root / "run.py")]
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

def is_port_listening(port: int) -> bool:
    for c in psutil.net_connections(kind="tcp"):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
            return True
    return False

def stop_process_tree(pid: int) -> None:
    try:
        p = psutil.Process(pid)
    except Exception:
        return
    children = p.children(recursive=True)
    for ch in children:
        try:
            ch.kill()
        except Exception:
            pass
    try:
        p.kill()
    except Exception:
        pass

def start_wrapper_console(root: Path, agent_name: str) -> None:
    # Open in new cmd window so console injection works reliably
    py = repo_paths(root).venv_python
    if not py.exists():
        raise FileNotFoundError("agentchattr venv python not found")
    if os.name != "nt":
        raise RuntimeError("Console wrapper launcher is implemented for Windows only in this ACP scaffold")

    title = f"agentchattr {agent_name}"
    # cmd /c start "title" cmd /k "cd /d <root> && <python> wrapper.py <agent>"
    launch = f'cd /d "{root}" && "{py}" "{root / "wrapper.py"}" {agent_name}'
    subprocess.Popen(["cmd", "/c", "start", title, "cmd", "/k", launch], cwd=str(root))

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
