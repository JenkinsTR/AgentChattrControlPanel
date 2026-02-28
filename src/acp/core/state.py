from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

APP_NAME = "AgentChattrControlPanel"

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

def load_state() -> AppState:
    p = state_path()
    if not p.exists():
        return AppState()
    try:
        raw = json.loads(p.read_text("utf-8"))
        ws = [WorkspaceProfile(**w) for w in raw.get("workspaces", [])]
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
        )
        return st
    except Exception:
        return AppState()

def save_state(st: AppState) -> None:
    p = state_path()
    data: dict[str, Any] = asdict(st)
    # dataclasses in list already converted by asdict
    p.write_text(json.dumps(data, indent=2), "utf-8")
