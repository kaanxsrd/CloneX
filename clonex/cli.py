"""Command-line entry point for CloneX.

Rich and discord.py-self are imported inside the functions that need them, so ``--help`` and
``--version`` start immediately and only a real connection pays for the Discord import.
"""

from __future__ import annotations

import argparse
import getpass
import os
import platform
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from clonex import APP_NAME, __version__, config, i18n
from clonex.core.models import ExitCode
from clonex.i18n import t

if TYPE_CHECKING:
    from clonex.ui.terminal import TerminalUI


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def program_name() -> str:
    name = Path(sys.argv[0]).stem
    return "python -m clonex" if name in {"__main__", ""} else name


def guild_id(value: str) -> int:
    """Parse a positive Discord snowflake, in the decimal digits of any script."""
    digits = i18n.normalize_digits(value.strip())
    if not digits.isascii() or not digits.isdecimal() or not 0 < int(digits) < 2**64:
        raise argparse.ArgumentTypeError(t("error.invalid_id"))
    return int(digits)


def _early_arguments(argv: Sequence[str]) -> argparse.Namespace:
    """Read what decides the language, so that ``--help`` itself can be translated."""
    early = argparse.ArgumentParser(add_help=False)
    early.add_argument("--lang")
    early.add_argument("--config")
    early.add_argument("--set", action="append", default=[])
    return early.parse_known_args(argv)[0]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=program_name(), description=t("cli.description"), allow_abbrev=False
    )
    add = parser.add_argument
    add(
        "--version",
        action="version",
        version=f"{APP_NAME} {__version__}",
        help=t("cli.help.version"),
    )
    add("--source", type=guild_id, help=t("cli.help.source"))
    add("--target", type=guild_id, help=t("cli.help.target"))
    add("--apply", action="store_true", help=t("cli.help.apply"))
    add("--demo", action="store_true", help=t("cli.help.demo"))
    add("--check", action="store_true", help=t("cli.help.check"))
    add("--lang", metavar="CODE", help=t("cli.help.lang"))
    add("--config", metavar="PATH", help=t("cli.help.config"))
    add("--set", metavar="KEY=VALUE", action="append", default=[], help=t("cli.help.set"))
    add("--init-config", metavar="PATH", nargs="?", const="", help=t("cli.help.init_config"))
    add("--show-config", action="store_true", help=t("cli.help.show_config"))
    add("--list-languages", action="store_true", help=t("cli.help.list_languages"))
    args = parser.parse_args(argv)
    if args.source is not None and args.source == args.target:
        parser.error(t("error.same_server"))
    return args


def read_token(ui: TerminalUI) -> str:
    token = os.environ.get(config.TOKEN_VARIABLE, "").strip()
    if not token:
        ui.token_notice()
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                token = getpass.getpass("  > ").strip()
            except getpass.GetPassWarning as error:
                raise ValueError(t("error.hidden_input", variable=config.TOKEN_VARIABLE)) from error
    if not token or any(character.isspace() for character in token):
        raise ValueError(t("error.bad_token"))
    return token


def use_utf8_output() -> None:
    """Server names can hold any character; a legacy code page must not crash a running copy."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def run_check() -> ExitCode:
    """Load the dependencies that ``--help`` and ``--demo`` deliberately skip."""
    try:
        import curl_cffi
        import discord

        import clonex.session  # noqa: F401
    except ImportError as error:
        print(t("check.failed", error=error), file=sys.stderr)
        return ExitCode.FAILED
    build = "packaged executable" if is_packaged() else "source"
    print(f"{APP_NAME} {__version__} ({build})")
    print(f"Python {platform.python_version()} on {platform.platform()}")
    print(f"discord.py-self {discord.__version__}")
    print(f"curl_cffi {curl_cffi.__version__} (curl {curl_cffi.__curl_version__})")
    print(f"Language: {i18n.active_language()}")
    print(t("check.ok"))
    return ExitCode.OK


def show_settings(loaded: config.LoadedSettings) -> ExitCode:
    print(t("config.using", path=loaded.path) if loaded.path else t("config.none"))
    for key, value in config.flat_settings(loaded.settings).items():
        print(f"{key} = {value}")
    return ExitCode.OK


def list_languages() -> ExitCode:
    for language in i18n.available_languages():
        print(f"{language.code:8} {language.name} ({language.english_name})")
    return ExitCode.OK


def init_config(destination: str) -> ExitCode:
    path = config.write_template(Path(destination) if destination else config.user_config_path())
    print(t("config.created", path=path))
    return ExitCode.OK


def build_ui(settings: config.Settings) -> TerminalUI:
    from rich.console import Console

    from clonex.ui.terminal import TerminalUI
    from clonex.ui.theme import THEME

    def console(*, stderr: bool = False) -> Console:
        return Console(
            theme=THEME,
            highlight=False,
            stderr=stderr,
            no_color=True if settings.ui.color == "never" else None,
            force_terminal=True if settings.ui.color == "always" else None,
        )

    return TerminalUI(console(), console(stderr=True), max_listed=settings.ui.max_listed)


def _run(
    args: argparse.Namespace, settings: config.Settings, ui: TerminalUI, *, show_menu: bool
) -> ExitCode:
    try:
        if args.demo:
            from clonex.ui.demo import demo

            demo(ui)
            return ExitCode.OK
        apply = args.apply
        if show_menu:
            mode = ui.choose_mode()
            if mode == "exit":
                return ExitCode.OK
            apply = mode == "copy"
        ui.banner(apply=apply)
        source_id = (
            args.source
            or settings.source
            or guild_id(ui.prompt(t("prompt.source"), hint=t("prompt.source_hint")))
        )
        target_id = (
            args.target
            or settings.target
            or guild_id(ui.prompt(t("prompt.target"), hint=t("prompt.target_hint")))
        )
        if source_id == target_id:
            raise ValueError(t("error.same_server"))
        token = read_token(ui)
        ui.console.print()
        ui.note(t("note.connecting"))

        from clonex import session

        return session.run(token, source_id, target_id, apply=apply, ui=ui, settings=settings)
    except (ValueError, argparse.ArgumentTypeError) as error:
        ui.error(str(error))
    except (EOFError, KeyboardInterrupt):
        ui.cancelled(t("error.interrupted"))
        return ExitCode.INTERRUPTED
    except Exception as error:
        # The type name only: exception text can quote request data.
        ui.error(t("error.unexpected", name=type(error).__name__))
    return ExitCode.FAILED


def _report(error: config.ConfigError) -> ExitCode:
    print(i18n.error_text(error), file=sys.stderr)
    return ExitCode.FAILED


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    use_utf8_output()
    early = _early_arguments(arguments)
    # A broken settings file must not stop --help or --version, so it is reported afterwards.
    problem: config.ConfigError | None = None
    loaded = config.LoadedSettings(config.Settings(), None)
    try:
        loaded = config.load_settings(early.config, early.set)
        i18n.activate(early.lang or loaded.settings.language)
    except config.ConfigError as error:
        problem = error
        i18n.activate()
    args = parse_args(arguments)
    if problem is not None and args.init_config is None:
        return _report(problem)
    try:
        if args.init_config is not None:
            return init_config(args.init_config)
    except config.ConfigError as error:
        return _report(error)
    if args.show_config:
        return show_settings(loaded)
    if args.list_languages:
        return list_languages()
    if args.check:
        return run_check()

    ui = build_ui(loaded.settings)
    started_bare = not arguments and sys.stdin.isatty()
    try:
        return _run(args, loaded.settings, ui, show_menu=started_bare)
    finally:
        if started_bare and sys.platform == "win32":
            ui.pause()
