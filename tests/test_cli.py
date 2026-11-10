"""Arguments, token handling, startup cost, and the double-click flow."""

from __future__ import annotations

import argparse
import getpass
import io
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from clonex import __version__, cli, config
from clonex.core.models import ExitCode
from clonex.ui.terminal import TerminalUI
from clonex.ui.theme import THEME

SECRET = "mfa.not-a-real-token"


def make_ui() -> TerminalUI:
    return TerminalUI(
        Console(file=io.StringIO(), theme=THEME, width=96, force_terminal=False),
        Console(file=io.StringIO(), theme=THEME, width=96, force_terminal=False),
    )


def error_text(ui: TerminalUI) -> str:
    return ui.error_console.file.getvalue()  # type: ignore[attr-defined]


def scripted(ui: TerminalUI, monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    remaining = list(answers)

    def answer(*_args: object, **_kwargs: object) -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    monkeypatch.setattr(ui.console, "input", answer)


def namespace(**overrides: Any) -> argparse.Namespace:
    values = {"source": None, "target": None, "apply": False, "demo": False, "check": False}
    return argparse.Namespace(**{**values, **overrides})


@pytest.mark.parametrize("value", ["1", "123456789012345678", str(2**64 - 1)])
def test_valid_server_ids(value: str) -> None:
    assert cli.guild_id(value) == int(value)


@pytest.mark.parametrize("value", ["", "0", "-1", "12a", str(2**64), "1.5"])
def test_invalid_server_ids(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        cli.guild_id(value)


def test_server_ids_accept_any_decimal_script() -> None:
    assert cli.guild_id(" ١٢٣ ") == 123


def test_same_source_and_destination_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["--source", "1", "--target", "1"])
    assert caught.value.code == 2


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out.strip() == f"CloneX {__version__}"


def test_there_is_no_token_argument() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["--token", "x"])


def test_token_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config.TOKEN_VARIABLE, f"  {SECRET} ")
    assert cli.read_token(make_ui()) == SECRET


@pytest.mark.parametrize("bad", ["Bot abc", "two words", "   "])
def test_malformed_tokens_are_refused(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.delenv(config.TOKEN_VARIABLE, raising=False)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: bad)
    with pytest.raises(ValueError, match="without whitespace"):
        cli.read_token(make_ui())


def test_token_prompt_never_falls_back_to_visible_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(config.TOKEN_VARIABLE, raising=False)

    def echoing(_prompt: str) -> str:
        import warnings

        warnings.warn("cannot hide input", getpass.GetPassWarning, stacklevel=2)
        return "typed-in-the-clear"

    monkeypatch.setattr(getpass, "getpass", echoing)
    with pytest.raises(ValueError, match="Hidden input is unavailable"):
        cli.read_token(make_ui())


def test_a_typed_token_is_not_displayed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(config.TOKEN_VARIABLE, raising=False)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: SECRET)
    ui = make_ui()
    assert cli.read_token(ui) == SECRET
    assert SECRET not in ui.console.file.getvalue()  # type: ignore[attr-defined]


@pytest.mark.parametrize("flags", [["--help"], ["--version"], ["--demo"]])
def test_quick_commands_do_not_import_discord(flags: list[str]) -> None:
    code = (
        "import sys\n"
        "from clonex import cli\n"
        f"try:\n    cli.main({flags!r})\nexcept SystemExit:\n    pass\n"
        "sys.exit('discord' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_check_loads_the_full_runtime(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.run_check() is ExitCode.OK
    assert "Installation OK" in capsys.readouterr().out


def test_menu_exit_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    ui = make_ui()
    scripted(ui, monkeypatch, "3")
    assert cli._run(namespace(), config.Settings(), ui, show_menu=True) is ExitCode.OK


@pytest.mark.parametrize(("choice", "apply"), [("1", False), ("2", True)])
def test_menu_selects_the_mode(monkeypatch: pytest.MonkeyPatch, choice: str, apply: bool) -> None:
    from clonex import session

    seen: dict[str, Any] = {}

    def fake_run(
        token: str, source: int, target: int, *, apply: bool, ui: Any, settings: Any
    ) -> ExitCode:
        seen.update(token=token, source=source, target=target, apply=apply)
        return ExitCode.OK

    monkeypatch.setattr(session, "run", fake_run)
    monkeypatch.setenv(config.TOKEN_VARIABLE, SECRET)
    ui = make_ui()
    scripted(ui, monkeypatch, choice, "11", "22")
    assert cli._run(namespace(), config.Settings(), ui, show_menu=True) is ExitCode.OK
    assert seen == {"token": SECRET, "source": 11, "target": 22, "apply": apply}


def test_invalid_id_at_the_prompt_is_a_clean_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    ui = make_ui()
    scripted(ui, monkeypatch, "not-a-number")
    assert cli._run(namespace(), config.Settings(), ui, show_menu=False) is ExitCode.FAILED
    assert "positive decimal" in error_text(ui)


def test_identical_ids_at_the_prompt_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    ui = make_ui()
    scripted(ui, monkeypatch, "5", "5")
    assert cli._run(namespace(), config.Settings(), ui, show_menu=False) is ExitCode.FAILED
    assert "different servers" in error_text(ui)


def test_closed_input_reports_an_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    ui = make_ui()
    scripted(ui, monkeypatch)
    assert cli._run(namespace(), config.Settings(), ui, show_menu=False) is ExitCode.INTERRUPTED


def test_unexpected_errors_never_print_their_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from clonex import session

    def explode(*_args: object, **_kwargs: object) -> ExitCode:
        raise RuntimeError(f"leaked {SECRET}")

    monkeypatch.setattr(session, "run", explode)
    monkeypatch.setenv(config.TOKEN_VARIABLE, SECRET)
    ui = make_ui()
    assert (
        cli._run(namespace(source=1, target=2), config.Settings(), ui, show_menu=False)
        is ExitCode.FAILED
    )
    assert SECRET not in error_text(ui)
    assert "RuntimeError" in error_text(ui)


def test_output_survives_a_legacy_code_page(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    cli.use_utf8_output()
    stream.write("日本語 🎉")
    stream.flush()
