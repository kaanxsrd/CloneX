"""Plain data shared by the core and the terminal UI.

The UI imports this module, so it must not import ``discord`` at runtime: that import alone
costs over half a second, and ``--help``, ``--version`` and ``--demo`` never need it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clonex.core.executor import Executor
    from clonex.core.plan import CopyPlan
    from clonex.core.recovery import IssueLog


class ExitCode(IntEnum):
    OK = 0
    FAILED = 1
    DECLINED = 2
    WARNINGS = 3
    INTERRUPTED = 130


@dataclass(frozen=True, slots=True)
class CopyIssue:
    phase: str
    item: str
    reason: str
    consequence: str


@dataclass(frozen=True, slots=True)
class CopySummary:
    source_name: str
    source_id: int
    target_name: str
    target_id: int
    roles: int
    categories: int
    text_channels: int
    voice_channels: int
    delete_channels: int
    delete_roles: int
    retained_role: str | None = None
    limited_bitrates: int = 0
    static_icon: bool = False
    skipped_member_overwrites: int = 0
    skipped_member_channels: int = 0
    renamed_roles: tuple[tuple[int, str], ...] = ()
    converted_channels: tuple[tuple[int, str, str], ...] = ()
    skipped_channels: tuple[tuple[int, str, str], ...] = ()
    issues: tuple[CopyIssue, ...] = ()
    skipped_steps: int = 0
    excluded_channels: int = 0
    replaces_name: bool = True
    replaces_icon: bool = True
    replaces_everyone: bool = True

    @property
    def has_omissions(self) -> bool:
        return bool(self.issues or self.skipped_channels or self.skipped_member_overwrites)

    @property
    def deletes_anything(self) -> bool:
        return bool(self.delete_channels or self.delete_roles)

    @classmethod
    def from_plan(cls, plan: CopyPlan, log: IssueLog) -> CopySummary:
        """Describe what the copy is going to do."""
        return cls._build(plan, log, None)

    @classmethod
    def from_executor(cls, executor: Executor) -> CopySummary:
        """Describe what the copy actually did."""
        return cls._build(executor.plan, executor.log, executor)

    @classmethod
    def _build(cls, plan: CopyPlan, log: IssueLog, executor: Executor | None) -> CopySummary:
        channels = (
            [source for source, _ in executor.created_channels] if executor else plan.channels
        )
        counts = Counter(channel.type.name for channel in channels)
        created_ids = {channel.id for channel in channels}
        source, target = plan.source, plan.target
        options = plan.settings.copy
        return cls(
            source_name=source.name,
            source_id=source.id,
            target_name=target.name,
            target_id=target.id,
            roles=executor.created_role_count if executor else len(plan.roles),
            categories=len(executor.category_map) if executor else counts["category"],
            text_channels=counts["text"] + counts["news"],
            voice_channels=counts["voice"],
            delete_channels=len(plan.channels_to_delete),
            delete_roles=len(plan.roles_to_delete),
            retained_role=plan.retained_role.name if plan.retained_role is not None else None,
            limited_bitrates=sum(
                channel.type.name == "voice" and channel.bitrate > target.bitrate_limit
                for channel in plan.channels
            ),
            static_icon=plan.static_icon and not plan.preserve_icon,
            skipped_member_overwrites=len(plan.skipped_member_overwrites),
            skipped_member_channels=len(
                {channel_id for channel_id, _ in plan.skipped_member_overwrites}
            ),
            renamed_roles=tuple(
                (identifier, name)
                for identifier, name in plan.renamed_roles.items()
                if not executor or identifier not in plan.skipped_role_ids
            ),
            converted_channels=tuple(
                (channel.id, channel.name, str(channel.type))
                for channel in plan.converted_channels
                if not executor or channel.id in created_ids
            ),
            skipped_channels=tuple(
                (channel.id, channel.name, str(channel.type)) for channel in plan.skipped_channels
            ),
            issues=tuple(log.issues),
            skipped_steps=executor.skipped_steps if executor else 0,
            excluded_channels=plan.excluded_channels,
            replaces_name=options.server_name,
            replaces_icon=not plan.preserve_icon,
            replaces_everyone=options.everyone_permissions,
        )
