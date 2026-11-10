"""Offline walkthrough of the real interface, driven entirely by sample data."""

from __future__ import annotations

import time

from clonex.core.models import CopySummary
from clonex.i18n import t
from clonex.ui.terminal import TerminalUI

_STEP_DELAY_SECONDS = 0.25
_SUMMARY = CopySummary(
    source_name="Example Community",
    source_id=111111111111111111,
    target_name="Example Community Clone",
    target_id=222222222222222222,
    roles=9,
    categories=3,
    text_channels=12,
    voice_channels=2,
    delete_channels=4,
    delete_roles=0,
)
_STEPS = (
    ("phase.remove_channels", "welcome"),
    ("phase.create_roles", "Community Lead"),
    ("phase.create_roles", "Moderator"),
    ("phase.create_categories", "INFORMATION"),
    ("phase.create_categories", "COMMUNITY"),
    ("phase.create_text", "announcements"),
    ("phase.create_text", "general"),
    ("phase.create_voice", "Lounge"),
    ("phase.restore_channel_order", "general"),
    ("phase.update_identity", "Example Community"),
)


def demo(ui: TerminalUI) -> None:
    """Show the actual interface with synthetic data and no network access."""
    ui.banner(demo=True)
    ui.preview(_SUMMARY)
    with ui.copying(len(_STEPS)):
        for phase_key, name in _STEPS:
            phase = t(phase_key)
            ui.report(phase, name, False)
            if ui.console.is_interactive:
                time.sleep(_STEP_DELAY_SECONDS)
            ui.report(phase, name, True)
    ui.completed(_SUMMARY)
    ui.note(t("demo.finished"))
