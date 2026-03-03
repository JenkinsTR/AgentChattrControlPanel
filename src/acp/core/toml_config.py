from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tomlkit import document, dumps, parse, table


def _to_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


def _to_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    return []


def _to_plain_value(value: Any) -> Any:
    unwrap = getattr(value, "unwrap", None)
    if callable(unwrap):
        try:
            value = unwrap()
        except Exception:
            pass
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = _to_plain_value(v)
        return out
    if isinstance(value, list):
        return [_to_plain_value(v) for v in value]
    return value


AGENT_KNOWN_FIELDS: set[str] = {
    "command",
    "cwd",
    "color",
    "label",
    "resume_flag",
    "write_access",
    "extra_args",
    "strip_env",
}


def _sanitize_additional_options(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in value.items():
        key = str(k).strip()
        if not key or key in AGENT_KNOWN_FIELDS:
            continue
        out[key] = _to_plain_value(v)
    return out


@dataclass
class AgentDef:
    name: str
    command: str
    cwd: str
    color: str
    label: str
    resume_flag: str
    write_access: bool = True
    extra_args: list[str] = field(default_factory=list)
    strip_env: list[str] = field(default_factory=list)
    additional_options: dict[str, Any] = field(default_factory=dict)


CODEX_RUNTIME_EXTRA_ARGS = ["--sandbox", "workspace-write", "-a", "never", "-c", "windows.sandbox=unelevated"]


def is_codex_agent(name: str, command: str | None = None) -> bool:
    n = (name or "").strip().lower()
    c = (command or "").strip().lower()
    return n.startswith("codex") or c == "codex"


BUILTIN_AGENT_PRESETS: list[dict[str, Any]] = [
    {
        "id": "generic",
        "name": "Generic Agent (Built-in)",
        "command": "agent",
        "label": "Agent",
        "color": "#888888",
        "resume_flag": "--resume",
        "write_access": True,
        "extra_args": [],
        "strip_env": [],
        "additional_options": {},
    },
    {
        "id": "codex",
        "name": "Codex (Built-in)",
        "command": "codex",
        "label": "Codex",
        "color": "#10a37f",
        "resume_flag": "exec resume",
        "write_access": True,
        "extra_args": CODEX_RUNTIME_EXTRA_ARGS,
        "strip_env": [],
        "additional_options": {},
    },
    {
        "id": "gemini",
        "name": "Gemini (Built-in)",
        "command": "gemini",
        "label": "Gemini",
        "color": "#4285f4",
        "resume_flag": "--resume",
        "write_access": True,
        "extra_args": [],
        "strip_env": [],
        "additional_options": {},
    },
    {
        "id": "claude",
        "name": "Claude (Built-in)",
        "command": "claude",
        "label": "Claude",
        "color": "#a78bfa",
        "resume_flag": "--resume",
        "write_access": True,
        "extra_args": [],
        "strip_env": [],
        "additional_options": {},
    },
]


DEFAULT_AGENTS = [
    AgentDef(
        "codex",
        "codex",
        "..",
        "#10a37f",
        "Codex",
        "exec resume",
        write_access=True,
        extra_args=CODEX_RUNTIME_EXTRA_ARGS,
    ),
    AgentDef("gemini", "gemini", "..", "#4285f4", "Gemini", "--resume", write_access=True),
    AgentDef("claude", "claude", "..", "#a78bfa", "Claude", "--resume", write_access=True),
]


def load_toml(p: Path) -> Any:
    return parse(p.read_text("utf-8"))


def save_toml(p: Path, doc: Any) -> None:
    p.write_text(dumps(doc), "utf-8")


def ensure_config_structure(doc: Any) -> Any:
    if "server" not in doc:
        doc["server"] = table()
    if "agents" not in doc:
        doc["agents"] = table()
    if "routing" not in doc:
        doc["routing"] = table()
    if "mcp" not in doc:
        doc["mcp"] = table()
    if "images" not in doc:
        doc["images"] = table()
    return doc


def set_server(doc: Any, host: str, port: int, data_dir: str = "./data") -> None:
    doc = ensure_config_structure(doc)
    doc["server"]["host"] = host
    doc["server"]["port"] = int(port)
    doc["server"]["data_dir"] = data_dir


def set_mcp(doc: Any, http_port: int, sse_port: int) -> None:
    doc = ensure_config_structure(doc)
    doc["mcp"]["http_port"] = int(http_port)
    doc["mcp"]["sse_port"] = int(sse_port)


def set_routing(doc: Any, default: str = "none", max_agent_hops: int = 4) -> None:
    doc = ensure_config_structure(doc)
    doc["routing"]["default"] = default
    doc["routing"]["max_agent_hops"] = int(max_agent_hops)


def set_images(doc: Any, upload_dir: str = "./uploads", max_size_mb: int = 10) -> None:
    doc = ensure_config_structure(doc)
    doc["images"]["upload_dir"] = upload_dir
    doc["images"]["max_size_mb"] = int(max_size_mb)


def builtin_agent_presets() -> list[dict[str, Any]]:
    # Return detached copies so callers can mutate safely.
    return [
        {
            "id": str(p.get("id", "")),
            "name": str(p.get("name", "")),
            "command": str(p.get("command", "")),
            "label": str(p.get("label", "")),
            "color": str(p.get("color", "")),
            "resume_flag": str(p.get("resume_flag", "")),
            "write_access": _to_bool(p.get("write_access", True)),
            "extra_args": list(p.get("extra_args", []) or []),
            "strip_env": list(p.get("strip_env", []) or []),
            "additional_options": _sanitize_additional_options(p.get("additional_options", {})),
        }
        for p in BUILTIN_AGENT_PRESETS
    ]


def list_agent_names(doc: Any) -> list[str]:
    agents = doc.get("agents", {})
    if not isinstance(agents, dict):
        return []
    return [str(k) for k in agents.keys()]


def get_agent_def(doc: Any, name: str) -> AgentDef | None:
    agents = doc.get("agents", {})
    if name not in agents:
        return None
    cfg = agents[name]
    additional_options = _sanitize_additional_options(
        {str(k): v for k, v in cfg.items() if str(k) not in AGENT_KNOWN_FIELDS}
    )
    return AgentDef(
        name=name,
        command=str(cfg.get("command", name)),
        cwd=str(cfg.get("cwd", ".")),
        color=str(cfg.get("color", "#888")),
        label=str(cfg.get("label", name)),
        resume_flag=str(cfg.get("resume_flag", "--resume")),
        write_access=_to_bool(cfg.get("write_access", True)),
        extra_args=_to_str_list(cfg.get("extra_args", [])),
        strip_env=_to_str_list(cfg.get("strip_env", [])),
        additional_options=additional_options,
    )


def list_agent_defs(doc: Any) -> list[AgentDef]:
    out: list[AgentDef] = []
    for name in list_agent_names(doc):
        a = get_agent_def(doc, name)
        if a is not None:
            out.append(a)
    return out


def _workspace_arg_variants(path: str) -> list[str]:
    raw = (path or "").strip()
    if not raw:
        return []

    p = Path(raw)
    vals: list[str] = [raw]
    try:
        resolved = str(p.resolve())
    except Exception:
        resolved = str(p)

    vals.append(resolved)
    vals.append(resolved.replace("\\", "/"))
    if os.name == "nt":
        vals.append(resolved.lower())
        vals.append(resolved.replace("\\", "/").lower())

    out: list[str] = []
    seen: set[str] = set()
    for v in vals:
        s = str(v).strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _sync_codex_add_dir(extra: list[str], workspace_path: str, old_workspace_path: str | None = None) -> list[str]:
    """Ensure Codex has --add-dir entries for the active workspace path variants."""
    old_variants = {v.lower() if os.name == "nt" else v for v in _workspace_arg_variants(old_workspace_path or "")}

    kept: list[str] = []
    i = 0
    while i < len(extra):
        tok = extra[i]
        if tok == "--add-dir" and i + 1 < len(extra):
            val = str(extra[i + 1]).strip()
            if val:
                key = val.lower() if os.name == "nt" else val
                if key in old_variants:
                    i += 2
                    continue
            kept.extend([tok, extra[i + 1]])
            i += 2
            continue
        kept.append(tok)
        i += 1

    existing: set[str] = set()
    i = 0
    while i < len(kept):
        if kept[i] == "--add-dir" and i + 1 < len(kept):
            val = str(kept[i + 1]).strip()
            if val:
                existing.add(val)
            i += 2
        else:
            i += 1

    for variant in _workspace_arg_variants(workspace_path):
        if variant in existing:
            continue
        kept.extend(["--add-dir", variant])
        existing.add(variant)

    return kept


def set_agent(doc: Any, a: AgentDef) -> None:
    doc = ensure_config_structure(doc)
    if a.name not in doc["agents"]:
        doc["agents"][a.name] = table()
    agent_cfg = doc["agents"][a.name]

    additional_options = _sanitize_additional_options(a.additional_options)
    for key in list(agent_cfg.keys()):
        skey = str(key)
        if skey not in AGENT_KNOWN_FIELDS and skey not in additional_options:
            del agent_cfg[skey]

    agent_cfg["command"] = a.command
    agent_cfg["cwd"] = a.cwd
    agent_cfg["color"] = a.color
    agent_cfg["label"] = a.label
    agent_cfg["resume_flag"] = a.resume_flag
    agent_cfg["write_access"] = a.write_access
    extra_args = list(a.extra_args or [])
    if not extra_args and is_codex_agent(a.name, a.command) and a.write_access:
        # Keep flags explicit to avoid --full-auto reintroducing on-request prompts.
        extra_args = CODEX_RUNTIME_EXTRA_ARGS.copy()
    if is_codex_agent(a.name, a.command) and a.write_access and a.cwd:
        extra_args = _sync_codex_add_dir(extra_args, a.cwd)
    if extra_args:
        agent_cfg["extra_args"] = extra_args
    elif "extra_args" in agent_cfg:
        del agent_cfg["extra_args"]
    if a.strip_env:
        agent_cfg["strip_env"] = list(a.strip_env)
    elif "strip_env" in agent_cfg:
        del agent_cfg["strip_env"]

    for key, value in additional_options.items():
        agent_cfg[key] = value


def upsert_agent(doc: Any, a: AgentDef) -> None:
    set_agent(doc, a)

def remove_agent(doc: Any, name: str) -> None:
    if "agents" in doc and name in doc["agents"]:
        del doc["agents"][name]


def build_default_config(host: str, port: int, http_port: int, sse_port: int) -> Any:
    doc = document()
    set_server(doc, host, port)
    set_routing(doc, "none", 4)
    set_mcp(doc, http_port, sse_port)
    set_images(doc)
    for a in DEFAULT_AGENTS:
        set_agent(doc, a)
    return doc


def apply_workspace_single(doc: Any, workspace_path: str, agents: list[str] | None = None) -> None:
    if agents is None:
        agents = [k for k in list_agent_names(doc)]
    for name in agents:
        if "agents" in doc and name in doc["agents"]:
            cfg = doc["agents"][name]
            old_cwd = str(cfg.get("cwd", "")).strip()
            cfg["cwd"] = workspace_path
            command = str(cfg.get("command", ""))
            write_access = _to_bool(cfg.get("write_access", True), True)
            if is_codex_agent(name, command) and write_access:
                extra = _to_str_list(cfg.get("extra_args", []))
                cfg["extra_args"] = _sync_codex_add_dir(extra, workspace_path, old_workspace_path=old_cwd)


def get_agent_write_access(doc: Any, name: str) -> bool:
    """Get write_access for an agent. Default True if not set. For Codex, infers from extra_args."""
    agents = doc.get("agents", {})
    if name not in agents:
        return True
    cfg = agents[name]
    if "write_access" in cfg:
        return _to_bool(cfg["write_access"], True)
    # Infer from extra_args for Codex (--full-auto, -a never, or --sandbox workspace-write)
    command = str(cfg.get("command", ""))
    if is_codex_agent(name, command):
        extra = cfg.get("extra_args", [])
        extra = _to_str_list(extra)
        if "--full-auto" in extra:
            return True
        for i in range(len(extra) - 1):
            if extra[i] == "--sandbox" and extra[i + 1] == "workspace-write":
                return True
            if extra[i] in ("-a", "--ask-for-approval") and extra[i + 1] == "never":
                return True
        return False
    return True


def _strip_codex_runtime_args(extra: list[str]) -> list[str]:
    # Remove --sandbox workspace-write, --full-auto, -a never, and -c windows.sandbox=...
    new_extra = []
    i = 0
    while i < len(extra):
        if extra[i] == "--full-auto":
            i += 1
            continue
        if extra[i] == "--sandbox" and i + 1 < len(extra) and extra[i + 1] == "workspace-write":
            i += 2
            continue
        if extra[i] == "-a" and i + 1 < len(extra) and extra[i + 1] == "never":
            i += 2
            continue
        if extra[i] == "--ask-for-approval" and i + 1 < len(extra) and extra[i + 1] == "never":
            i += 2
            continue
        if extra[i] == "-c" and i + 1 < len(extra) and str(extra[i + 1]).startswith("windows.sandbox="):
            i += 2
            continue
        new_extra.append(extra[i])
        i += 1
    return new_extra


def _resolve_agent_write_targets(doc: Any, name: str) -> list[str]:
    agents = [str(n) for n in doc.get("agents", {}).keys()]
    if name in agents:
        return [name]
    base = name.lower().rstrip("_")
    matches = [n for n in agents if n.lower() == base or n.lower().startswith(base + "_")]
    return matches if matches else [name]


def set_agent_write_access(doc: Any, name: str, value: bool) -> None:
    """Set write_access for an agent. Updates extra_args for Codex, write_access for all.
    When name is 'codex' or 'gemini', also updates codex_A/B and gemini_A/B if present."""
    doc = ensure_config_structure(doc)
    to_update = _resolve_agent_write_targets(doc, name)
    for agent_name in to_update:
        if agent_name not in doc["agents"]:
            doc["agents"][agent_name] = table()
        cfg = doc["agents"][agent_name]
        cfg["write_access"] = value

    # For Codex: sync extra_args so wrapper gets deterministic sandbox + approval behavior.
    for agent_name in to_update:
        cfg = doc["agents"][agent_name]
        command = str(cfg.get("command", ""))
        if not is_codex_agent(agent_name, command):
            continue
        extra = _to_str_list(cfg.get("extra_args", []))
        new_extra = _strip_codex_runtime_args(extra)
        if value:
            new_extra = CODEX_RUNTIME_EXTRA_ARGS.copy() + new_extra
            cwd = str(cfg.get("cwd", "")).strip()
            if cwd:
                new_extra = _sync_codex_add_dir(new_extra, cwd)
        cfg["extra_args"] = new_extra


def ensure_slot_agents(doc: Any, workspace_a: str, workspace_b: str) -> None:
    # Create codex_A/gemini_A + codex_B/gemini_B
    def mk(name, cmd, cwd, color, label, resume):
        set_agent(doc, AgentDef(name, cmd, cwd, color, label, resume))
    mk("codex_A", "codex", workspace_a, "#10a37f", "Codex (A)", "exec resume")
    mk("gemini_A", "gemini", workspace_a, "#4285f4", "Gemini (A)", "--resume")
    mk("codex_B", "codex", workspace_b, "#10a37f", "Codex (B)", "exec resume")
    mk("gemini_B", "gemini", workspace_b, "#4285f4", "Gemini (B)", "--resume")
