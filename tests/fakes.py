"""Real discord.py-self models running on a recording, in-memory HTTP layer.

Only ``HTTPClient`` is replaced. Guilds, roles, channels, overwrites and every ``edit`` or
``create_*`` call are the library's own code, so these tests also fail if the library stops
accepting the arguments CloneX sends. No test performs network access.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import discord

SELF_ID = 1000
OTHER_OWNER_ID = 1001
TEXT, VOICE, CATEGORY, NEWS, STAGE, FORUM = 0, 2, 4, 5, 13, 15
_BUCKETS = {TEXT: TEXT, NEWS: TEXT, FORUM: TEXT, VOICE: VOICE, STAGE: VOICE, CATEGORY: CATEGORY}
ROLE_SUBJECT, MEMBER_SUBJECT = 0, 1
ADMINISTRATOR = 8


def user(user_id: int) -> dict[str, Any]:
    return {
        "id": str(user_id),
        "username": f"user{user_id}",
        "discriminator": "0",
        "avatar": None,
    }


def member(user_id: int, role_ids: Iterable[int] = ()) -> dict[str, Any]:
    return {
        "user": user(user_id),
        "roles": [str(role_id) for role_id in role_ids],
        "joined_at": "2026-01-01T00:00:00+00:00",
        "flags": 0,
    }


def role(
    role_id: int,
    name: str,
    position: int,
    *,
    permissions: int = 0,
    managed: bool = False,
    color: int = 0,
    hoist: bool = False,
    mentionable: bool = False,
) -> dict[str, Any]:
    return {
        "id": str(role_id),
        "name": name,
        "position": position,
        "permissions": str(permissions),
        "managed": managed,
        "color": color,
        "hoist": hoist,
        "mentionable": mentionable,
        "flags": 0,
    }


def overwrite(
    subject_id: int, kind: int = ROLE_SUBJECT, allow: int = 0, deny: int = 0
) -> dict[str, Any]:
    return {"id": str(subject_id), "type": kind, "allow": str(allow), "deny": str(deny)}


def channel(
    channel_id: int,
    kind: int,
    name: str,
    position: int,
    *,
    parent: int | None = None,
    overwrites: Iterable[dict[str, Any]] = (),
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": str(channel_id),
        "type": kind,
        "name": name,
        "position": position,
        "parent_id": None if parent is None else str(parent),
        "permission_overwrites": list(overwrites),
        "nsfw": False,
        **extra,
    }


def text(channel_id: int, name: str, position: int, **extra: Any) -> dict[str, Any]:
    extra.setdefault("topic", None)
    extra.setdefault("rate_limit_per_user", 0)
    extra.setdefault("default_auto_archive_duration", 1440)
    extra.setdefault("default_thread_rate_limit_per_user", 0)
    return channel(channel_id, extra.pop("kind", TEXT), name, position, **extra)


def voice(channel_id: int, name: str, position: int, **extra: Any) -> dict[str, Any]:
    extra.setdefault("bitrate", 64000)
    extra.setdefault("user_limit", 0)
    extra.setdefault("rtc_region", None)
    extra.setdefault("video_quality_mode", 1)
    extra.setdefault("rate_limit_per_user", 0)
    return channel(channel_id, VOICE, name, position, **extra)


def category(channel_id: int, name: str, position: int, **extra: Any) -> dict[str, Any]:
    return channel(channel_id, CATEGORY, name, position, **extra)


def http_error(
    status: int = 400, code: int = 50035, errors: dict[str, Any] | None = None
) -> discord.HTTPException:
    response = SimpleNamespace(status=status, reason="Rejected")
    message: dict[str, Any] = {"code": code, "message": "Rejected by the fake server"}
    if errors is not None:
        message["errors"] = errors
    return discord.HTTPException(response, message)  # type: ignore[arg-type]


@dataclass
class Failure:
    op: str
    when: Callable[[dict[str, Any]], bool] | None
    error: Callable[[], Exception]
    remaining: int

    def matches(self, op: str, fields: dict[str, Any]) -> bool:
        return self.remaining != 0 and self.op == op and (self.when is None or self.when(fields))


class RecordingHTTP:
    """The subset of ``discord.http.HTTPClient`` that CloneX reaches."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.target: discord.Guild | None = None
        self.channels: dict[int, dict[str, Any]] = {}
        self.members: dict[int, dict[str, Any]] = {}
        self.failures: list[Failure] = []
        self.icon = b"icon-bytes"
        self.icon_error: Exception | None = None
        self._ids = itertools.count(900_000)

    def fail(
        self,
        op: str,
        when: Callable[[dict[str, Any]], bool] | None = None,
        *,
        error: Callable[[], Exception] = http_error,
        times: int = 1,
    ) -> None:
        """Make matching requests raise; ``times=-1`` keeps failing indefinitely."""
        self.failures.append(Failure(op, when, error, times))

    def count(self, op: str) -> int:
        return sum(call_op == op for call_op, _ in self.calls)

    def _record(self, op: str, **fields: Any) -> None:
        self.calls.append((op, fields))
        for failure in self.failures:
            if failure.matches(op, fields):
                failure.remaining -= 1
                raise failure.error()

    def display_order(self) -> list[tuple[int, str]]:
        """Destination channels as ``(bucket, name)``, sorted the way Discord displays them."""
        ordered = sorted(
            self.channels.values(), key=lambda c: (_BUCKETS[c["type"]], c["position"], int(c["id"]))
        )
        return [(_BUCKETS[c["type"]], c["name"]) for c in ordered]

    async def create_role(self, guild_id: int, *, reason: str | None = None, **fields: Any):
        self._record("create_role", guild_id=guild_id, **fields)
        return role(
            next(self._ids),
            fields["name"],
            1,
            permissions=int(fields.get("permissions", 0)),
            color=fields.get("color", 0),
            hoist=fields.get("hoist", False),
            mentionable=fields.get("mentionable", False),
        )

    async def delete_role(self, guild_id: int, role_id: int, *, reason: str | None = None):
        self._record("delete_role", guild_id=guild_id, role_id=role_id)

    async def edit_role(
        self, guild_id: int, role_id: int, *, reason: str | None = None, **fields: Any
    ):
        self._record("edit_role", guild_id=guild_id, role_id=role_id, **fields)
        return role(role_id, "@everyone", 0, permissions=int(fields.get("permissions", 0)))

    async def move_role_position(
        self, guild_id: int, positions: list[dict[str, Any]], *, reason: str | None = None
    ):
        self._record("move_role_position", guild_id=guild_id, positions=positions)
        return []

    async def create_channel(
        self, guild_id: int, channel_type: int, *, reason: str | None = None, **options: Any
    ):
        self._record("create_channel", guild_id=guild_id, channel_type=int(channel_type), **options)
        channel_id = next(self._ids)
        payload = {
            "id": str(channel_id),
            "type": int(channel_type),
            "guild_id": str(guild_id),
            # Discord appends new channels after the existing ones.
            "position": len(self.channels),
            "nsfw": False,
            "topic": None,
            "rate_limit_per_user": 0,
            "default_auto_archive_duration": 1440,
            "default_thread_rate_limit_per_user": 0,
            "bitrate": 64000,
            "user_limit": 0,
            "rtc_region": None,
            "video_quality_mode": 1,
            "parent_id": None,
            "permission_overwrites": [],
            **options,
        }
        self.channels[channel_id] = payload
        return payload

    async def delete_channel(self, channel_id: int, *, reason: str | None = None):
        self._record("delete_channel", channel_id=channel_id)
        self.channels.pop(channel_id, None)

    async def edit_channel(self, channel_id: int, *, reason: str | None = None, **options: Any):
        self._record("edit_channel", channel_id=channel_id, **options)
        self.channels[channel_id].update(options)
        return self.channels[channel_id]

    async def bulk_channel_update(
        self, guild_id: int, data: list[dict[str, Any]], *, reason: str | None = None
    ):
        self._record("bulk_channel_update", guild_id=guild_id, data=data)
        for entry in data:
            if entry["id"] in self.channels:
                self.channels[entry["id"]]["position"] = entry["position"]
            # Discord follows this request with CHANNEL_UPDATE events that refresh the cache.
            cached = self.target.get_channel(entry["id"]) if self.target else None
            if cached is not None:
                cached.position = entry["position"]

    async def edit_guild(self, guild_id: int, *, reason: str | None = None, **fields: Any):
        self._record("edit_guild", guild_id=guild_id, **fields)
        return {"id": str(guild_id), "name": fields.get("name", "edited")}

    async def get_member(self, guild_id: int, member_id: int):
        self._record("get_member", guild_id=guild_id, member_id=member_id)
        if member_id not in self.members:
            raise discord.NotFound(
                SimpleNamespace(status=404, reason="Not Found"),  # type: ignore[arg-type]
                {"code": 10007, "message": "Unknown Member"},
            )
        return self.members[member_id]

    async def get_from_cdn(self, url: str) -> bytes:
        self._record("get_from_cdn", url=url)
        if self.icon_error is not None:
            raise self.icon_error
        return self.icon


@dataclass
class World:
    source: discord.Guild
    target: discord.Guild
    http: RecordingHTTP


def guild_payload(
    guild_id: int,
    *,
    roles: Iterable[dict[str, Any]] = (),
    channels: Iterable[dict[str, Any]] = (),
    members: Iterable[dict[str, Any]] = (),
    owner_id: int = OTHER_OWNER_ID,
    name: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    default = role(guild_id, "@everyone", 0, permissions=extra.pop("everyone_permissions", 0))
    return {
        "id": str(guild_id),
        "name": name or f"Guild {guild_id}",
        "owner_id": str(owner_id),
        "roles": [default, *roles],
        "channels": list(channels),
        "members": [member(SELF_ID), *members],
        "premium_tier": 0,
        "features": [],
        **extra,
    }


def build_world(source: dict[str, Any], target: dict[str, Any]) -> World:
    """Turn two guild payloads into live library objects sharing one recording HTTP layer."""
    http = RecordingHTTP()
    client = discord.Client(chunk_guilds_at_startup=False, guild_subscriptions=False)
    state = client._connection
    state.http = http  # type: ignore[assignment]
    state.user = discord.ClientUser(state=state, data=user(SELF_ID))  # type: ignore[arg-type]
    guilds = [discord.Guild(data=payload, state=state) for payload in (source, target)]  # type: ignore[arg-type]
    http.target = guilds[1]
    for payload in target["channels"]:
        http.channels[int(payload["id"])] = dict(payload)
    return World(guilds[0], guilds[1], http)
