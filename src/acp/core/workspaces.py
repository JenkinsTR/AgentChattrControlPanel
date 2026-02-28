from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .state import AppState, WorkspaceProfile, save_state
from .utils import ensure_dir

def add_workspace(st: AppState, name: str, path: str) -> None:
    st.workspaces.append(WorkspaceProfile(name=name, path=path))
    if not st.active_workspace:
        st.active_workspace = path
    save_state(st)

def remove_workspace(st: AppState, path: str) -> None:
    st.workspaces = [w for w in st.workspaces if w.path != path]
    if st.active_workspace == path:
        st.active_workspace = st.workspaces[0].path if st.workspaces else ""
    save_state(st)

def set_active_workspace(st: AppState, path: str) -> None:
    st.active_workspace = path
    save_state(st)

def create_workspace_folder(path: str) -> None:
    p = Path(path)
    ensure_dir(p)
