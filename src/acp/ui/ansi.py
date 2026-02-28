"""Convert ANSI escape sequences to HTML for display in rich-text widgets."""

from __future__ import annotations

import re
from html import escape

# ANSI SGR (Select Graphic Rendition) codes to CSS
# Format: \x1b[Nm or \x1b[N;M;Km
_FG_COLORS = {
    30: "#000000",  # black
    31: "#cd3131",  # red
    32: "#0dbc79",  # green
    33: "#e5e510",  # yellow
    34: "#2472c8",  # blue
    35: "#bc3fbc",  # magenta
    36: "#11a8cd",  # cyan
    37: "#e5e5e5",  # white
    39: None,       # default
    90: "#666666",  # bright black
    91: "#f14c4c",  # bright red
    92: "#23d18b",  # bright green
    93: "#f5f543",  # bright yellow
    94: "#3b8eea",  # bright blue
    95: "#d670d6",  # bright magenta
    96: "#29b8db",  # bright cyan
    97: "#e5e5e5",  # bright white
}

_BG_COLORS = {
    40: "#000000",
    41: "#cd3131",
    42: "#0dbc79",
    43: "#e5e510",
    44: "#2472c8",
    45: "#bc3fbc",
    46: "#11a8cd",
    47: "#e5e5e5",
    49: None,
}


def _parse_sgr(codes: str) -> dict | None:
    """Parse SGR parameters. Returns style dict, or None for full reset."""
    parts = [int(x) for x in codes.split(";") if x.strip()]
    style: dict[str, str | None] = {}
    i = 0
    while i < len(parts):
        n = parts[i]
        if n == 0:
            return None  # full reset
        if n == 1:
            style["font-weight"] = "bold"
        elif n == 2:
            style["font-weight"] = "normal"
        elif n == 22:
            style["font-weight"] = "normal"
        elif n in _FG_COLORS:
            style["color"] = _FG_COLORS[n]  # None means reset
        elif n in _BG_COLORS:
            style["background-color"] = _BG_COLORS[n]
        i += 1
    return style


def _style_to_attrs(style: dict) -> str:
    return "; ".join(f"{k}: {v}" for k, v in style.items() if v is not None)


def ansi_to_html(text: str) -> str:
    """Convert text with ANSI escape codes to HTML with inline styles."""
    if "\x1b" not in text and "\033" not in text:
        return escape(text)

    # Normalize ESC to \x1b
    text = text.replace("\033", "\x1b")
    pattern = re.compile(r"\x1b\[([0-9;]*)m")
    out: list[str] = []
    current: dict[str, str] = {}
    pos = 0

    for m in pattern.finditer(text):
        # Emit text before this match
        raw = text[pos : m.start()]
        if raw:
            if current:
                attrs = _style_to_attrs(current)
                out.append(f'<span style="{attrs}">{escape(raw)}</span>')
            else:
                out.append(escape(raw))
        pos = m.end()

        sgr = m.group(1)
        if not sgr or sgr == "0":
            current = {}
        else:
            parsed = _parse_sgr(sgr)
            if parsed is None:
                current = {}
            else:
                current = dict(current)
                for k, v in parsed.items():
                    if v is None:
                        current.pop(k, None)
                    else:
                        current[k] = v

    # Emit remainder
    raw = text[pos:]
    if raw:
        if current:
            attrs = _style_to_attrs(current)
            out.append(f'<span style="{attrs}">{escape(raw)}</span>')
        else:
            out.append(escape(raw))

    return "".join(out)
