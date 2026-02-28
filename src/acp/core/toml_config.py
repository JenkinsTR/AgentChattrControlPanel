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

DEFAULT_AGENTS = [
    AgentDef("codex", "codex", "..", "#10a37f", "Codex", "exec resume"),
    AgentDef("gemini", "gemini", "..", "#4285f4", "Gemini", "--resume"),
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

def ensure_slot_agents(doc: Any, workspace_a: str, workspace_b: str) -> None:
    # Create codex_A/gemini_A + codex_B/gemini_B
    def mk(name, cmd, cwd, color, label, resume):
        set_agent(doc, AgentDef(name, cmd, cwd, color, label, resume))
    mk("codex_A", "codex", workspace_a, "#10a37f", "Codex (A)", "exec resume")
    mk("gemini_A", "gemini", workspace_a, "#4285f4", "Gemini (A)", "--resume")
    mk("codex_B", "codex", workspace_b, "#10a37f", "Codex (B)", "exec resume")
    mk("gemini_B", "gemini", workspace_b, "#4285f4", "Gemini (B)", "--resume")
