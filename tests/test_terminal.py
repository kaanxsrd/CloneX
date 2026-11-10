"""The terminal UI, rendered to memory."""

from __future__ import annotations

import io
import sys
import threading
from dataclasses import replace

import pytest
from rich.console import Console

from clonex.core.models import CopyIssue, CopySummary
from clonex.ui.demo import demo
from clonex.ui.terminal import TerminalUI
from clonex.ui.theme import THEME, literal

SUMMARY = CopySummary(
    source_name="Source",
    source_id=1,
    target_name="Target",
    target_id=2,
    roles=3,
    categories=1,
    text_channels=2,
    voice_channels=1,
    delete_channels=4,
    delete_roles=5,
)
ISSUE = CopyIssue("Creating roles", "Moderator", "Rejected.", "Skip this role.")


def make_ui(width: int = 96) -> TerminalUI:
    console = Console(file=io.StringIO(), theme=THEME, width=width, force_terminal=False)
    errors = Console(file=io.StringIO(), theme=THEME, width=width, force_terminal=False)
    return TerminalUI(console, errors)


def output(ui: TerminalUI) -> str:
    return ui.console.file.getvalue()  # type: ignore[attr-defined]


def scripted(ui: TerminalUI, monkeypatch: pytest.MonkeyPatch, *answers: str) -> list[str]:
    remaining = list(answers)
    monkeypatch.setattr(ui.console, "input", lambda *_args, **_kwargs: remaining.pop(0))
    return remaining


def test_server_controlled_text_cannot_inject_terminal_sequences() -> None:
    assert literal("a\x1b[31mred\x1b[0m\x07b").plain == "ared b"


def test_rich_markup_in_names_is_shown_literally() -> None:
    assert literal("[bold]x[/bold]").plain == "[bold]x[/bold]"


def test_preview_reports_every_planned_change() -> None:
    ui = make_ui()
    ui.preview(
        replace(
            SUMMARY,
            retained_role="Admin",
            limited_bitrates=2,
            static_icon=True,
            skipped_member_overwrites=7,
            skipped_member_channels=3,
            issues=(ISSUE,),
        )
    )
    text = output(ui)
    for expected in (
        "Channels and categories: 4. Roles: 5.",
        "Admin",
        "static PNG",
        "OMISSIONS",
        "Member-specific permission overwrites",
    ):
        assert expected in text


def test_long_adjustment_lists_are_capped() -> None:
    ui = make_ui()
    ui.max_listed = 4
    renamed = tuple((index, f"role-{index}") for index in range(6))
    ui.role_name_changes(replace(SUMMARY, renamed_roles=renamed))
    assert "...and 2 more" in output(ui)
    assert "role-4" not in output(ui)


@pytest.mark.parametrize("answer", ["y", "YES", " yes "])
def test_recovery_accepts_explicit_consent(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    ui = make_ui()
    scripted(ui, monkeypatch, answer)
    assert ui.confirm_recovery(ISSUE) is True


@pytest.mark.parametrize("answer", ["", "n", "NO"])
def test_recovery_declines_by_default(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    ui = make_ui()
    scripted(ui, monkeypatch, answer)
    assert ui.confirm_recovery(ISSUE) is False


def test_recovery_asks_again_on_an_unclear_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    ui = make_ui()
    remaining = scripted(ui, monkeypatch, "maybe", "y")
    assert ui.confirm_recovery(ISSUE) is True
    assert not remaining


def test_menu_retries_until_a_valid_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    ui = make_ui()
    scripted(ui, monkeypatch, "9", "2")
    assert ui.choose_mode() == "copy"


def test_pause_tolerates_a_closed_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    ui = make_ui()

    def closed(*_args: object, **_kwargs: object) -> str:
        raise EOFError

    monkeypatch.setattr(ui.console, "input", closed)
    ui.pause()


def test_skips_and_errors_are_reported_with_the_failed_step() -> None:
    ui = make_ui()
    with ui.copying(3):
        ui.report("Creating roles", "One", True)
        ui.report_skip("Creating roles", "Two")
    assert "SKIP: Creating roles / Two" in output(ui)
    ui.error("Boom")
    errors = ui.error_console.file.getvalue()  # type: ignore[attr-defined]
    assert (
        "Failed step" in errors
        and "Steps completed: 2 of 3." in errors
        and "Skipped steps included: 1." in errors
    )


def test_completion_title_reflects_omissions() -> None:
    ui = make_ui()
    ui.completed(SUMMARY)
    assert "COPY COMPLETE" in output(ui)
    ui = make_ui()
    ui.completed(replace(SUMMARY, issues=(ISSUE,)))
    assert "COPY FINISHED WITH WARNINGS" in output(ui)


def test_demo_runs_offline() -> None:
    ui = make_ui(60)
    demo(ui)
    assert "Demo finished" in output(ui)


def test_progress_panel_survives_concurrent_updates() -> None:
    """Rich redraws from its own thread while the copy mutates the recent-steps list."""
    ui = make_ui()
    failures: list[BaseException] = []
    finished = threading.Event()

    def redraw() -> None:
        try:
            while not finished.is_set():
                ui._progress_panel()
        except BaseException as error:
            failures.append(error)

    switch_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    thread = threading.Thread(target=redraw)
    try:
        with ui.copying(50_000):
            thread.start()
            for index in range(50_000):
                ui.report("Phase", str(index), True)
    finally:
        finished.set()
        thread.join()
        sys.setswitchinterval(switch_interval)
    assert not failures
