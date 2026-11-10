"""How settings change what a copy does, including what still needs the user's consent."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from fakes import CATEGORY, TEXT, VOICE, World, overwrite
from scenarios import SCENARIOS, Scenario, typical_source, typical_target

from clonex.config import CopyOptions, ReplaceOptions, Settings
from clonex.core.executor import Executor
from clonex.core.models import CopySummary
from clonex.core.plan import build_plan
from clonex.core.recovery import IssueLog

BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}


def settings(**copy: Any) -> Settings:
    return Settings(copy=CopyOptions(**copy))


def additive() -> Settings:
    return Settings(replace=ReplaceOptions(channels=False, roles=False))


def run(world: World, chosen: Settings) -> tuple[Executor, list[Any], int]:
    prompts: list[Any] = []
    steps = {"count": 0}

    async def decide(issue: Any) -> bool:
        prompts.append(issue)
        return True

    def report(_p: str, _i: str, done: bool) -> None:
        steps["count"] += done

    def report_skip(_p: str, _i: str) -> None:
        steps["count"] += 1

    async def go() -> Executor:
        log = IssueLog(decide)
        plan = await build_plan(world.source, world.target, log, chosen)
        executor = Executor(plan, log, report=report, report_skip=report_skip)
        await executor.run()
        return executor

    return asyncio.run(go()), prompts, steps["count"]


def created(world: World, kind: int | None = None) -> list[dict[str, Any]]:
    return [
        fields
        for op, fields in world.http.calls
        if op == "create_channel" and (kind is None or fields["channel_type"] == kind)
    ]


def ops(world: World) -> set[str]:
    return {op for op, _ in world.http.calls}


def typical() -> World:
    return BY_NAME["typical"].world()


@pytest.mark.parametrize(
    "chosen",
    [
        settings(roles=False),
        settings(everyone_permissions=False),
        settings(categories=False),
        settings(text_channels=False),
        settings(voice_channels=False),
        settings(announcement_channels="skip"),
        settings(permission_overwrites=False),
        settings(server_name=False),
        settings(server_icon=False),
        settings(server_name=False, server_icon=False),
        additive(),
        Settings(
            copy=CopyOptions(
                roles=False,
                everyone_permissions=False,
                categories=False,
                text_channels=False,
                voice_channels=False,
                announcement_channels="skip",
                server_name=False,
                server_icon=False,
            ),
            replace=ReplaceOptions(channels=False, roles=False),
        ),
    ],
    ids=str,
)
def test_progress_always_matches_the_work_for_any_settings(chosen: Settings) -> None:
    executor, _, steps = run(typical(), chosen)
    assert steps == executor.operation_count


def test_turning_everything_off_writes_nothing() -> None:
    chosen = Settings(
        copy=CopyOptions(
            roles=False,
            everyone_permissions=False,
            categories=False,
            text_channels=False,
            voice_channels=False,
            announcement_channels="skip",
            server_name=False,
            server_icon=False,
        ),
        replace=ReplaceOptions(channels=False, roles=False),
    )
    world = typical()
    run(world, chosen)
    assert world.http.calls == []


def test_voice_channels_can_be_left_out() -> None:
    world = typical()
    executor, prompts, _ = run(world, settings(voice_channels=False))
    assert not created(world, VOICE)
    summary = CopySummary.from_plan(executor.plan, executor.log)
    assert summary.excluded_channels == 2
    assert not prompts


def test_text_channels_and_announcements_are_separate_choices() -> None:
    world = typical()
    run(world, settings(text_channels=False))
    assert [f["name"] for f in created(world, TEXT)] == ["updates"]
    world = typical()
    run(world, settings(announcement_channels="skip"))
    assert "updates" not in [f["name"] for f in created(world, TEXT)]


def test_excluded_channels_do_not_count_as_warnings() -> None:
    world = typical()
    executor, _, _ = run(world, settings(voice_channels=False))
    assert not executor.log.issues


def test_skipping_categories_leaves_children_uncategorized_without_a_prompt() -> None:
    world = typical()
    _, prompts, _ = run(world, settings(categories=False))
    assert not created(world, CATEGORY)
    assert all(f.get("parent_id") is None for f in created(world))
    assert not prompts


def test_replace_off_deletes_nothing_and_says_so() -> None:
    world = typical()
    executor, _, _ = run(world, additive())
    assert not {"delete_channel", "delete_role"} & ops(world)
    summary = CopySummary.from_plan(executor.plan, executor.log)
    assert not summary.deletes_anything


def test_community_is_allowed_when_channels_are_not_deleted() -> None:
    community = Scenario("c", target=lambda: typical_target(features=["COMMUNITY"]))
    run(community.world(), additive())


def test_copy_roles_off_keeps_destination_roles_only_if_replace_is_off() -> None:
    world = typical()
    run(world, Settings(copy=CopyOptions(roles=False), replace=ReplaceOptions(roles=False)))
    assert not {"create_role", "delete_role", "move_role_position"} & ops(world)


def test_disabling_roles_discloses_lost_overwrites_once() -> None:
    world = typical()
    _, prompts, _ = run(world, settings(roles=False))
    assert [issue.phase for issue in prompts] == ["Checking copy settings"]
    welcome = next(f for f in created(world) if f["name"] == "welcome")
    assert {int(entry["id"]) for entry in welcome["permission_overwrites"]} == {2}


def test_disabling_overwrites_needs_consent_and_sends_none() -> None:
    world = typical()
    _, prompts, _ = run(world, settings(permission_overwrites=False))
    assert [issue.phase for issue in prompts] == ["Checking copy settings"]
    assert all(not f["permission_overwrites"] for f in created(world))


def test_declining_a_settings_disclosure_stops_before_any_write() -> None:
    from clonex.core.errors import CloneCancelled

    world = typical()

    async def refuse(_issue: Any) -> bool:
        return False

    async def go() -> None:
        await build_plan(world.source, world.target, IssueLog(refuse), settings(roles=False))

    with pytest.raises(CloneCancelled):
        asyncio.run(go())
    assert not world.http.calls


def test_no_prompt_when_settings_remove_nothing() -> None:
    plain = replace(BY_NAME["typical"], source=lambda: _without_overwrites())
    _, prompts, _ = run(plain.world(), settings(permission_overwrites=False))
    assert not prompts


def _without_overwrites() -> dict[str, Any]:
    payload = typical_source()
    for channel in payload["channels"]:
        channel["permission_overwrites"] = []
    return payload


def test_disabling_overwrites_skips_member_lookups() -> None:
    def source() -> dict[str, Any]:
        payload = typical_source()
        payload["channels"][1]["permission_overwrites"] += [overwrite(777, 1)]
        return payload

    world = Scenario("m", source=source).world()
    run(world, settings(permission_overwrites=False))
    assert "get_member" not in ops(world)


@pytest.mark.parametrize(
    ("chosen", "expected"),
    [
        (settings(server_name=False), {"icon"}),
        (settings(server_icon=False), {"name"}),
    ],
)
def test_server_identity_parts_are_independent(chosen: Settings, expected: set[str]) -> None:
    world = BY_NAME["static_icon_is_copied"].world()
    run(world, chosen)
    fields = next(f for op, f in world.http.calls if op == "edit_guild")
    assert set(fields) - {"guild_id"} == expected


def test_server_icon_off_never_downloads_it() -> None:
    world = BY_NAME["static_icon_is_copied"].world()
    run(world, settings(server_icon=False))
    assert "get_from_cdn" not in ops(world)


def test_everyone_permissions_can_stay() -> None:
    world = typical()
    run(world, settings(everyone_permissions=False))
    assert "edit_role" not in ops(world)


def test_the_audit_reason_is_configurable() -> None:
    seen: list[str | None] = []
    world = typical()
    original = world.http.create_channel

    async def spy(guild_id: int, channel_type: int, *, reason: str | None = None, **options: Any):
        seen.append(reason)
        return await original(guild_id, channel_type, reason=reason, **options)

    world.http.create_channel = spy  # type: ignore[method-assign]
    run(world, Settings(audit_reason="Scheduled rebuild"))
    assert seen and set(seen) == {"Scheduled rebuild"}
