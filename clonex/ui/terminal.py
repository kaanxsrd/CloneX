"""Terminal presentation for CloneX. No Discord requests are made here."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from typing import Any, Literal

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.style import Style
from rich.table import Table
from rich.text import Text

from clonex import __version__
from clonex.config import UiOptions
from clonex.core.models import CopyIssue, CopySummary
from clonex.i18n import no_answers, normalize_digits, t, yes_answers
from clonex.ui.theme import THEME, literal

RECENT_STEPS = 3
Mode = Literal["preview", "copy", "exit"]
_DEFAULT_MAX_LISTED = UiOptions().max_listed


class TerminalUI:
    def __init__(
        self,
        console: Console | None = None,
        error_console: Console | None = None,
        *,
        max_listed: int = _DEFAULT_MAX_LISTED,
    ):
        self.console = console or Console(theme=THEME, highlight=False)
        self.error_console = error_console or Console(theme=THEME, stderr=True, highlight=False)
        self.max_listed = max_listed
        self.progress: Progress | None = None
        self.live: Live | None = None
        self.status: Any = None
        self.task_id: TaskID | None = None
        self.skipped_steps = 0
        self.phase = t("progress.preparing")
        self.item = ""
        self.elapsed = 0.0
        # Rich redraws the live panel from its own thread while the copy updates this state.
        self._state_lock = threading.Lock()
        self._recent: deque[tuple[str, str, bool]] = deque(maxlen=RECENT_STEPS)

    @property
    def width(self) -> int:
        return min(self.console.width, 96)

    def panel(self, content: RenderableType, *, title: str = "", style: str = "accent") -> Panel:
        return Panel(
            content,
            title=Text(title, style=self.console.get_style(style) + Style(bold=True))
            if title
            else None,
            title_align="left",
            border_style=style,
            box=box.ROUNDED,
            padding=(1, 2),
            width=self.width,
        )

    def banner(self, *, apply: bool = False, demo: bool = False) -> None:
        mode_key = (
            "banner.mode_demo" if demo else "banner.mode_copy" if apply else "banner.mode_preview"
        )
        heading = Table.grid(expand=True)
        heading.add_column(ratio=1)
        heading.add_column(justify="right")
        heading.add_row(
            Text.assemble(("CLONEX", "brand"), (f"  v{__version__}", "muted")),
            Text(t(mode_key), style="secondary"),
        )
        self.console.print()
        self.console.print(
            self.panel(
                Group(
                    heading,
                    Text(t("banner.tagline"), style="muted"),
                    Text(),
                    Text(t("banner.steps"), style="white"),
                )
            )
        )
        self.note(t("banner.note_demo") if demo else t("banner.note_live"))

    def choose_mode(self) -> Mode:
        """Ask what to do when the program is started without arguments."""
        options = Table.grid(padding=(0, 2))
        options.add_column(style="brand")
        options.add_column()
        options.add_row("1", t("menu.preview"))
        options.add_row("2", t("menu.copy"))
        options.add_row("3", t("menu.exit"))
        self.console.print()
        self.console.print(self.panel(options, title=f"CLONEX  v{__version__}"))
        modes: dict[str, Mode] = {"1": "preview", "2": "copy", "3": "exit"}
        while True:
            choice = normalize_digits(self.prompt(t("menu.select")).strip())
            if choice in modes:
                return modes[choice]
            self.note(t("menu.invalid"))

    def pause(self) -> None:
        """Keep a window opened by double-click visible until the result has been read."""
        self.console.print()
        with suppress(EOFError, KeyboardInterrupt):
            self.console.input(Text(t("pause.prompt"), style="muted"))

    def note(self, message: str) -> None:
        self.console.print(literal(message, "muted"))

    def token_notice(self) -> None:
        self.console.print()
        self.console.print(Text(t("token.title"), style="brand"))
        self.note(t("token.note"))

    def prompt(self, label: str, *, hint: str = "") -> str:
        self.console.print()
        self.console.print(literal(label, "brand"))
        if hint:
            self.note(hint)
        return self.console.input(Text("  > ", style="accent"))

    @contextmanager
    def busy(self, message: str) -> Iterator[None]:
        if self.console.is_interactive:
            self.status = self.console.status(literal(message, "accent"), spinner="line")
            try:
                with self.status:
                    yield
            finally:
                self.status = None
        else:
            self.note(message)
            yield

    def metrics(self, summary: CopySummary) -> Table:
        table = Table.grid(expand=True, padding=(0, 1))
        for _ in range(4):
            table.add_column(justify="center", ratio=1)
        counts = (
            summary.roles,
            summary.categories,
            summary.text_channels,
            summary.voice_channels,
        )
        table.add_row(*[Text(str(count), style="brand") for count in counts])
        labels = ("metric.roles", "metric.categories", "metric.text", "metric.voice")
        table.add_row(*[Text(t(label), style="muted") for label in labels])
        return table

    def _server_cards(self, summary: CopySummary) -> Table:
        wide = self.width >= 72
        servers = Table.grid(expand=True, padding=(0, 2))
        for _ in range(2 if wide else 1):
            servers.add_column(ratio=1)
        destination = (
            "card.destination_replace" if summary.deletes_anything else "card.destination_add"
        )
        cards = [
            self.panel(
                Group(literal(name, "heading"), literal(identifier, "muted")),
                title=label,
                style=style,
            )
            for name, identifier, label, style in (
                (summary.source_name, summary.source_id, t("card.source"), "accent"),
                (summary.target_name, summary.target_id, t(destination), "secondary"),
            )
        ]
        if wide:
            servers.add_row(*cards)
        else:
            for card in cards:
                servers.add_row(card)
        return servers

    def _changes(self, summary: CopySummary) -> Table:
        details = Table.grid(padding=(0, 2), expand=True)
        details.add_column(style="muted", no_wrap=True)
        details.add_column(ratio=1)
        if summary.deletes_anything:
            details.add_row(
                t("changes.remove_label"),
                t(
                    "changes.remove",
                    channels=summary.delete_channels,
                    roles=summary.delete_roles,
                ),
            )
        replaced = [
            t(key)
            for key, enabled in (
                ("changes.item_name", summary.replaces_name),
                ("changes.item_icon", summary.replaces_icon),
                ("changes.item_everyone", summary.replaces_everyone),
            )
            if enabled
        ]
        if replaced:
            details.add_row(t("changes.replace_label"), t("list.separator").join(replaced))
        details.add_row(t("changes.keep_label"), t("changes.keep"))
        if summary.retained_role is not None:
            details.add_row(t("changes.access_role_label"), literal(summary.retained_role, "good"))
        if summary.limited_bitrates:
            details.add_row(
                t("changes.voice_limit_label"),
                t("changes.voice_limit", count=summary.limited_bitrates),
            )
        if summary.static_icon:
            details.add_row(t("changes.icon_label"), t("changes.icon_static"))
        if summary.excluded_channels:
            details.add_row(
                t("changes.excluded_label"),
                t("changes.excluded", count=summary.excluded_channels),
            )
        return details

    def preview(self, summary: CopySummary) -> None:
        self.console.print()
        self.console.print(Text(t("section.review"), style="section"))
        self.console.print()
        self.console.print(self._server_cards(summary), width=self.width)
        self.console.print(
            self.panel(self.metrics(summary), title=t("panel.to_create"), style="muted")
        )
        self.console.print(
            self.panel(self._changes(summary), title=t("panel.changes"), style="muted")
        )
        self.role_name_changes(summary)
        self.channel_type_changes(summary)
        self.recovery_notes(summary.issues)
        if summary.skipped_member_overwrites:
            self.console.print(
                self.panel(
                    Text(
                        t(
                            "note.member_overwrites",
                            overwrites=summary.skipped_member_overwrites,
                            channels=summary.skipped_member_channels,
                        ),
                        style="warning",
                    ),
                    title=t("panel.copy_note"),
                    style="warning",
                )
            )

    def _adjustment_panel(
        self, intro: str, title: str, rows: Sequence[tuple[str, Text]], *, label_style: str
    ) -> None:
        """Show a warning followed by at most ``max_listed`` affected items."""
        table = Table.grid(padding=(0, 2), expand=True)
        table.add_column(style=label_style)
        table.add_column(ratio=1)
        for label, value in rows[: self.max_listed]:
            table.add_row(label, value)
        if len(rows) > self.max_listed:
            table.add_row("", t("list.more", count=len(rows) - self.max_listed))
        self.console.print(
            self.panel(
                Group(Text(intro, style="warning"), Text(), table), title=title, style="warning"
            )
        )

    def channel_type_changes(self, summary: CopySummary) -> None:
        if not summary.converted_channels and not summary.skipped_channels:
            return
        changes = [(t("adjust.copy_as_text"), channel) for channel in summary.converted_channels]
        changes += [(t("adjust.skip"), channel) for channel in summary.skipped_channels]
        self._adjustment_panel(
            t(
                "adjust.channels_intro",
                converted=len(summary.converted_channels),
                skipped=len(summary.skipped_channels),
            ),
            t("panel.channel_adjustments"),
            [
                (action, literal(t("adjust.channel_item", name=name, kind=kind, id=identifier)))
                for action, (identifier, name, kind) in changes
            ],
            label_style="warning",
        )

    def role_name_changes(self, summary: CopySummary) -> None:
        if not summary.renamed_roles:
            return
        self._adjustment_panel(
            t("adjust.roles_intro", count=len(summary.renamed_roles)),
            t("panel.role_adjustments"),
            [(str(source_id), literal(name)) for source_id, name in summary.renamed_roles],
            label_style="muted",
        )

    def confirm(self, target_id: int, deletes: bool = True) -> str:
        self.console.print(
            self.panel(
                Text(t("confirm.replace" if deletes else "confirm.add"), style="warning"),
                title=t("panel.confirm_replace" if deletes else "panel.confirm_add"),
                style="warning",
            )
        )
        return self.prompt(t("prompt.target"), hint=t("confirm.hint", id=target_id))

    def confirm_recovery(self, issue: CopyIssue) -> bool:
        """Suspend animation while stdin is read in the client's worker thread."""
        activity = self.live or self.status
        if activity is not None:
            activity.stop()
        try:
            body = Text("\n").join(
                literal(line)
                for line in (
                    t("recovery.step", value=issue.phase),
                    t("recovery.item", value=issue.item),
                    *issue.reason.splitlines(),
                    "",
                    t("recovery.if_continue", value=issue.consequence),
                )
            )
            self.console.print(self.panel(body, title=t("panel.recoverable"), style="warning"))
            yes, no = yes_answers(), no_answers()
            while True:
                answer = self.prompt(t("recovery.prompt"), hint=t("recovery.hint"))
                answer = answer.strip().casefold()
                if answer in yes:
                    return True
                if answer in no:
                    return False
                self.note(t("recovery.invalid"))
        finally:
            if activity is not None:
                activity.start()

    def recovery_notes(self, issues: tuple[CopyIssue, ...]) -> None:
        if not issues:
            return
        rows: list[Text] = []
        for index, issue in enumerate(issues, 1):
            rows.extend(
                [
                    literal(f"{index}. {issue.phase} / {issue.item}", "warning"),
                    *(literal(line) for line in issue.reason.splitlines()),
                    literal(issue.consequence),
                    Text(),
                ]
            )
        self.console.print(
            self.panel(
                Group(*rows),
                title=t("panel.omissions", count=len(issues)),
                style="warning",
            )
        )

    def _progress_panel(self) -> Panel:
        with self._state_lock:
            recent = tuple(self._recent)
            phase, item, skipped_steps = self.phase, self.item, self.skipped_steps
        activity = Table.grid(padding=(0, 2), expand=True)
        activity.add_column(style="good", no_wrap=True)
        activity.add_column(ratio=1)
        for step_phase, name, skipped in recent:
            activity.add_row(
                Text(
                    t("progress.skip") if skipped else t("progress.done"),
                    style="warning" if skipped else "good",
                ),
                literal(f"{step_phase} / {name}", "muted"),
            )
        return self.panel(
            Group(
                literal(phase, "heading"),
                literal(item, "accent"),
                Text(),
                self.progress or Text(),
                Text(t("progress.skipped", count=skipped_steps), style="warning")
                if skipped_steps
                else Text(),
                Text(),
                activity,
            ),
            title=t("panel.cloning"),
        )

    @contextmanager
    def copying(self, total: int) -> Iterator[None]:
        with self._state_lock:
            self._recent.clear()
            self.skipped_steps = 0
            self.phase, self.item = t("progress.preparing"), t("progress.waiting")
        self.progress = Progress(
            BarColumn(
                bar_width=None, style="bright_black", complete_style="cyan", finished_style="green"
            ),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self.console,
            auto_refresh=False,
            expand=True,
        )
        self.task_id = self.progress.add_task("copy", total=total)
        started = time.monotonic()
        self.console.print()
        if self.console.is_interactive:
            self.live = Live(
                console=self.console,
                get_renderable=self._progress_panel,
                refresh_per_second=8,
                transient=True,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self.live.start()
        try:
            yield
        finally:
            self.elapsed = time.monotonic() - started
            if self.live is not None:
                self.live.stop()
                self.live = None

    def report(self, phase: str, item: str, completed: bool) -> None:
        if self.progress is None or self.task_id is None:
            return
        if not self.console.is_interactive and phase != self.phase:
            self.console.print(literal(phase, "accent"))
        with self._state_lock:
            self.phase, self.item = phase, item
            if completed:
                self._recent.append((phase, item, False))
        if completed:
            self.progress.advance(self.task_id)

    def report_skip(self, phase: str, item: str) -> None:
        if self.progress is None or self.task_id is None:
            return
        with self._state_lock:
            self.phase, self.item = phase, item
            self.skipped_steps += 1
            self._recent.append((phase, item, True))
        self.progress.advance(self.task_id)
        if self.live is None:
            self.console.print(literal(f"{t('progress.skip')}: {phase} / {item}", "warning"))

    def completed(self, summary: CopySummary) -> None:
        minutes, seconds = divmod(int(self.elapsed), 60)
        style = "warning" if summary.has_omissions else "good"
        self.console.print(
            self.panel(
                Group(
                    literal(summary.target_name, "heading"),
                    Text(t("complete.finished", time=f"{minutes:02d}:{seconds:02d}"), style=style),
                    Text(t("complete.skipped", count=summary.skipped_steps), style=style),
                    Text(),
                    self.metrics(summary),
                    Text(),
                    Text(t("complete.review"), style="muted"),
                ),
                title=t("panel.complete_warnings" if summary.has_omissions else "panel.complete"),
                style=style,
            )
        )
        self.role_name_changes(summary)
        self.channel_type_changes(summary)
        self.recovery_notes(summary.issues)
        if summary.skipped_member_overwrites:
            self.note(t("complete.skipped_members", count=summary.skipped_member_overwrites))

    def preview_complete(self) -> None:
        self.console.print(
            self.panel(
                Text(t("preview.no_changes"), style="accent"),
                title=t("panel.preview_complete"),
            )
        )

    def cancelled(self, message: str | None = None) -> None:
        self.console.print(
            self.panel(
                literal(message or t("cancelled.default")),
                title=t("panel.cancelled"),
                style="warning",
            )
        )

    def error(self, message: str) -> None:
        body = Text("\n").join(literal(line) for line in message.splitlines())
        if self.progress is not None and self.task_id is not None:
            task = self.progress.tasks[self.task_id]
            body.append(f"\n\n{t('error.failed_step')}", style="muted")
            body.append(literal(self.phase, "heading"))
            body.append(f"\n{t('error.item')}", style="muted")
            body.append(literal(self.item))
            body.append(
                "\n\n"
                + t("error.steps_completed", done=int(task.completed), total=int(task.total or 0)),
                style="muted",
            )
            if self.skipped_steps:
                body.append(
                    " " + t("error.steps_skipped", count=self.skipped_steps), style="warning"
                )
        self.error_console.print(self.panel(body, title=t("panel.stopped"), style="danger"))
