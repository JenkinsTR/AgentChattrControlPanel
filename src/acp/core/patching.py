from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PATCH_BEGIN = "# ACP_PATCH_ALLOWED_ORIGINS_BEGIN"
PATCH_END = "# ACP_PATCH_ALLOWED_ORIGINS_END"

@dataclass(frozen=True)
class PatchStatus:
    patched: bool
    backup_exists: bool
    backup_path: Path

def _backup_path(app_py: Path) -> Path:
    return app_py.with_suffix(".py.acp.bak")

def status(app_py: Path) -> PatchStatus:
    txt = app_py.read_text("utf-8") if app_py.exists() else ""
    bak = _backup_path(app_py)
    return PatchStatus(
        patched=(PATCH_BEGIN in txt and PATCH_END in txt),
        backup_exists=bak.exists(),
        backup_path=bak,
    )

def patch_allowed_origins(app_py: Path) -> None:
    """Patch agentchattr/app.py to allow non-localhost Origin when server.host is a LAN IP.

    Why:
      app.py only allows origins of http://127.0.0.1:<port> and http://localhost:<port>.
      When you browse from another device to http://192.168.x.x:<port>, browser sends Origin accordingly and gets blocked.

    Patch strategy:
      After `allowed_origins = {...}`, add:
        _acp_host = cfg.get('server',{}).get('host','127.0.0.1')
        if _acp_host not in ('127.0.0.1','localhost','::1','0.0.0.0'):
            allowed_origins.add(f"http://{_acp_host}:{port}")
    """
    if not app_py.exists():
        raise FileNotFoundError(app_py)

    st = status(app_py)
    if st.patched:
        return

    bak = st.backup_path
    if not bak.exists():
        bak.write_text(app_py.read_text("utf-8"), "utf-8")

    lines = app_py.read_text("utf-8").splitlines(True)

    # Find allowed_origins definition inside _install_security_middleware
    # We look for: allowed_origins = {
    insert_at = None
    for i, line in enumerate(lines):
        if "allowed_origins" in line and "{" in line and "=" in line:
            insert_at = i
            # Insert after the closing brace of that set literal
            # Scan forward until we see a line with just "}" (or "}" with commas/spaces)
            j = i + 1
            while j < len(lines):
                if lines[j].lstrip().startswith("}"):
                    insert_at = j + 1
                    break
                j += 1
            break

    if insert_at is None:
        raise RuntimeError("Couldn't locate allowed_origins block in app.py; agentchattr may have changed upstream.")

    patch = [
        "\n",
        f"    {PATCH_BEGIN}\n",
        "    _acp_host = cfg.get('server', {}).get('host', '127.0.0.1')\n",
        "    # If binding to a LAN IP, allow that Origin too\n",
        "    if _acp_host not in ('127.0.0.1', 'localhost', '::1', '0.0.0.0'):\n",
        "        allowed_origins.add(f\"http://{_acp_host}:{port}\")\n",
        f"    {PATCH_END}\n",
        "\n",
    ]

    lines[insert_at:insert_at] = patch
    app_py.write_text("".join(lines), "utf-8")

def unpatch(app_py: Path) -> None:
    st = status(app_py)
    if not st.backup_exists:
        # Nothing to do
        return
    # Restore original
    original = st.backup_path.read_text("utf-8")
    app_py.write_text(original, "utf-8")
