from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from .toml_config import AGENT_KNOWN_FIELDS

APP_NAME = "AgentChattrControlPanel"


def _to_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


def _to_jsonish(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_to_jsonish(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = _to_jsonish(v)
        return out
    return str(value)


def _sanitize_additional_options(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        key = str(k).strip()
        if not key or key in AGENT_KNOWN_FIELDS:
            continue
        out[key] = _to_jsonish(v)
    return out


def state_path() -> Path:
    base = Path(user_config_dir(APP_NAME))
    base.mkdir(parents=True, exist_ok=True)
    return base / "state.json"

@dataclass
class WorkspaceProfile:
    name: str
    path: str

@dataclass
class AppState:
    agentchattr_root: str = ""
    active_workspace: str = ""
    workspaces: list[WorkspaceProfile] = field(default_factory=list)

    # Server settings
    server_host: str = "127.0.0.1"
    server_port: int = 8300
    mcp_http_port: int = 8200
    mcp_sse_port: int = 8201

    # Mode
    workspace_mode: str = "single"  # "single" or "slots"
    slot_count: int = 2  # slots A/B by default

    # Last known token (parsed from run.py stdout)
    last_session_token: str = ""

    # User-defined agent presets for Config UI
    agent_presets: list[dict[str, Any]] = field(default_factory=list)


def _sanitize_preset(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    if not name:
        return None
    extra = raw.get("extra_args", [])
    if isinstance(extra, str):
        extra_args = [extra] if extra else []
    elif isinstance(extra, list):
        extra_args = [str(x) for x in extra if str(x).strip()]
    else:
        extra_args = []
    strip_env = raw.get("strip_env", [])
    if isinstance(strip_env, str):
        strip_env_vars = [strip_env] if strip_env else []
    elif isinstance(strip_env, list):
        strip_env_vars = [str(x) for x in strip_env if str(x).strip()]
    else:
        strip_env_vars = []
    return {
        "name": name,
        "command": str(raw.get("command", "")).strip(),
        "label": str(raw.get("label", "")).strip(),
        "color": str(raw.get("color", "")).strip(),
        "resume_flag": str(raw.get("resume_flag", "")).strip(),
        "write_access": _to_bool(raw.get("write_access", True)),
        "extra_args": extra_args,
        "strip_env": strip_env_vars,
        "additional_options": _sanitize_additional_options(raw.get("additional_options", {})),
    }

def load_state() -> AppState:
    p = state_path()
    if not p.exists():
        return AppState()
    try:
        raw = json.loads(p.read_text("utf-8"))
        ws = [WorkspaceProfile(**w) for w in raw.get("workspaces", [])]
        presets: list[dict[str, Any]] = []
        for item in raw.get("agent_presets", []):
            clean = _sanitize_preset(item)
            if clean is not None:
                presets.append(clean)
        st = AppState(
            agentchattr_root=raw.get("agentchattr_root", ""),
            active_workspace=raw.get("active_workspace", ""),
            workspaces=ws,
            server_host=raw.get("server_host", "127.0.0.1"),
            server_port=int(raw.get("server_port", 8300)),
            mcp_http_port=int(raw.get("mcp_http_port", 8200)),
            mcp_sse_port=int(raw.get("mcp_sse_port", 8201)),
            workspace_mode=raw.get("workspace_mode", "single"),
            slot_count=int(raw.get("slot_count", 2)),
            last_session_token=raw.get("last_session_token", ""),
            agent_presets=presets,
        )
        return st
    except Exception:
        return AppState()

def save_state(st: AppState) -> None:
    p = state_path()
    data: dict[str, Any] = asdict(st)
    # dataclasses in list already converted by asdict
    p.write_text(json.dumps(data, indent=2), "utf-8")
