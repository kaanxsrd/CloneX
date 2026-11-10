"""Named server layouts and fault injections shared by the test suite."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fakes import (
    ADMINISTRATOR,
    FORUM,
    MEMBER_SUBJECT,
    NEWS,
    SELF_ID,
    STAGE,
    World,
    build_world,
    category,
    channel,
    guild_payload,
    http_error,
    member,
    overwrite,
    role,
    text,
    voice,
)

SOURCE_ID = 1
TARGET_ID = 2
ADMIN_ROLE = 300
OWNED: dict[str, Any] = {"owner_id": SELF_ID}
ADMIN_MEMBER = member(SELF_ID, [ADMIN_ROLE])


def typical_source(**extra: Any) -> dict[str, Any]:
    """One of everything the planner distinguishes, listed in display order."""
    return guild_payload(
        SOURCE_ID,
        name="Source Server",
        everyone_permissions=1024,
        roles=[
            role(11, "Member", 1, permissions=2048, color=0x123456),
            role(12, "Moderator", 2, permissions=8192, hoist=True, mentionable=True),
            role(13, "Bot Role", 3, managed=True),
        ],
        channels=[
            category(20, "INFO", 0, overwrites=[overwrite(11, allow=1024)]),
            text(
                21,
                "welcome",
                0,
                parent=20,
                topic="hello",
                rate_limit_per_user=5,
                overwrites=[overwrite(SOURCE_ID, deny=1024), overwrite(12, allow=2048)],
            ),
            text(22, "updates", 1, parent=20, kind=NEWS, topic="news"),
            category(30, "COMMUNITY", 1),
            text(31, "general", 2, parent=30, nsfw=True),
            voice(32, "Lounge", 0, parent=30, bitrate=384000, user_limit=8),
            voice(33, "Quiet", 1, parent=30, rate_limit_per_user=30),
            channel(34, FORUM, "forum", 3, parent=30),
            channel(35, STAGE, "stage", 2, parent=30, bitrate=64000, user_limit=0),
            text(40, "uncategorized", 3),
        ],
        **extra,
    )


def typical_target(**extra: Any) -> dict[str, Any]:
    return guild_payload(
        TARGET_ID,
        name="Destination",
        roles=[role(201, "Old Role", 1), role(202, "Integration", 2, managed=True)],
        channels=[category(210, "old-category", 0), text(211, "old-chat", 0, parent=210)],
        **{**OWNED, **extra},
    )


def non_owner_target(**extra: Any) -> dict[str, Any]:
    payload = guild_payload(
        TARGET_ID,
        name="Destination",
        roles=[
            role(201, "Old Role", 1),
            role(ADMIN_ROLE, "Admin", 5, permissions=ADMINISTRATOR),
        ],
        channels=[text(211, "old-chat", 0)],
        **extra,
    )
    payload["members"] = [ADMIN_MEMBER]
    return payload


Setup = Callable[[World], None]


@dataclass(frozen=True)
class Scenario:
    name: str
    source: Callable[[], dict[str, Any]] = typical_source
    target: Callable[[], dict[str, Any]] = typical_target
    setup: Setup | None = None
    decline: bool = False

    def world(self) -> World:
        world = build_world(self.source(), self.target())
        if self.setup is not None:
            self.setup(world)
        return world


def failing(op: str, when: Callable[[dict[str, Any]], bool] | None = None) -> Setup:
    def apply(world: World) -> None:
        world.http.fail(op, when)

    return apply


def named(name: str) -> Callable[[dict[str, Any]], bool]:
    return lambda fields: fields.get("name") == name


def _absent_member_source() -> dict[str, Any]:
    payload = typical_source()
    payload["channels"][1]["permission_overwrites"] += [
        overwrite(777, MEMBER_SUBJECT, allow=1024),
        overwrite(778, MEMBER_SUBJECT, deny=1024),
    ]
    payload["channels"][4]["permission_overwrites"] += [overwrite(777, MEMBER_SUBJECT, allow=1)]
    return payload


def _present_member(world: World) -> None:
    world.http.members[778] = member(778)


def _managed_overwrite_source() -> dict[str, Any]:
    payload = typical_source()
    payload["channels"][4]["permission_overwrites"] += [overwrite(13, allow=1024)]
    return payload


def _missing_role_overwrite_source() -> dict[str, Any]:
    payload = typical_source()
    payload["channels"][4]["permission_overwrites"] += [overwrite(555, allow=1024)]
    return payload


def _missing_category_source() -> dict[str, Any]:
    payload = typical_source()
    payload["channels"][-1]["parent_id"] = "999"
    return payload


def _odd_role_names_source() -> dict[str, Any]:
    payload = typical_source()
    payload["roles"] += [
        role(14, "⠀ㅤ", 4),
        role(15, "  padded\x07  ", 5),
        role(16, "x" * 130, 6),
    ]
    return payload


def _overflow_source() -> dict[str, Any]:
    payload = typical_source()
    payload["roles"] += [role(1000 + index, f"Extra {index}", 10 + index) for index in range(260)]
    return payload


def _name_too_long(world: World) -> None:
    world.http.fail(
        "create_role",
        named("Member"),
        error=lambda: http_error(
            errors={"name": {"_errors": [{"code": "BASE_TYPE_BAD_LENGTH", "message": "no"}]}}
        ),
    )


def _animated_source() -> dict[str, Any]:
    return typical_source(icon="a_abcdef")


def _static_source() -> dict[str, Any]:
    return typical_source(icon="abcdef")


def _icon_unreadable(world: World) -> None:
    world.http.icon_error = OSError("download failed")


def _no_positions_source() -> dict[str, Any]:
    """Every channel shares a position, so only the ID breaks ties."""
    payload = typical_source()
    for entry in payload["channels"]:
        entry["position"] = 0
    payload["channels"].reverse()  # The library's list order must not decide the result.
    return payload


SCENARIOS = [
    Scenario("typical"),
    Scenario("non_owner_keeps_admin_role", target=non_owner_target),
    Scenario("animated_icon_becomes_static", source=_animated_source),
    Scenario("static_icon_is_copied", source=_static_source),
    Scenario("unreadable_icon_is_kept", source=_static_source, setup=_icon_unreadable),
    Scenario("absent_member_overwrites", source=_absent_member_source, setup=_present_member),
    Scenario("managed_role_overwrite", source=_managed_overwrite_source),
    Scenario("missing_role_overwrite", source=_missing_role_overwrite_source),
    Scenario("missing_category", source=_missing_category_source),
    Scenario("odd_role_names", source=_odd_role_names_source),
    Scenario("role_capacity_overflow", source=_overflow_source),
    Scenario("role_name_rejected_for_length", setup=_name_too_long),
    Scenario("tied_positions", source=_no_positions_source),
    Scenario("delete_channel_rejected", setup=failing("delete_channel")),
    Scenario("delete_role_rejected", setup=failing("delete_role")),
    Scenario("everyone_rejected", setup=failing("edit_role")),
    Scenario("create_role_rejected", setup=failing("create_role", named("Moderator"))),
    Scenario("role_order_rejected", setup=failing("move_role_position")),
    Scenario("create_category_rejected", setup=failing("create_channel", named("COMMUNITY"))),
    Scenario("create_text_rejected", setup=failing("create_channel", named("welcome"))),
    Scenario("create_voice_rejected", setup=failing("create_channel", named("Quiet"))),
    Scenario("identity_rejected", setup=failing("edit_guild")),
    Scenario("declined_recovery", setup=failing("create_channel", named("welcome")), decline=True),
]
