from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tomlkit import document, dumps, parse, table

@dataclass
class AgentDef:
    name: str
    command: str
    cwd: str
    color: str
    label: str
    resume_flag: str
    write_access: bool = True

DEFAULT_AGENTS = [
    AgentDef("codex", "codex", "..", "#10a37f", "Codex", "exec resume", write_access=True),
    AgentDef("gemini", "gemini", "..", "#4285f4", "Gemini", "--resume", write_access=True),
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

def set_agent(doc: Any, a: AgentDef) -> None:
    doc = ensure_config_structure(doc)
    if a.name not in doc["agents"]:
        doc["agents"][a.name] = table()
    doc["agents"][a.name]["command"] = a.command
    doc["agents"][a.name]["cwd"] = a.cwd
    doc["agents"][a.name]["color"] = a.color
    doc["agents"][a.name]["label"] = a.label
    doc["agents"][a.name]["resume_flag"] = a.resume_flag
    doc["agents"][a.name]["write_access"] = a.write_access
    if a.name.lower().startswith("codex"):
        # Keep flags explicit to avoid --full-auto reintroducing on-request prompts.
        doc["agents"][a.name]["extra_args"] = [
            "--sandbox", "workspace-write", "-a", "never", "-c", "windows.sandbox=unelevated"
        ] if a.write_access else []

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
        agents = [k for k in doc.get("agents", {}).keys()]
    for name in agents:
        if "agents" in doc and name in doc["agents"]:
            doc["agents"][name]["cwd"] = workspace_path


def get_agent_write_access(doc: Any, name: str) -> bool:
    """Get write_access for an agent. Default True if not set. For Codex, infers from extra_args."""
    agents = doc.get("agents", {})
    if name not in agents:
        return True
    cfg = agents[name]
    if "write_access" in cfg:
        val = cfg["write_access"]
        return bool(val) if not isinstance(val, str) else val.lower() not in ("false", "0", "no", "off")
    # Infer from extra_args for Codex (--full-auto, -a never, or --sandbox workspace-write)
    if name.lower().startswith("codex"):
        extra = cfg.get("extra_args", [])
        if isinstance(extra, str):
            extra = [extra] if extra else []
        extra = list(extra)
        if "--full-auto" in extra:
            return True
        for i in range(len(extra) - 1):
            if extra[i] == "--sandbox" and extra[i + 1] == "workspace-write":
                return True
            if extra[i] in ("-a", "--ask-for-approval") and extra[i + 1] == "never":
                return True
        return False
    return True


def set_agent_write_access(doc: Any, name: str, value: bool) -> None:
    """Set write_access for an agent. Updates extra_args for Codex, write_access for all.
    When name is 'codex' or 'gemini', also updates codex_A/B and gemini_A/B if present."""
    doc = ensure_config_structure(doc)
    # When toggling "codex", update codex + codex_A/B; when "gemini", update gemini + gemini_A/B
    prefix = name.lower().rstrip("_")
    to_update = [n for n in doc.get("agents", {}).keys() if n.lower().startswith(prefix)]
    if not to_update:
        to_update = [name]
    for agent_name in to_update:
        if agent_name not in doc["agents"]:
            doc["agents"][agent_name] = table()
        cfg = doc["agents"][agent_name]
        cfg["write_access"] = value

    # For Codex: sync extra_args so wrapper gets deterministic sandbox + approval behavior.
    for agent_name in to_update:
        if not agent_name.lower().startswith("codex"):
            continue
        cfg = doc["agents"][agent_name]
        extra = list(cfg.get("extra_args", []) or [])
        if isinstance(extra, str):
            extra = [extra] if extra else []
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
        if value:
            new_extra = ["--sandbox", "workspace-write", "-a", "never", "-c", "windows.sandbox=unelevated"] + new_extra
        cfg["extra_args"] = new_extra

def ensure_slot_agents(doc: Any, workspace_a: str, workspace_b: str) -> None:
    # Create codex_A/gemini_A + codex_B/gemini_B
    def mk(name, cmd, cwd, color, label, resume):
        set_agent(doc, AgentDef(name, cmd, cwd, color, label, resume))
    mk("codex_A", "codex", workspace_a, "#10a37f", "Codex (A)", "exec resume")
    mk("gemini_A", "gemini", workspace_a, "#4285f4", "Gemini (A)", "--resume")
    mk("codex_B", "codex", workspace_b, "#10a37f", "Codex (B)", "exec resume")
    mk("gemini_B", "gemini", workspace_b, "#4285f4", "Gemini (B)", "--resume")
