"""The Discord connection: signs in, then plans and runs a single copy."""

from __future__ import annotations

import asyncio
import logging

import discord

from clonex.config import Settings
from clonex.core.discord_errors import http_error_message
from clonex.core.errors import CloneCancelled, CloneError
from clonex.core.executor import Executor
from clonex.core.models import CopyIssue, CopySummary, ExitCode
from clonex.core.plan import build_plan
from clonex.core.recovery import IssueLog
from clonex.i18n import normalize_digits, t
from clonex.ui.terminal import TerminalUI

# Without a handler the library's rate-limit warnings go to stderr through the live panel.
logging.getLogger("discord").addHandler(logging.NullHandler())


class CloneClient(discord.Client):
    def __init__(
        self, source_id: int, target_id: int, *, apply: bool, ui: TerminalUI, settings: Settings
    ) -> None:
        super().__init__(chunk_guilds_at_startup=False, guild_subscriptions=False)
        self.source_id = source_id
        self.target_id = target_id
        self.apply = apply
        self.ui = ui
        self.clone_settings = settings
        self.started = False
        self.copy_started = False
        self.exit_code = ExitCode.FAILED
        self.log = IssueLog(self._recover)

    async def _recover(self, issue: CopyIssue) -> bool:
        """Preview mode lists omissions without asking; copy mode needs a decision for each."""
        if not self.apply:
            return True
        return await asyncio.to_thread(self.ui.confirm_recovery, issue)

    async def on_ready(self) -> None:
        # READY can fire again after a gateway reset; the copy must never run twice.
        if self.started:
            return
        self.started = True
        ui = self.ui
        try:
            self.exit_code = await self._clone()
        except CloneCancelled as error:
            state = t("session.partial") if self.copy_started else t("session.no_changes")
            ui.cancelled(f"{error} {state}")
            self.exit_code = ExitCode.DECLINED
        except CloneError as error:
            ui.error(str(error))
        except discord.HTTPException as error:
            ui.error(http_error_message(error, copy_started=self.copy_started))
        except EOFError:
            ui.cancelled(
                t("session.input_ended_partial")
                if self.copy_started
                else t("session.input_ended_none")
            )
            self.exit_code = ExitCode.INTERRUPTED
        except OSError:
            ui.error(t("session.io_failed"))
        except Exception as error:
            ui.error(t("session.unexpected", name=type(error).__name__))
        finally:
            try:
                if self.exit_code not in {ExitCode.OK, ExitCode.WARNINGS}:
                    ui.recovery_notes(tuple(self.log.issues))
            finally:
                await self.close()

    async def _clone(self) -> ExitCode:
        ui = self.ui
        source = self.get_guild(self.source_id)
        target = self.get_guild(self.target_id)
        if source is None or target is None:
            raise CloneError(t("session.not_member"))
        with ui.busy(t("session.checking")):
            plan = await build_plan(source, target, self.log, self.clone_settings)
        preview = CopySummary.from_plan(plan, self.log)
        ui.preview(preview)
        if not self.apply:
            ui.preview_complete()
            return ExitCode.OK
        confirmation = await asyncio.to_thread(ui.confirm, target.id, preview.deletes_anything)
        if normalize_digits(confirmation.strip()) != str(target.id):
            ui.cancelled()
            return ExitCode.DECLINED
        executor = Executor(plan, self.log, report=ui.report, report_skip=ui.report_skip)
        with ui.copying(executor.operation_count):
            self.copy_started = True
            await executor.run()
        result = CopySummary.from_executor(executor)
        ui.completed(result)
        return ExitCode.WARNINGS if result.has_omissions else ExitCode.OK


async def _connect(
    token: str, source_id: int, target_id: int, *, apply: bool, ui: TerminalUI, settings: Settings
) -> ExitCode:
    async with CloneClient(source_id, target_id, apply=apply, ui=ui, settings=settings) as client:
        try:
            await client.start(token, reconnect=False)
        except (discord.DiscordException, OSError) as error:
            if not client.copy_started or isinstance(error, discord.LoginFailure):
                raise
            ui.error(t("session.connection_lost", name=type(error).__name__))
            return ExitCode.FAILED
        return client.exit_code


def run(
    token: str, source_id: int, target_id: int, *, apply: bool, ui: TerminalUI, settings: Settings
) -> ExitCode:
    """Connect and run one preview or copy, translating connection failures to an exit code."""
    try:
        return asyncio.run(
            _connect(token, source_id, target_id, apply=apply, ui=ui, settings=settings)
        )
    except discord.LoginFailure:
        ui.error(t("session.login_failed"))
    except (discord.DiscordException, OSError) as error:
        ui.error(t("session.connection_failed", name=type(error).__name__))
    return ExitCode.FAILED
