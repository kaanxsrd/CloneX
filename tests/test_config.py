"""Settings: where they come from, how they are validated, and what they refuse."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from clonex import cli, config, i18n
from clonex.config import ConfigError, Settings


def write(folder: Path, text: str, name: str = "clonex.toml") -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_with_no_file() -> None:
    loaded = config.load_settings(environ={})
    assert loaded.settings == Settings()
    assert loaded.path is None


def test_a_local_file_is_found_and_applied(tmp_path: Path) -> None:
    path = write(tmp_path, '[copy]\nroles = false\n[ui]\ncolor = "never"\nmax_listed = 3\n')
    loaded = config.load_settings(environ={})
    assert loaded.path == path
    assert loaded.settings.copy.roles is False
    assert (loaded.settings.ui.color, loaded.settings.ui.max_listed) == ("never", 3)
    assert loaded.settings.copy.categories is True


def test_the_local_file_beats_the_user_file(tmp_path: Path) -> None:
    config.user_config_path().parent.mkdir(parents=True)
    config.user_config_path().write_text('language = "de"\n', encoding="utf-8")
    assert config.load_settings(environ={}).settings.language == "de"
    write(tmp_path, 'language = "fr"\n')
    assert config.load_settings(environ={}).settings.language == "fr"


def test_explicit_path_and_environment_variable(tmp_path: Path) -> None:
    other = write(tmp_path, 'language = "ja"\n', "other.toml")
    assert config.load_settings(str(other), environ={}).settings.language == "ja"
    loaded = config.load_settings(environ={config.CONFIG_VARIABLE: str(other)})
    assert loaded.settings.language == "ja"


def test_a_named_file_that_is_missing_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as caught:
        config.load_settings(str(tmp_path / "absent.toml"), environ={})
    assert caught.value.key == "config.error.missing"


def test_priority_override_beats_environment_beats_file(tmp_path: Path) -> None:
    write(tmp_path, 'language = "de"\n')
    environ = {config.LANGUAGE_VARIABLE: "fr"}
    assert config.load_settings(environ=environ).settings.language == "fr"
    result = config.load_settings(overrides=["language=ko"], environ=environ)
    assert result.settings.language == "ko"


@pytest.mark.parametrize(
    ("override", "key", "expected"),
    [
        ("copy.roles=false", "copy.roles", False),
        ("ui.max_listed=3", "ui.max_listed", 3),
        ("language=tr", "language", "tr"),
        ('audit_reason="Moving house"', "audit_reason", "Moving house"),
        ("source=111111111111111111", "source", 111111111111111111),
    ],
)
def test_overrides_keep_their_types(override: str, key: str, expected: object) -> None:
    settings = config.load_settings(overrides=[override], environ={}).settings
    assert config.flat_settings(settings)[key] == expected


@pytest.mark.parametrize(
    ("text", "error_key"),
    [
        ("copy.rolez = true\n", "config.error.unknown"),
        ("[copy]\nroles = 1\n", "config.error.type"),
        ('[ui]\ncolor = "blue"\n', "config.error.choice"),
        ("[ui]\nmax_listed = 0\n", "config.error.type"),
        ("[ui]\nmax_listed = true\n", "config.error.type"),
        ('audit_reason = ""\n', "config.error.type"),
        (f'audit_reason = "{"x" * 513}"\n', "config.error.type"),
        ("source = -4\n", "config.error.type"),
        ("source = true\n", "config.error.type"),
        ("not valid toml", "config.error.invalid"),
    ],
)
def test_invalid_settings_are_rejected(tmp_path: Path, text: str, error_key: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError) as caught:
        config.load_settings(environ={})
    assert caught.value.key == error_key
    assert i18n.error_text(caught.value), "every error must render"


@pytest.mark.parametrize("text", ['token = "abc"\n', '[discord]\ntoken = "abc"\n'])
def test_tokens_can_never_live_in_a_settings_file(tmp_path: Path, text: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError) as caught:
        config.load_settings(environ={})
    assert caught.value.key == "config.error.token"


def test_override_needs_an_equals_sign() -> None:
    with pytest.raises(ConfigError) as caught:
        config.load_settings(overrides=["copy.roles"], environ={})
    assert caught.value.key == "config.error.override"


def test_the_template_is_exactly_the_defaults() -> None:
    parsed = config._flatten(tomllib.loads(config.TEMPLATE))
    defaults = {k: v for k, v in config.flat_settings(Settings()).items() if v is not None}
    assert parsed == defaults


def test_template_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.toml"
    assert config.write_template(path) == path
    path.write_text("mine", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.write_template(path)
    assert path.read_text(encoding="utf-8") == "mine"


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("win32", Path("appdata") / "CloneX"),
        ("darwin", Path("home") / "Library" / "Application Support" / "CloneX"),
        ("linux", Path("xdg") / "clonex"),
    ],
)
def test_each_platform_uses_its_own_settings_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, expected: Path
) -> None:
    monkeypatch.setattr(config.sys, "platform", platform)
    monkeypatch.setattr(config.Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    assert config.user_config_dir() == tmp_path / expected


def test_cli_reports_bad_settings_but_still_shows_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "copy.rolez = true\n")
    with pytest.raises(SystemExit) as caught:
        cli.main(["--version"])
    assert caught.value.code == 0
    capsys.readouterr()
    assert cli.main(["--demo"]) == 1
    assert "copy.rolez" in capsys.readouterr().err


def test_cli_init_show_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "made.toml"
    assert cli.main(["--init-config", str(target)]) == 0
    assert target.is_file()
    capsys.readouterr()
    assert cli.main(["--config", str(target), "--set", "copy.roles=false", "--show-config"]) == 0
    shown = capsys.readouterr().out
    assert "copy.roles = False" in shown and str(target) in shown
    assert cli.main(["--list-languages"]) == 0
    assert "English" in capsys.readouterr().out


def test_settings_supply_the_server_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    from clonex import session
    from clonex.core.models import ExitCode

    seen: dict[str, int] = {}

    def fake_run(token: str, source: int, target: int, **_: object) -> ExitCode:
        seen.update(source=source, target=target)
        return ExitCode.OK

    monkeypatch.setattr(session, "run", fake_run)
    monkeypatch.setenv(config.TOKEN_VARIABLE, "abc")
    args = argparse.Namespace(source=None, target=None, apply=False, demo=False)
    settings = Settings(source=11, target=22)
    assert cli._run(args, settings, cli.build_ui(settings), show_menu=False) is ExitCode.OK
    assert seen == {"source": 11, "target": 22}
