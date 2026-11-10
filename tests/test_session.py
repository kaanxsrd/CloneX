"""The sign-in flow: confirmations, exit codes, and failure reporting."""

from __future__ import annotations

import asyncio
import io
from typing import Any

import discord
import pytest
from fakes import VOICE, World, http_error
from rich.console import Console
from scenarios import SCENARIOS, SOURCE_ID, TARGET_ID, named

from clonex import session
from clonex.config import CopyOptions, Settings
from clonex.core.models import CopyIssue, ExitCode
from clonex.ui.terminal import TerminalUI
from clonex.ui.theme import THEME

BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}


class ScriptedUI(TerminalUI):
    """Answers prompts from a script and renders to memory."""

    def __init__(self, confirmation: str = str(TARGET_ID), recover: bool = True) -> None:
        super().__init__(
            Console(file=io.StringIO(), theme=THEME, width=96, force_terminal=False),
            Console(file=io.StringIO(), theme=THEME, width=96, force_terminal=False),
        )
        self.confirmation = confirmation
        self.recover = recover
        self.confirmations = 0
        self.recoveries = 0

    def confirm(self, target_id: int, deletes: bool = True) -> str:
        self.confirmations += 1
        return self.confirmation

    def confirm_recovery(self, issue: CopyIssue) -> bool:
        self.recoveries += 1
        return self.recover

    @property
    def errors(self) -> str:
        return self.error_console.file.getvalue()  # type: ignore[attr-defined]

    @property
    def text(self) -> str:
        return self.console.file.getvalue()  # type: ignore[attr-defined]


def run_client(
    world: World, ui: ScriptedUI, *, apply: bool, settings: Settings | None = None
) -> session.CloneClient:
    async def go() -> session.CloneClient:
        client = session.CloneClient(
            SOURCE_ID, TARGET_ID, apply=apply, ui=ui, settings=settings or Settings()
        )
        guilds = {SOURCE_ID: world.source, TARGET_ID: world.target}
        client.get_guild = guilds.get  # type: ignore[method-assign,assignment]

        async def close() -> None:
            return None

        client.close = close  # type: ignore[method-assign]
        await client.on_ready()
        return client

    return asyncio.run(go())


def write_ops(world: World) -> set[str]:
    return {op for op, _ in world.http.calls} - {"get_member", "get_from_cdn"}


def test_preview_mode_never_asks_and_never_writes() -> None:
    world = BY_NAME["missing_category"].world()
    ui = ScriptedUI()
    client = run_client(world, ui, apply=False)
    assert client.exit_code is ExitCode.OK
    assert (ui.confirmations, ui.recoveries) == (0, 0)
    assert not write_ops(world)
    assert "PREVIEW COMPLETE" in ui.text


def test_a_wrong_confirmation_changes_nothing() -> None:
    world = BY_NAME["typical"].world()
    client = run_client(world, ScriptedUI(confirmation="nope"), apply=True)
    assert client.exit_code is ExitCode.DECLINED
    assert not write_ops(world)


def test_a_confirmed_copy_succeeds() -> None:
    world = BY_NAME["non_owner_keeps_admin_role"].world()
    client = run_client(world, ScriptedUI(), apply=True)
    assert client.exit_code is ExitCode.WARNINGS  # the typical source has skipped channel types
    assert "edit_guild" in write_ops(world)


def test_settings_reach_the_copy() -> None:
    world = BY_NAME["typical"].world()
    chosen = Settings(copy=CopyOptions(voice_channels=False))
    run_client(world, ScriptedUI(), apply=True, settings=chosen)
    created = [f["channel_type"] for op, f in world.http.calls if op == "create_channel"]
    assert created and VOICE not in created


def test_ready_firing_twice_cannot_run_the_copy_twice() -> None:
    world = BY_NAME["typical"].world()
    ui = ScriptedUI()

    async def go() -> None:
        client = session.CloneClient(SOURCE_ID, TARGET_ID, apply=True, ui=ui, settings=Settings())
        guilds = {SOURCE_ID: world.source, TARGET_ID: world.target}
        client.get_guild = guilds.get  # type: ignore[method-assign,assignment]

        async def close() -> None:
            return None

        client.close = close  # type: ignore[method-assign]
        await client.on_ready()
        await client.on_ready()

    asyncio.run(go())
    assert ui.confirmations == 1


def test_a_declined_recovery_reports_partial_changes() -> None:
    world = BY_NAME["declined_recovery"].world()
    ui = ScriptedUI(recover=False)
    client = run_client(world, ui, apply=True)
    assert client.exit_code is ExitCode.DECLINED
    assert "partially modified" in ui.text


def test_a_critical_failure_during_copy_says_so() -> None:
    world = BY_NAME["typical"].world()
    world.http.fail("create_channel", named("general"), error=lambda: http_error(500, 0))
    ui = ScriptedUI()
    client = run_client(world, ui, apply=True)
    assert client.exit_code is ExitCode.FAILED
    assert "partially modified" in ui.errors


def test_a_critical_failure_during_preparation_says_nothing_changed() -> None:
    world = BY_NAME["static_icon_is_copied"].world()
    world.http.icon_error = http_error(500, 0)
    ui = ScriptedUI()
    client = run_client(world, ui, apply=True)
    assert client.exit_code is ExitCode.FAILED
    assert "No destination changes" in ui.errors


def test_missing_servers_are_reported() -> None:
    ui = ScriptedUI()

    async def go() -> ExitCode:
        client = session.CloneClient(SOURCE_ID, TARGET_ID, apply=False, ui=ui, settings=Settings())

        async def close() -> None:
            return None

        client.close = close  # type: ignore[method-assign]
        await client.on_ready()
        return client.exit_code

    assert asyncio.run(go()) is ExitCode.FAILED
    assert "member of both" in ui.errors


def _failing_start(error: Exception, *, copy_started: bool) -> Any:
    async def start(self: session.CloneClient, _token: str, *, reconnect: bool) -> None:
        assert reconnect is False
        self.copy_started = copy_started
        raise error

    return start


@pytest.mark.parametrize(
    ("error", "copy_started", "expected"),
    [
        (discord.LoginFailure("bad"), False, "Login failed"),
        (OSError("offline"), False, "Connection failed (OSError)"),
        (OSError("offline"), True, "partially modified"),
        (discord.GatewayNotFound(), True, "partially modified"),
    ],
)
def test_connection_failures_explain_the_state_of_the_destination(
    monkeypatch: pytest.MonkeyPatch, error: Exception, copy_started: bool, expected: str
) -> None:
    monkeypatch.setattr(
        session.CloneClient, "start", _failing_start(error, copy_started=copy_started)
    )
    ui = ScriptedUI()
    assert (
        session.run("token", SOURCE_ID, TARGET_ID, apply=True, ui=ui, settings=Settings())
        is ExitCode.FAILED
    )
    assert expected in ui.errors
