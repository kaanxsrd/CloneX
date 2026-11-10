"""Applies a prepared plan to the destination, one sequential request at a time."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar

import discord

from clonex.core.discord_errors import http_error_details, is_name_length_error
from clonex.core.errors import CloneError
from clonex.core.models import CopyIssue
from clonex.core.plan import TEXT_CHANNEL_TYPES, CopyPlan, is_category, validate
from clonex.core.recovery import IssueLog, can_skip_request
from clonex.i18n import t

_SKIPPED: Any = object()

T = TypeVar("T")
Report = Callable[[str, str, bool], None]
ReportSkip = Callable[[str, str], None]


def _is_voice(channel: Any) -> bool:
    return channel.type is discord.ChannelType.voice


def _is_text(channel: Any) -> bool:
    return channel.type in TEXT_CHANNEL_TYPES


def _needs_voice_slowmode(channel: Any) -> bool:
    """``create_voice_channel`` cannot set slowmode, so a non-zero value costs one extra edit."""
    return _is_voice(channel) and channel.slowmode_delay > 0


class Executor:
    def __init__(
        self,
        plan: CopyPlan,
        log: IssueLog,
        *,
        report: Report | None = None,
        report_skip: ReportSkip | None = None,
    ) -> None:
        self.plan = plan
        self.log = log
        self._report = report
        self._report_skip = report_skip
        self._reason = plan.settings.audit_reason
        self._executed = False
        self.role_map: dict[int, discord.Role] = {
            plan.source.default_role.id: plan.target.default_role
        }
        self.category_map: dict[int, discord.CategoryChannel] = {}
        self.created_channels: list[tuple[Any, Any]] = []
        self.created_role_count = 0
        self.skipped_steps = 0
        # Discord orders each of these kinds independently, so each needs one bulk request.
        self._order_groups = [
            group
            for group in (
                ("phase.restore_category_order", "order.categories", is_category),
                ("phase.restore_channel_order", "order.text", _is_text),
                ("phase.restore_channel_order", "order.voice", _is_voice),
            )
            if any(group[2](channel) for channel in plan.channels)
        ]

    @property
    def operation_count(self) -> int:
        """Progress steps in a full run; every step is later reported as done or skipped."""
        plan = self.plan
        return (
            len(plan.channels_to_delete)
            + len(plan.roles_to_delete)
            + plan.settings.copy.everyone_permissions
            + len(plan.roles)
            + bool(plan.roles)
            + len(plan.channels)
            + sum(map(_needs_voice_slowmode, plan.channels))
            + len(self._order_groups)
            + plan.updates_identity
        )

    async def run(self) -> None:
        if self._executed:
            raise CloneError(t("error.execute_once"))
        validate(self.plan.source, self.plan.target, self.plan.settings)
        self._executed = True
        await self._remove_channels()
        await self._remove_roles()
        await self._update_default_role()
        await self._create_roles()
        await self._restore_role_order()
        await self._create_categories()
        await self._create_channels()
        await self._restore_channel_order()
        await self._update_identity()

    async def _step(self, operation: Awaitable[T], phase: str, item: str) -> T:
        if self._report is not None:
            self._report(phase, item, False)
        result = await operation
        if self._report is not None:
            self._report(phase, item, True)
        return result

    def _skip_step(self, phase: str, item: str) -> None:
        self.skipped_steps += 1
        if self._report_skip is not None:
            self._report_skip(phase, item)

    async def _recover_step(
        self, operation: Awaitable[T], phase: str, item: str, consequence: str
    ) -> T:
        """Await ``operation``; on a skippable rejection ask the user, then return ``_SKIPPED``."""
        try:
            return await operation
        except discord.HTTPException as error:
            if not self.log.can_recover or not can_skip_request(error):
                raise
            validate(self.plan.source, self.plan.target, self.plan.settings)
            await self.log.accept(CopyIssue(phase, item, http_error_details(error), consequence))
            self._skip_step(phase, item)
            return _SKIPPED

    async def _run_step(
        self, operation: Awaitable[T], phase: str, item: str, consequence: str
    ) -> T:
        return await self._recover_step(
            self._step(operation, phase, item), phase, item, consequence
        )

    async def _map_overwrites(self, channel: Any) -> dict[Any, discord.PermissionOverwrite]:
        plan = self.plan
        mapped = {}
        for subject, permissions in plan.overwrites[channel.id].items():
            if (
                (channel.id, subject.id) in plan.skipped_member_overwrites
                or subject.id in plan.skipped_role_ids
                or subject.id in plan.skipped_lookup_ids
            ):
                continue
            target = self.role_map.get(subject.id) or plan.member_map.get(subject.id)
            if target is None:
                # Never drop a permission rule without a decision: it can widen channel access.
                await self.log.accept(
                    CopyIssue(
                        t("phase.map_permissions"),
                        t(
                            "issue.mapping_item",
                            name=channel.name,
                            id=channel.id,
                            overwrite=subject.id,
                        ),
                        t("issue.mapping_reason"),
                        t("issue.mapping_consequence"),
                    )
                )
                continue
            mapped[target] = permissions
        return mapped

    async def _remove_channels(self) -> None:
        # Categories go last so their children never need re-parenting by Discord.
        for channel in sorted(self.plan.channels_to_delete, key=is_category):
            await self._run_step(
                channel.delete(reason=self._reason),
                t("phase.remove_channels"),
                channel.name,
                t("issue.remove_channel"),
            )

    async def _remove_roles(self) -> None:
        for role in reversed(self.plan.roles_to_delete):
            await self._run_step(
                role.delete(reason=self._reason),
                t("phase.remove_roles"),
                role.name,
                t("issue.remove_role"),
            )

    async def _update_default_role(self) -> None:
        if not self.plan.settings.copy.everyone_permissions:
            return
        source_role = self.plan.source.default_role
        updated = await self._run_step(
            self.plan.target.default_role.edit(
                permissions=source_role.permissions, reason=self._reason
            ),
            t("phase.update_everyone"),
            "@everyone",
            t("issue.everyone"),
        )
        if isinstance(updated, discord.Role):
            self.role_map[source_role.id] = updated

    async def _create_role(self, role: discord.Role) -> discord.Role:
        plan = self.plan
        options: dict[str, Any] = {
            "permissions": role.permissions,
            "colour": role.colour,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "reason": self._reason,
        }
        name = plan.role_names[role.id]
        phase = t("phase.create_roles")
        try:
            return await self._step(plan.target.create_role(name=name, **options), phase, name)
        except discord.HTTPException as error:
            fallback = f"Role {role.id}"
            if not is_name_length_error(error) or name == fallback:
                raise
            plan.role_names[role.id] = fallback
            plan.renamed_roles[role.id] = fallback
            return await self._step(
                plan.target.create_role(name=fallback, **options), phase, fallback
            )

    async def _create_roles(self) -> None:
        plan = self.plan
        for role in plan.roles:
            created = await self._recover_step(
                self._create_role(role),
                t("phase.create_roles"),
                f"{role.name} (ID {role.id})",
                plan.role_omission(role.id),
            )
            if created is _SKIPPED:
                plan.skipped_role_ids.add(role.id)
            else:
                self.role_map[role.id] = created
                self.created_role_count += 1

    async def _restore_role_order(self) -> None:
        plan = self.plan
        if not plan.roles:
            return
        phase = t("phase.restore_role_order")
        created = [self.role_map[role.id] for role in plan.roles if role.id in self.role_map]
        if not created:
            self._skip_step(phase, t("order.item", label=t("order.roles"), count=0))
            return
        await self._run_step(
            plan.target.edit_role_positions(
                positions={role: index for index, role in enumerate(created, 1)},
                reason=self._reason,
            ),
            phase,
            t("order.item", label=t("order.roles"), count=len(created)),
            t("issue.role_order"),
        )

    async def _create_categories(self) -> None:
        plan = self.plan
        for channel in filter(is_category, plan.channels):
            created = await self._run_step(
                plan.target.create_category(
                    channel.name,
                    overwrites=await self._map_overwrites(channel),
                    reason=self._reason,
                ),
                t("phase.create_categories"),
                channel.name,
                t("issue.create_category"),
            )
            if created is _SKIPPED:
                plan.uncategorized_ids.add(channel.id)
            else:
                self.category_map[channel.id] = created

    async def _parent_category(self, channel: Any) -> discord.CategoryChannel | None:
        plan = self.plan
        parent = self.category_map.get(channel.category_id)
        if (
            parent is None
            and channel.category_id is not None
            and channel.category_id not in plan.uncategorized_ids
        ):
            await self.log.accept(
                CopyIssue(
                    t("phase.map_categories"),
                    t("issue.parent_category_item", name=channel.name, id=channel.id),
                    t("issue.parent_category_reason", category=channel.category_id),
                    t("issue.parent_category_consequence"),
                )
            )
            plan.uncategorized_ids.add(channel.category_id)
        return parent

    def _text_channel_request(self, channel: Any, options: dict[str, Any]) -> Awaitable[Any]:
        return self.plan.target.create_text_channel(
            **options,
            news=False,
            slowmode_delay=channel.slowmode_delay,
            topic=channel.topic,
            default_auto_archive_duration=channel.default_auto_archive_duration,
            default_thread_slowmode_delay=channel.default_thread_slowmode_delay,
        )

    def _voice_channel_request(self, channel: Any, options: dict[str, Any]) -> Awaitable[Any]:
        target = self.plan.target
        return target.create_voice_channel(
            **options,
            bitrate=min(channel.bitrate, int(target.bitrate_limit)),
            user_limit=channel.user_limit,
            rtc_region=channel.rtc_region,
            video_quality_mode=channel.video_quality_mode,
        )

    async def _create_channels(self) -> None:
        for channel in self.plan.channels:
            if is_category(channel):
                continue
            options = {
                "name": channel.name,
                "category": await self._parent_category(channel),
                "overwrites": await self._map_overwrites(channel),
                "reason": self._reason,
                "nsfw": channel.nsfw,
            }
            if _is_text(channel):
                request, phase = self._text_channel_request(channel, options), "phase.create_text"
            else:
                request, phase = self._voice_channel_request(channel, options), "phase.create_voice"
            created = await self._run_step(
                request, t(phase), channel.name, t("issue.create_channel")
            )
            if created is not _SKIPPED:
                self.created_channels.append((channel, created))
            if not _needs_voice_slowmode(channel):
                continue
            if created is _SKIPPED:
                self._skip_step(t("phase.voice_slowmode"), channel.name)
            else:
                await self._run_step(
                    created.edit(slowmode_delay=channel.slowmode_delay, reason=self._reason),
                    t("phase.voice_slowmode"),
                    channel.name,
                    t("issue.voice_slowmode"),
                )

    def _bulk_position_update(self, created: Iterable[Any]) -> Awaitable[None]:
        """Send one list of positions.

        ``channel.edit(position=...)`` re-sends the whole channel list on this same heavily
        rate-limited route for each channel it moves, and the library has no public bulk
        method, so this private call replaces one request per channel with one per kind.
        """
        target = self.plan.target
        payload: list[Any] = [
            {"id": channel.id, "position": index} for index, channel in enumerate(created)
        ]
        return target._state.http.bulk_channel_update(target.id, payload, reason=self._reason)

    async def _restore_channel_order(self) -> None:
        created: dict[int, Any] = {source.id: new for source, new in self.created_channels}
        created.update(self.category_map)
        for phase_key, label_key, belongs in self._order_groups:
            ordered = [
                created[channel.id]
                for channel in self.plan.channels
                if belongs(channel) and channel.id in created
            ]
            item = t("order.item", label=t(label_key), count=len(ordered))
            if not ordered:
                self._skip_step(t(phase_key), item)
                continue
            await self._run_step(
                self._bulk_position_update(ordered), t(phase_key), item, t("issue.channel_order")
            )

    async def _update_identity(self) -> None:
        plan = self.plan
        if not plan.updates_identity:
            return
        identity: dict[str, Any] = {"reason": self._reason}
        if plan.settings.copy.server_name:
            identity["name"] = plan.source.name
        if not plan.preserve_icon:
            identity["icon"] = plan.icon
        await self._run_step(
            plan.target.edit(**identity),
            t("phase.update_identity"),
            plan.source.name,
            t("issue.identity"),
        )
