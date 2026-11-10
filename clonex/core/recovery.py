"""Explicit, item-scoped recovery decisions shared by planning and execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

from clonex.core.errors import CloneCancelled, CloneError
from clonex.core.models import CopyIssue
from clonex.i18n import t

Decider = Callable[[CopyIssue], Awaitable[bool]]

_SKIPPABLE_STATUSES = frozenset({400, 403, 404, 413})
# Account, session and server-access failures. Continuing past these would only repeat them.
_FATAL_CODES = frozenset(
    {10001, 10004, 10012, 10020, 20026, 40001, 40002, 40003, 50001, 50014, 50025, 60003}
)


def can_skip_request(error: discord.HTTPException) -> bool:
    """Only definite item rejections; never replay an uncertain write or bypass login."""
    return (
        error.status in _SKIPPABLE_STATUSES
        and error.code not in _FATAL_CODES
        and not isinstance(error, discord.CaptchaRequired)
    )


class IssueLog:
    """The omissions the user has accepted. Nothing is recorded without a decision."""

    def __init__(self, decide: Decider | None = None) -> None:
        self._decide = decide
        self.issues: list[CopyIssue] = []

    @property
    def can_recover(self) -> bool:
        return self._decide is not None

    async def accept(self, issue: CopyIssue) -> None:
        """Record ``issue`` if the user agrees; otherwise end the copy."""
        if self._decide is None:
            raise CloneError(f"{issue.item}: {issue.reason} {issue.consequence}")
        if not await self._decide(issue):
            raise CloneCancelled(t("error.stopped_at", phase=issue.phase, item=issue.item))
        self.issues.append(issue)
