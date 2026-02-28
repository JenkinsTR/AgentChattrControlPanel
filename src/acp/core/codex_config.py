"""Codex CLI trusted project configuration.

Codex loads project .codex/config.toml only when the project is trusted.
Add workspaces to ~/.codex/config.toml [projects."path"] trust_level = "trusted"
so agentchattr's MCP injection works.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from tomlkit import document, dumps, parse, table

TrustStatus = Literal["trusted", "missing", "added", "error"]


def _codex_config_path() -> Path:
    """Path to Codex user config.toml (CODEX_HOME or ~/.codex)."""
    base = os.environ.get("CODEX_HOME")
    if base:
        return Path(base).expanduser() / "config.toml"
    return Path.home() / ".codex" / "config.toml"


def _normalize_path(path: str) -> str:
    """Canonical absolute path for TOML key (forward slashes for cross-platform)."""
    p = Path(path).resolve()
    return str(p).replace("\\", "/")


def _normalize_path_windows(path: str) -> str:
    """Windows native path (backslashes). Codex may compare using this on Windows."""
    p = Path(path).resolve()
    return str(p)


def _trust_key_variants(path: str) -> list[str]:
    """Generate robust project key variants for Codex trust lookups on Windows."""
    key_fwd = _normalize_path(path)
    key_win = _normalize_path_windows(path) if os.name == "nt" else key_fwd
    variants = {key_fwd, key_win}
    # Some runtimes compare paths case-sensitively even on Windows; include lowercase forms.
    variants.add(key_fwd.lower())
    variants.add(key_win.lower())
    # Include trailing-slash forward form to match alternate normalizers.
    variants.add(key_fwd.rstrip("/") + "/")
    return [v for v in variants if v]


def is_workspace_trusted(workspace_path: str) -> bool:
    """Check if workspace is in Codex trusted projects."""
    if not workspace_path or not workspace_path.strip():
        return False
    cfg = _codex_config_path()
    if not cfg.exists():
        return False
    try:
        doc = parse(cfg.read_text("utf-8"))
        projects = doc.get("projects")
        if not projects:
            return False
        for key in _trust_key_variants(workspace_path):
            if key in projects and str(projects[key].get("trust_level", "")).lower() == "trusted":
                return True
        return False
    except Exception:
        return False


def add_workspace_to_codex_trusted(workspace_path: str) -> tuple[TrustStatus, str]:
    """
    Add workspace to Codex trusted projects. Creates config if missing.
    On Windows, adds both forward-slash and backslash forms so Codex finds it.
    Returns (status, message).
    """
    if not workspace_path or not workspace_path.strip():
        return ("error", "No workspace path")
    cfg = _codex_config_path()
    key_fwd = _normalize_path(workspace_path)
    try:
        if cfg.exists():
            doc = parse(cfg.read_text("utf-8"))
        else:
            doc = document()
        if "projects" not in doc:
            doc["projects"] = table()
        projects = doc["projects"]
        # Check if already trusted (either format)
        for key in _trust_key_variants(workspace_path):
            if key in projects and str(projects[key].get("trust_level", "")).lower() == "trusted":
                return ("trusted", "Already trusted")
        # Add multiple formats on Windows (Codex may compare using either path/casing style)
        for key in _trust_key_variants(workspace_path):
            projects[key] = table()
            projects[key]["trust_level"] = "trusted"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(dumps(doc), "utf-8")
        return ("added", f"Added {key_fwd} to Codex trusted projects")
    except Exception as e:
        return ("error", str(e))
