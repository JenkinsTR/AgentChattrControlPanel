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
WritableRootStatus = Literal["present", "added", "error"]


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


def _workspace_root_variants(path: str) -> set[str]:
    """Equivalent path variants for writable_roots comparisons."""
    key_fwd = _normalize_path(path)
    key_win = _normalize_path_windows(path) if os.name == "nt" else key_fwd
    variants = {
        key_fwd,
        key_win,
        key_fwd.lower(),
        key_win.lower(),
        key_fwd.rstrip("/"),
        key_win.rstrip("\\"),
        key_fwd.rstrip("/").lower(),
        key_win.rstrip("\\").lower(),
    }
    return {v for v in variants if v}


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    return []


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


def is_workspace_in_writable_roots(workspace_path: str) -> bool:
    """Check if workspace is listed in Codex sandbox_workspace_write.writable_roots."""
    if not workspace_path or not workspace_path.strip():
        return False
    cfg = _codex_config_path()
    if not cfg.exists():
        return False
    try:
        doc = parse(cfg.read_text("utf-8"))
        section = doc.get("sandbox_workspace_write")
        if not section:
            return False
        roots = _string_list(section.get("writable_roots", []))
        if not roots:
            return False
        want = _workspace_root_variants(workspace_path)
        for root in roots:
            if _workspace_root_variants(root) & want:
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


def add_workspace_to_codex_writable_roots(workspace_path: str) -> tuple[WritableRootStatus, str]:
    """
    Ensure workspace is in ~/.codex/config.toml [sandbox_workspace_write].writable_roots.
    Returns (status, message).
    """
    if not workspace_path or not workspace_path.strip():
        return ("error", "No workspace path")
    cfg = _codex_config_path()
    key_fwd = _normalize_path(workspace_path)
    key_win = _normalize_path_windows(workspace_path) if os.name == "nt" else key_fwd
    try:
        if cfg.exists():
            doc = parse(cfg.read_text("utf-8"))
        else:
            doc = document()

        if "sandbox_workspace_write" not in doc:
            doc["sandbox_workspace_write"] = table()
        section = doc["sandbox_workspace_write"]

        roots = _string_list(section.get("writable_roots", []))
        want = _workspace_root_variants(workspace_path)
        if any(_workspace_root_variants(root) & want for root in roots):
            return ("present", "Workspace already in Codex writable_roots")

        if os.name == "nt":
            roots.extend([key_fwd, key_win])
        else:
            roots.append(key_fwd)

        # De-duplicate while preserving order.
        dedup: list[str] = []
        seen: set[str] = set()
        for root in roots:
            if not root:
                continue
            key = root.lower()
            if key in seen:
                continue
            seen.add(key)
            dedup.append(root)

        section["writable_roots"] = dedup
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(dumps(doc), "utf-8")
        return ("added", f"Added {key_fwd} to Codex writable_roots")
    except Exception as e:
        return ("error", str(e))
