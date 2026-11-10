"""Terminal colours and safe rendering of server-controlled text."""

from __future__ import annotations

import re

from rich.text import Text
from rich.theme import Theme

THEME = Theme(
    {
        "accent": "bright_cyan",
        "secondary": "bright_magenta",
        "muted": "bright_black",
        "good": "bright_green",
        "warning": "yellow",
        "danger": "bright_red",
        "heading": "bold white",
        "brand": "bold bright_cyan",
        "section": "bold bright_magenta",
    }
)

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def literal(value: object, style: str = "") -> Text:
    """Keep server names literal and prevent control characters from altering the display."""
    return Text(_CONTROL_CHARACTER.sub(" ", _ANSI_ESCAPE.sub("", str(value))), style=style)
