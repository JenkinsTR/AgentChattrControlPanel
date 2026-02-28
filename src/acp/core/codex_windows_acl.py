from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .utils import CmdResult, run_cmd


@dataclass(frozen=True)
class AclPreflightResult:
    ok: bool
    title: str
    detail: str
    risky_everyone_write: bool = False
    has_deny_entries: bool = False
    deny_principals: tuple[str, ...] = ()
    raw_acl: str = ""


def _is_windows() -> bool:
    return os.name == "nt"


def _is_admin() -> bool:
    if not _is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _resolve_to_unc_if_mapped(path: str) -> str:
    """If path is on a mapped drive (e.g. K:\\...), return UNC (\\\\server\\share\\...).
    Elevated processes often don't see the user's drive mappings, so repair must use UNC."""
    if not _is_windows() or not path or len(path) < 2:
        return path
    resolved = str(Path(path).resolve())
    if len(resolved) < 2 or resolved[1] != ":":
        return resolved
    drive = resolved[:2].upper()  # e.g. "K:"
    try:
        buf = ctypes.create_unicode_buffer(256)
        size = ctypes.c_uint(256)
        err = ctypes.windll.mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size))
        if err == 0 and buf.value:
            unc_root = buf.value.rstrip("\\")
            return unc_root + "\\" + resolved[3:].lstrip("\\")
    except Exception:
        pass
    return resolved


def _parse_everyone_write_risk(acl_text: str) -> tuple[bool, str]:
    """Detect world-writable ACL entries (Everyone with W/M/F rights)."""
    for raw_line in acl_text.splitlines():
        line = raw_line.strip()
        if "Everyone:" not in line:
            continue
        upper = line.upper()
        if "(F)" in upper or "(M)" in upper or "(W)" in upper or "(RX,W)" in upper:
            return True, line
    return False, ""


def _extract_principal_from_acl_line(line: str, workspace_path: str) -> str:
    text = line.strip()
    if not text or ":" not in text:
        return ""
    ws = str(Path(workspace_path).resolve())
    prefix = ws + " "
    if text.lower().startswith(prefix.lower()):
        text = text[len(prefix):].strip()
    return text.split(":", 1)[0].strip()


def _collect_deny_principals(acl_text: str, workspace_path: str) -> list[str]:
    principals: list[str] = []
    seen: set[str] = set()
    for raw_line in acl_text.splitlines():
        line = raw_line.strip()
        if "(DENY)" not in line.upper():
            continue
        principal = _extract_principal_from_acl_line(line, workspace_path)
        if not principal:
            continue
        key = principal.lower()
        if key in seen:
            continue
        seen.add(key)
        principals.append(principal)
    return principals


def inspect_workspace_acl_for_codex(workspace_path: str) -> AclPreflightResult:
    if not workspace_path or not workspace_path.strip():
        return AclPreflightResult(False, "No workspace", "Set an active workspace first.")
    if not _is_windows():
        return AclPreflightResult(True, "N/A on this OS", "Codex Windows ACL preflight is only needed on Windows.")

    ws = Path(workspace_path).resolve()
    if not ws.exists() or not ws.is_dir():
        return AclPreflightResult(False, "Workspace missing", str(ws))

    try:
        result = run_cmd(["icacls", str(ws)])
    except Exception as e:
        return AclPreflightResult(False, "ACL check failed", str(e))
    acl_raw = (result.out or "") + ("\n" + result.err if result.err else "")
    if result.code != 0:
        detail = (result.err or result.out or "icacls failed").strip()
        return AclPreflightResult(False, "ACL check failed", detail, raw_acl=acl_raw)

    deny_principals = _collect_deny_principals(acl_raw, str(ws))
    risky, line = _parse_everyone_write_risk(acl_raw)
    if deny_principals and risky:
        return AclPreflightResult(
            False,
            "Risky ACL for Codex sandbox",
            f"Detected DENY ACL entries and broad write permissions (e.g. {line}).",
            risky_everyone_write=True,
            has_deny_entries=True,
            deny_principals=tuple(deny_principals),
            raw_acl=acl_raw,
        )
    if deny_principals:
        return AclPreflightResult(
            False,
            "ACL deny entries block writes",
            f"Detected explicit DENY ACL entry: {deny_principals[0]}",
            has_deny_entries=True,
            deny_principals=tuple(deny_principals),
            raw_acl=acl_raw,
        )
    if risky:
        return AclPreflightResult(
            False,
            "Risky ACL for Codex sandbox",
            f"Detected broad write permissions: {line}",
            risky_everyone_write=True,
            raw_acl=acl_raw,
        )

    return AclPreflightResult(True, "ACL looks compatible", str(ws), raw_acl=acl_raw)


def _principal_arg_for_icacls(principal: str) -> str:
    p = principal.strip()
    if not p:
        return ""
    if p.upper().startswith("S-1-"):
        return f"*{p}"
    return f'"{p}"'


def _repair_commands(workspace_path: str, deny_principals: list[str]) -> list[str]:
    ws = str(Path(workspace_path).resolve())
    cmds = [f'icacls "{ws}" /inheritance:d']
    # Explicit deny ACEs override grants and must be removed first.
    for principal in deny_principals:
        arg = _principal_arg_for_icacls(principal)
        if arg:
            cmds.append(f'icacls "{ws}" /remove:d {arg} /T /C')
    cmds.extend(
        [
            f'icacls "{ws}" /remove:d Everyone /T /C',
            f'icacls "{ws}" /remove:g Everyone /T /C',
            f'icacls "{ws}" /grant:r "%USERNAME%:(OI)(CI)(M)" "Administrators:(OI)(CI)(F)" "SYSTEM:(OI)(CI)(F)" /T /C',
        ]
    )
    return cmds


def _run_cmd_sequence(commands: list[str]) -> CmdResult:
    out_parts: list[str] = []
    err_parts: list[str] = []
    exit_code = 0
    for cmd in commands:
        r = run_cmd(["cmd", "/c", cmd], timeout=300)
        out_parts.append(f"$ {cmd}\n{(r.out or '').strip()}")
        if r.err:
            err_parts.append(f"$ {cmd}\n{r.err.strip()}")
        if r.code != 0 and " /remove:" not in cmd.lower():
            exit_code = r.code
    return CmdResult(exit_code, "\n\n".join(out_parts), "\n\n".join(err_parts))


def _run_repair_elevated(workspace_path: str, deny_principals: list[str]) -> CmdResult:
    """Launch ACL repair through UAC if ACP is not already admin.
    Uses UNC path for workspace so the elevated process sees the same folder (mapped drives
    like K: are not visible in the elevated session)."""
    path_for_elevated = _resolve_to_unc_if_mapped(workspace_path)
    commands = _repair_commands(path_for_elevated, deny_principals)
    temp_cmd = Path(tempfile.gettempdir()) / f"acp_acl_repair_{int(time.time() * 1000)}.cmd"
    lines = ["@echo off", "setlocal", "set ERR=0"]
    for cmd in commands:
        if " /remove:" in cmd.lower():
            lines.append(f"{cmd} || echo [WARN] {cmd}")
        else:
            lines.append(f"{cmd} || set ERR=1")
    lines.append("exit /b %ERR%")
    temp_cmd.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    try:
        ps_cmd = (
            f"$p = Start-Process -FilePath 'cmd.exe' "
            f"-ArgumentList @('/c', '\"{str(temp_cmd)}\"') "
            f"-Verb RunAs -PassThru -Wait; "
            f"if ($null -eq $p) {{ exit 1 }}; "
            f"exit $p.ExitCode"
        )
        try:
            return run_cmd(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                timeout=300,
            )
        except Exception as e:
            return CmdResult(1, "", str(e))
    finally:
        try:
            temp_cmd.unlink(missing_ok=True)
        except Exception:
            pass


def repair_workspace_acl_for_codex(workspace_path: str) -> CmdResult:
    if not _is_windows():
        return CmdResult(1, "", "ACL repair is only supported on Windows.")
    if not workspace_path or not workspace_path.strip():
        return CmdResult(1, "", "No workspace path.")
    ws = Path(workspace_path).resolve()
    if not ws.exists() or not ws.is_dir():
        return CmdResult(1, "", f"Workspace does not exist: {ws}")

    pre = inspect_workspace_acl_for_codex(str(ws))
    deny_principals = list(pre.deny_principals) if pre.deny_principals else []
    if _is_admin():
        return _run_cmd_sequence(_repair_commands(str(ws), deny_principals))
    return _run_repair_elevated(str(ws), deny_principals)


def probe_codex_sandbox_write(workspace_path: str) -> CmdResult:
    """Run a local write probe in Codex Windows sandbox mode."""
    if not _is_windows():
        return CmdResult(1, "", "Probe is only supported on Windows.")
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return CmdResult(1, "", "Codex CLI not found on PATH.")
    if not workspace_path or not workspace_path.strip():
        return CmdResult(1, "", "No workspace path.")

    ws = Path(workspace_path).resolve()
    if not ws.exists() or not ws.is_dir():
        return CmdResult(1, "", f"Workspace does not exist: {ws}")

    probe_name = f".acp_codex_probe_{int(time.time())}.txt"
    ps = (
        f"Set-Content -Path '{probe_name}' -Value 'ok'; "
        f"if (Test-Path '{probe_name}') {{ "
        f"Get-Content '{probe_name}'; Remove-Item -Force '{probe_name}'; exit 0 "
        f"}} else {{ Write-Error 'probe missing'; exit 2 }}"
    )
    cmd = [
        "sandbox",
        "windows",
        "--full-auto",
        "-c",
        "windows.sandbox=unelevated",
        "powershell",
        "-NoProfile",
        "-Command",
        ps,
    ]
    # On Windows, Codex often resolves to codex.CMD; invoke via cmd /c for compatibility.
    if codex_bin.lower().endswith((".cmd", ".bat")):
        full_cmd = ["cmd", "/c", codex_bin, *cmd]
    else:
        full_cmd = [codex_bin, *cmd]
    try:
        return run_cmd(full_cmd, cwd=ws, timeout=90)
    except Exception as e:
        return CmdResult(1, "", str(e))
