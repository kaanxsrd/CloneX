"""Planning and execution, exercised through the real library against a recording HTTP layer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import discord
import pytest
from fakes import VOICE, World, build_world, guild_payload, http_error, role, text, voice
from scenarios import (
    ADMIN_ROLE,
    SCENARIOS,
    SOURCE_ID,
    TARGET_ID,
    Scenario,
    named,
    non_owner_target,
    typical_source,
    typical_target,
)

from clonex.core.errors import CloneCancelled, CloneError
from clonex.core.executor import Executor
from clonex.core.models import CopySummary
from clonex.core.plan import build_plan, copy_role_name
from clonex.core.recovery import IssueLog, can_skip_request

BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}
COMPLETING = [scenario for scenario in SCENARIOS if not scenario.decline]
READ_ONLY = {"get_member", "get_from_cdn"}


@dataclass
class Run:
    world: World
    executor: Executor
    log: IssueLog
    prompts: list[Any] = field(default_factory=list)
    done: int = 0
    skipped: int = 0

    def created(self, kind: int | None = None) -> list[dict[str, Any]]:
        return [
            fields
            for op, fields in self.world.http.calls
            if op == "create_channel" and (kind is None or fields["channel_type"] == kind)
        ]


def copy(world: World, *, decline: bool = False) -> Run:
    async def go() -> Run:
        prompts: list[Any] = []

        async def decide(issue: Any) -> bool:
            prompts.append(issue)
            return not decline

        log = IssueLog(decide)
        plan = await build_plan(world.source, world.target, log)
        counters = {"done": 0, "skipped": 0}

        def report(_phase: str, _item: str, completed: bool) -> None:
            counters["done"] += completed

        def report_skip(_phase: str, _item: str) -> None:
            counters["skipped"] += 1

        executor = Executor(plan, log, report=report, report_skip=report_skip)
        run = Run(world, executor, log, prompts)
        try:
            await executor.run()
        finally:
            run.done, run.skipped = counters["done"], counters["skipped"]
        return run

    return asyncio.run(go())


def first(scenario: str) -> Run:
    return copy(BY_NAME[scenario].world())


def plan_only(world: World) -> Any:
    async def go() -> Any:
        return await build_plan(world.source, world.target, IssueLog(_accept))

    return asyncio.run(go())


async def _accept(_issue: Any) -> bool:
    return True


@pytest.mark.parametrize("scenario", COMPLETING, ids=lambda s: s.name)
def test_every_planned_step_is_reported_exactly_once(scenario: Scenario) -> None:
    run = copy(scenario.world())
    assert run.done + run.skipped == run.executor.operation_count


@pytest.mark.parametrize("scenario", COMPLETING, ids=lambda s: s.name)
def test_the_source_server_is_never_written_to(scenario: Scenario) -> None:
    world = scenario.world()
    copy(world)
    source_channels = {channel.id for channel in world.source.channels}
    source_roles = {source_role.id for source_role in world.source.roles} - {TARGET_ID}
    for op, fields in world.http.calls:
        assert fields.get("guild_id", TARGET_ID) == TARGET_ID, op
        assert fields.get("channel_id") not in source_channels, op
        assert fields.get("role_id") not in source_roles, op


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_planning_only_reads(scenario: Scenario) -> None:
    world = scenario.world()
    plan_only(world)
    assert {op for op, _ in world.http.calls} <= READ_ONLY


def test_summary_counts_match_the_plan_then_the_result() -> None:
    world = BY_NAME["create_text_rejected"].world()
    preview = CopySummary.from_plan(plan_only(BY_NAME["create_text_rejected"].world()), IssueLog())
    assert (preview.roles, preview.categories, preview.text_channels, preview.voice_channels) == (
        2,
        2,
        4,
        2,
    )
    result = CopySummary.from_executor(copy(world).executor)
    assert result.text_channels == 3
    assert result.skipped_steps == 1
    assert result.has_omissions


def test_channels_end_up_in_source_order() -> None:
    world = BY_NAME["typical"].world()
    copy(world)
    text_names = [name for bucket, name in world.http.display_order() if bucket == 0]
    assert text_names == ["welcome", "updates", "general", "uncategorized"]
    voice_names = [name for bucket, name in world.http.display_order() if bucket == VOICE]
    assert voice_names == ["Lounge", "Quiet"]


def test_tied_positions_fall_back_to_id_like_discord() -> None:
    world = BY_NAME["tied_positions"].world()
    copy(world)
    text_names = [name for bucket, name in world.http.display_order() if bucket == 0]
    assert text_names == ["welcome", "updates", "general", "uncategorized"]


def test_ordering_cost_does_not_grow_with_the_channel_count() -> None:
    channels = [text(100 + index, f"text-{index}", index) for index in range(200)]
    source = guild_payload(SOURCE_ID, channels=channels)
    world = build_world(source, typical_target())
    copy(world)
    assert world.http.count("bulk_channel_update") == 1
    assert world.http.count("edit_channel") == 0


def test_one_bulk_request_per_channel_kind() -> None:
    run = first("typical")
    assert run.world.http.count("bulk_channel_update") == 3


def test_rejected_ordering_is_one_decision_and_keeps_the_copy() -> None:
    world = BY_NAME["typical"].world()
    world.http.fail("bulk_channel_update", lambda fields: len(fields["data"]) == 4)
    run = copy(world)
    assert [issue.item for issue in run.prompts] == ["Text channels: 4"]
    assert run.done + run.skipped == run.executor.operation_count


def test_every_channel_of_a_kind_rejected_skips_its_ordering_step() -> None:
    world = BY_NAME["typical"].world()
    world.http.fail("create_channel", lambda fields: fields["channel_type"] == VOICE, times=-1)
    run = copy(world)
    assert run.world.http.count("bulk_channel_update") == 2
    assert run.done + run.skipped == run.executor.operation_count


def test_text_slowmode_is_sent_at_creation() -> None:
    created = {fields["name"]: fields for fields in first("typical").created()}
    assert created["welcome"]["rate_limit_per_user"] == 5


def test_voice_slowmode_costs_one_edit_only_when_set() -> None:
    world = BY_NAME["typical"].world()
    copy(world)
    edits = [fields for op, fields in world.http.calls if op == "edit_channel"]
    assert [edit["rate_limit_per_user"] for edit in edits] == [30]


def test_announcements_become_text_and_unsupported_types_are_skipped() -> None:
    run = first("typical")
    names = {fields["name"]: fields["channel_type"] for fields in run.created()}
    assert names["updates"] == 0
    assert "forum" not in names and "stage" not in names


def test_overwrites_point_at_destination_roles_never_source_ones() -> None:
    world = BY_NAME["typical"].world()
    run = copy(world)
    welcome = next(fields for fields in run.created() if fields["name"] == "welcome")
    subjects = {int(entry["id"]) for entry in welcome["permission_overwrites"]}
    assert subjects == {TARGET_ID, run.executor.role_map[12].id}


def test_managed_roles_are_neither_copied_nor_deleted() -> None:
    world = BY_NAME["typical"].world()
    copy(world)
    assert "Bot Role" not in [f["name"] for op, f in world.http.calls if op == "create_role"]
    assert [f["role_id"] for op, f in world.http.calls if op == "delete_role"] == [201]


def test_non_owner_keeps_their_administrator_role() -> None:
    world = BY_NAME["non_owner_keeps_admin_role"].world()
    copy(world)
    assert ADMIN_ROLE not in [f["role_id"] for op, f in world.http.calls if op == "delete_role"]


def test_voice_bitrate_is_limited_to_the_destination() -> None:
    created = {fields["name"]: fields for fields in first("typical").created(VOICE)}
    assert created["Lounge"]["bitrate"] == 96000


def test_absent_members_only_lose_their_own_overwrites() -> None:
    world = BY_NAME["absent_member_overwrites"].world()
    run = copy(world)
    welcome = next(fields for fields in run.created() if fields["name"] == "welcome")
    subjects = {int(entry["id"]) for entry in welcome["permission_overwrites"]}
    assert 778 in subjects and 777 not in subjects
    assert run.executor.plan.skipped_member_overwrites == {(21, 777), (31, 777)}
    assert world.http.count("get_member") == 2, "absent members must only be looked up once"


@pytest.mark.parametrize("scenario", ["managed_role_overwrite", "missing_role_overwrite"])
def test_unmappable_role_overwrites_need_a_decision(scenario: str) -> None:
    run = first(scenario)
    assert [issue.phase for issue in run.prompts] == ["Checking role overwrites"]


def test_missing_category_needs_a_decision_and_uncategorizes() -> None:
    run = first("missing_category")
    assert [issue.phase for issue in run.prompts] == ["Checking categories"]
    orphan = next(fields for fields in run.created() if fields["name"] == "uncategorized")
    assert orphan.get("parent_id") is None


def test_role_name_length_rejection_retries_once_with_an_id_name() -> None:
    run = first("role_name_rejected_for_length")
    names = [f["name"] for op, f in run.world.http.calls if op == "create_role"]
    assert names == ["Member", "Role 11", "Moderator"]
    assert not run.prompts
    assert run.executor.plan.renamed_roles == {11: "Role 11"}


def test_a_role_that_cannot_be_created_drops_only_its_overwrites() -> None:
    run = first("create_role_rejected")
    assert 12 in run.executor.plan.skipped_role_ids
    welcome = next(fields for fields in run.created() if fields["name"] == "welcome")
    assert {int(entry["id"]) for entry in welcome["permission_overwrites"]} == {TARGET_ID}


def test_a_rejected_category_leaves_children_uncategorized() -> None:
    run = first("create_category_rejected")
    general = next(fields for fields in run.created() if fields["name"] == "general")
    assert general.get("parent_id") is None


def test_role_capacity_overflow_is_disclosed_and_trimmed() -> None:
    run = first("role_capacity_overflow")
    assert run.prompts[0].phase == "Checking role capacity"
    assert run.world.http.count("create_role") + 2 == 250


def test_animated_icon_is_copied_as_png() -> None:
    world = BY_NAME["animated_icon_becomes_static"].world()
    copy(world)
    url = next(f["url"] for op, f in world.http.calls if op == "get_from_cdn")
    assert ".png" in url
    assert next(f for op, f in world.http.calls if op == "edit_guild")["icon"]


def test_unreadable_icon_leaves_the_destination_icon_alone() -> None:
    world = BY_NAME["unreadable_icon_is_kept"].world()
    copy(world)
    assert "icon" not in next(f for op, f in world.http.calls if op == "edit_guild")


def test_source_without_icon_clears_the_destination_icon() -> None:
    world = BY_NAME["typical"].world()
    copy(world)
    assert next(f for op, f in world.http.calls if op == "edit_guild")["icon"] is None


def test_declining_stops_all_further_requests() -> None:
    world = BY_NAME["declined_recovery"].world()
    with pytest.raises(CloneCancelled, match="welcome"):
        copy(world, decline=True)
    assert world.http.calls[-1][1]["name"] == "welcome"


@pytest.mark.parametrize(
    "error",
    [
        lambda: http_error(500, 0),
        lambda: http_error(401, 40001),
        lambda: http_error(403, 50001),
    ],
)
def test_critical_failures_are_never_offered_for_recovery(error: Any) -> None:
    world = BY_NAME["typical"].world()
    world.http.fail("create_channel", named("general"), error=error)
    with pytest.raises(discord.HTTPException):
        copy(world)
    assert world.http.calls[-1][1]["name"] == "general"


def test_a_plan_can_only_be_executed_once() -> None:
    run = first("typical")
    with pytest.raises(CloneError):
        asyncio.run(run.executor.run())


def test_without_a_decider_omissions_are_errors() -> None:
    world = BY_NAME["missing_category"].world()

    async def go() -> None:
        await build_plan(world.source, world.target, IssueLog())

    with pytest.raises(CloneError):
        asyncio.run(go())


def _plan_error(source: dict[str, Any], target: dict[str, Any]) -> str:
    world = build_world(source, target)

    async def go() -> None:
        await build_plan(world.source, world.target, IssueLog(_accept))

    with pytest.raises(CloneError) as caught:
        asyncio.run(go())
    assert not world.http.calls
    return str(caught.value)


def test_copying_a_server_onto_itself_is_refused() -> None:
    world = build_world(typical_source(), typical_target())

    async def go() -> None:
        await build_plan(world.source, world.source, IssueLog(_accept))

    with pytest.raises(CloneError, match="different"):
        asyncio.run(go())


def test_a_community_destination_is_refused() -> None:
    assert "Community" in _plan_error(typical_source(), typical_target(features=["COMMUNITY"]))


def test_a_destination_without_administrator_is_refused() -> None:
    target = guild_payload(TARGET_ID, roles=[role(201, "Old", 1)])
    assert "Your account needs Administrator" in _plan_error(typical_source(), target)


def test_an_ordinary_role_above_the_retained_role_is_refused() -> None:
    target = non_owner_target()
    target["roles"].append(role(204, "Higher", 9))
    assert "above every other" in _plan_error(typical_source(), target)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Moderator", "Moderator"),
        ("  spaced  ", "spaced"),
        ("bell\x07", "bell"),
        ("⠀ㅤ", "Role 5"),
        ("", "Role 5"),
        ("x" * 130, "x" * 100),
        ("Ünïcödé 🎉", "Ünïcödé 🎉"),
    ],
)
def test_role_names_stay_usable(name: str, expected: str) -> None:
    assert copy_role_name(name, 5) == expected


@pytest.mark.parametrize(
    ("status", "code", "skippable"),
    [
        (400, 50035, True),
        (403, 50013, True),
        (404, 10003, True),
        (500, 0, False),
        (429, 0, False),
        (403, 50001, False),
        (401, 40001, False),
    ],
)
def test_only_definite_rejections_are_skippable(status: int, code: int, skippable: bool) -> None:
    assert can_skip_request(http_error(status, code)) is skippable


def test_captcha_is_never_skippable() -> None:
    response = SimpleNamespace(status=400, reason="Captcha")
    captcha = discord.CaptchaRequired(response, {"captcha_key": ["captcha-required"]})  # type: ignore[arg-type]
    assert can_skip_request(captcha) is False


def test_voice_channels_with_no_slowmode_need_no_edit() -> None:
    source = guild_payload(SOURCE_ID, channels=[voice(100, "v", 0)])
    world = build_world(source, typical_target())
    copy(world)
    assert world.http.count("edit_channel") == 0
