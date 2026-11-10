"""Read-only planning: nothing in this module writes to either server."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from operator import attrgetter
from typing import Any
from unicodedata import category as unicode_category

import discord

from clonex.config import Settings
from clonex.core.discord_errors import http_error_details
from clonex.core.errors import CloneError
from clonex.core.models import CopyIssue
from clonex.core.recovery import IssueLog, can_skip_request
from clonex.i18n import t

MAX_ROLES = 250
MAX_ROLE_NAME = 100
UNKNOWN_MEMBER = 10007
TEXT_CHANNEL_TYPES = (discord.ChannelType.text, discord.ChannelType.news)
COPYABLE_CHANNEL_TYPES = (
    discord.ChannelType.category,
    discord.ChannelType.voice,
    *TEXT_CHANNEL_TYPES,
)
DEFAULT_SETTINGS = Settings()
_BLANK_GLYPHS = frozenset("ᅟᅠ⠀ㅤﾠ")
# Discord displays channels by position and breaks ties by ID.
_DISPLAY_ORDER = attrgetter("position", "id")

Overwrites = dict[Any, discord.PermissionOverwrite]


def copy_role_name(name: str, source_id: int) -> str:
    """Preserve visible names; make empty, invisible, or overlong names usable."""
    cleaned = "".join(char for char in name if unicode_category(char) not in {"Cc", "Cs"})
    cleaned = cleaned.strip()[:MAX_ROLE_NAME].rstrip()
    if any(
        not char.isspace() and unicode_category(char)[0] not in "CMZ" and char not in _BLANK_GLYPHS
        for char in cleaned
    ):
        return cleaned
    return f"Role {source_id}"


def is_category(channel: discord.abc.GuildChannel) -> bool:
    return channel.type is discord.ChannelType.category


def retained_role(target: discord.Guild) -> discord.Role | None:
    """The destination role that keeps a non-owner's access, or ``None`` for the owner."""
    if target.me is None or target.owner_id == target.me.id:
        return None
    return target.me.top_role


def _joined_member(guild: discord.Guild) -> discord.Member:
    if guild.unavailable or guild.me is None:
        raise CloneError(t("validate.unavailable", id=guild.id))
    return guild.me


def validate(source: discord.Guild, target: discord.Guild, settings: Settings) -> None:
    """Raise unless the account can safely change the destination as configured."""
    if source.id == target.id:
        raise CloneError(t("error.same_server"))
    _joined_member(source)
    account = _joined_member(target)
    if not account.guild_permissions.administrator:
        raise CloneError(t("validate.no_admin", id=target.id))
    kept = retained_role(target)
    if kept is not None:
        if not kept.permissions.administrator:
            raise CloneError(t("validate.retained_not_admin"))
        if any(
            not role.is_default() and not role.managed and role.id != kept.id and role >= kept
            for role in target.roles
        ):
            raise CloneError(t("validate.role_hierarchy"))
    if settings.replace.channels and "COMMUNITY" in target.features:
        raise CloneError(t("validate.community"))


def _is_selected(channel: Any, settings: Settings) -> bool:
    options = settings.copy
    kind = channel.type
    if kind is discord.ChannelType.category:
        return options.categories
    if kind is discord.ChannelType.voice:
        return options.voice_channels
    if kind is discord.ChannelType.news:
        return options.announcement_channels == "text"
    return options.text_channels


@dataclass(slots=True)
class CopyPlan:
    """Everything needed to run a copy.

    Execution keeps adding to the ``skipped_*``, ``uncategorized_ids`` and rename fields when
    the user accepts a later omission, so a plan is single-use.
    """

    source: discord.Guild
    target: discord.Guild
    settings: Settings
    retained_role: discord.Role | None
    roles: list[discord.Role]
    role_names: dict[int, str]
    renamed_roles: dict[int, str]
    roles_to_delete: list[discord.Role]
    channels: list[Any]
    converted_channels: list[Any]
    skipped_channels: list[Any]
    excluded_channels: int
    channels_to_delete: list[Any]
    overwrites: dict[int, Overwrites]
    role_overwrite_counts: Counter[int]
    member_map: dict[int, discord.Member] = field(default_factory=dict)
    skipped_member_overwrites: set[tuple[int, int]] = field(default_factory=set)
    skipped_role_ids: set[int] = field(default_factory=set)
    skipped_lookup_ids: set[int] = field(default_factory=set)
    uncategorized_ids: set[int] = field(default_factory=set)
    icon: bytes | None = None
    static_icon: bool = False
    preserve_icon: bool = False

    @property
    def updates_identity(self) -> bool:
        return self.settings.copy.server_name or not self.preserve_icon

    def role_omission(self, role_id: int) -> str:
        return t("issue.role_omission", count=self.role_overwrite_counts[role_id])


async def build_plan(
    source: discord.Guild,
    target: discord.Guild,
    log: IssueLog,
    settings: Settings = DEFAULT_SETTINGS,
) -> CopyPlan:
    """Check prerequisites and work out the copy without changing either server."""
    validate(source, target, settings)
    plan = _select_structure(source, target, settings)
    await _disclose_disabled_permissions(plan, log)
    await _enforce_role_capacity(plan, log)
    await _resolve_overwrites(plan, log)
    await _read_icon(plan, log)
    return plan


def _select_structure(source: discord.Guild, target: discord.Guild, settings: Settings) -> CopyPlan:
    kept = retained_role(target)
    roles = (
        [role for role in source.roles if not role.is_default() and not role.managed]
        if settings.copy.roles
        else []
    )
    role_names = {role.id: copy_role_name(role.name, role.id) for role in roles}
    source_channels = list(source.channels)
    supported = [channel for channel in source_channels if channel.type in COPYABLE_CHANNEL_TYPES]
    channels = sorted(
        (channel for channel in supported if _is_selected(channel, settings)),
        key=_DISPLAY_ORDER,
    )
    # ``overwrites`` rebuilds its mapping on every access, so read it once per channel here.
    overwrites = {channel.id: channel.overwrites for channel in channels}
    return CopyPlan(
        source=source,
        target=target,
        settings=settings,
        retained_role=kept,
        roles=roles,
        role_names=role_names,
        renamed_roles={
            role.id: role_names[role.id] for role in roles if role_names[role.id] != role.name
        },
        roles_to_delete=[
            role
            for role in target.roles
            if not role.is_default() and not role.managed and role != kept
        ]
        if settings.replace.roles
        else [],
        channels=channels,
        converted_channels=[
            channel for channel in channels if channel.type is discord.ChannelType.news
        ],
        skipped_channels=[
            channel for channel in source_channels if channel.type not in COPYABLE_CHANNEL_TYPES
        ],
        excluded_channels=len(supported) - len(channels),
        channels_to_delete=list(target.channels) if settings.replace.channels else [],
        overwrites=overwrites,
        role_overwrite_counts=Counter(
            subject.id for mapping in overwrites.values() for subject in mapping
        ),
        # A category the user chose not to copy leaves its children uncategorized, by design.
        uncategorized_ids={c.id for c in supported if is_category(c)}
        if not settings.copy.categories
        else set(),
    )


def _is_role_subject(subject: Any) -> bool:
    return isinstance(subject, discord.Role) or (
        isinstance(subject, discord.Object) and subject.type is discord.Role
    )


async def _disclose_disabled_permissions(plan: CopyPlan, log: IssueLog) -> None:
    """Settings can remove allow/deny rules, which widens access, so that still needs consent."""
    options = plan.settings.copy
    if not options.permission_overwrites:
        affected = sum(bool(mapping) for mapping in plan.overwrites.values())
        if affected:
            await log.accept(
                CopyIssue(
                    t("phase.check_options"),
                    t("issue.settings_overwrites_item", count=affected),
                    t("issue.settings_overwrites_reason"),
                    t("issue.settings_overwrites_consequence"),
                )
            )
        plan.overwrites = {channel_id: {} for channel_id in plan.overwrites}
        plan.role_overwrite_counts.clear()
        return
    if options.roles:
        return
    everyone = plan.source.default_role.id
    role_subjects = {
        channel_id: {s.id for s in mapping if _is_role_subject(s) and s.id != everyone}
        for channel_id, mapping in plan.overwrites.items()
    }
    affected = sum(bool(subjects) for subjects in role_subjects.values())
    if affected:
        await log.accept(
            CopyIssue(
                t("phase.check_options"),
                t("issue.settings_roles_item", count=affected),
                t("issue.settings_roles_reason"),
                t("issue.settings_roles_consequence"),
            )
        )
    plan.skipped_role_ids.update(*role_subjects.values())


async def _enforce_role_capacity(plan: CopyPlan, log: IssueLog) -> None:
    retained_roles = len(plan.target.roles) - len(plan.roles_to_delete)
    if retained_roles + len(plan.roles) <= MAX_ROLES:
        return
    capacity = max(0, MAX_ROLES - retained_roles)
    omitted = plan.roles[capacity:]
    names = t("list.separator").join(
        t("issue.capacity_item", name=role.name, id=role.id) for role in omitted
    )
    await log.accept(
        CopyIssue(
            t("phase.check_role_capacity"),
            names,
            t("issue.capacity_reason"),
            t("issue.capacity_consequence", capacity=capacity, omitted=len(omitted)),
        )
    )
    plan.skipped_role_ids.update(role.id for role in omitted)
    del plan.roles[capacity:]
    plan.renamed_roles = {
        key: name for key, name in plan.renamed_roles.items() if key not in plan.skipped_role_ids
    }


async def _resolve_overwrites(plan: CopyPlan, log: IssueLog) -> None:
    category_ids = {channel.id for channel in plan.channels if is_category(channel)}
    source_role_ids = {role.id for role in plan.roles} | {plan.source.default_role.id}
    missing_members: set[int] = set()
    for channel in plan.channels:
        await _check_parent_category(plan, log, channel, category_ids)
        for subject in plan.overwrites[channel.id]:
            if _is_role_subject(subject):
                await _check_role_subject(plan, log, channel, subject.id, source_role_ids)
            else:
                await _resolve_member_subject(plan, log, channel.id, subject.id, missing_members)


async def _check_parent_category(
    plan: CopyPlan, log: IssueLog, channel: Any, category_ids: set[int]
) -> None:
    parent_id = channel.category_id
    if parent_id is None or parent_id in category_ids or parent_id in plan.uncategorized_ids:
        return
    await log.accept(
        CopyIssue(
            t("phase.check_categories"),
            t("issue.category_item", id=parent_id),
            t("issue.category_reason", channel=channel.id),
            t("issue.category_consequence"),
        )
    )
    plan.uncategorized_ids.add(parent_id)


async def _check_role_subject(
    plan: CopyPlan, log: IssueLog, channel: Any, role_id: int, source_role_ids: set[int]
) -> None:
    if role_id in source_role_ids or role_id in plan.skipped_role_ids:
        return
    await log.accept(
        CopyIssue(
            t("phase.check_role_overwrites"),
            t("issue.role_overwrite_item", role=role_id, name=channel.name, channel=channel.id),
            t("issue.role_overwrite_reason"),
            plan.role_omission(role_id),
        )
    )
    plan.skipped_role_ids.add(role_id)


async def _resolve_member_subject(
    plan: CopyPlan, log: IssueLog, channel_id: int, member_id: int, missing: set[int]
) -> None:
    if member_id in plan.skipped_lookup_ids:
        return
    if member_id not in plan.member_map and member_id not in missing:
        member = plan.target.get_member(member_id) or await _fetch_member(
            plan, log, member_id, missing
        )
        if member is not None:
            plan.member_map[member_id] = member
    if member_id in missing:
        plan.skipped_member_overwrites.add((channel_id, member_id))


async def _fetch_member(
    plan: CopyPlan, log: IssueLog, member_id: int, missing: set[int]
) -> discord.Member | None:
    try:
        return await plan.target.fetch_member(member_id)
    except discord.HTTPException as error:
        if isinstance(error, discord.NotFound) and error.code == UNKNOWN_MEMBER:
            missing.add(member_id)
            return None
        if not log.can_recover or not can_skip_request(error):
            raise
        await log.accept(
            CopyIssue(
                t("phase.resolve_members"),
                t("issue.member_item", id=member_id),
                http_error_details(error),
                t("issue.member_consequence"),
            )
        )
        plan.skipped_lookup_ids.add(member_id)
        return None


async def _read_icon(plan: CopyPlan, log: IssueLog) -> None:
    if not plan.settings.copy.server_icon:
        plan.preserve_icon = True
        return
    icon = plan.source.icon
    if icon is None:
        return
    if icon.is_animated() and "ANIMATED_ICON" not in plan.target.features:
        plan.static_icon = True
        icon = icon.with_format("png")
    try:
        plan.icon = await icon.read()
    except (discord.HTTPException, OSError) as error:
        if not log.can_recover:
            raise
        if isinstance(error, discord.HTTPException) and not can_skip_request(error):
            raise
        await log.accept(
            CopyIssue(
                t("phase.read_icon"),
                plan.source.name,
                http_error_details(error)
                if isinstance(error, discord.HTTPException)
                else t("issue.icon_reason"),
                t("issue.icon_consequence"),
            )
        )
        plan.preserve_icon = True
