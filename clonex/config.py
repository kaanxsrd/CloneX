"""User settings.

The highest priority comes first: command-line flags, ``--set``, ``CLONEX_LANG``, the settings
file, then the defaults here. Account tokens are deliberately not a setting.
"""

from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

CONFIG_FILENAME = "clonex.toml"
CONFIG_VARIABLE = "CLONEX_CONFIG"
LANGUAGE_VARIABLE = "CLONEX_LANG"
TOKEN_VARIABLE = "DISCORD_USER_TOKEN"
DEFAULT_AUDIT_REASON = "CloneX: user-confirmed structure copy"
MAX_AUDIT_REASON = 512
_MAX_SNOWFLAKE = 2**64


class ConfigError(Exception):
    """Invalid settings. Holds a message key so it can be shown in the active language."""

    def __init__(self, message_key: str, /, **values: object) -> None:
        super().__init__(message_key)
        self.key = message_key
        self.values = values


@dataclass(frozen=True, slots=True)
class CopyOptions:
    roles: bool = True
    everyone_permissions: bool = True
    categories: bool = True
    text_channels: bool = True
    voice_channels: bool = True
    announcement_channels: Literal["text", "skip"] = "text"
    permission_overwrites: bool = True
    server_name: bool = True
    server_icon: bool = True


@dataclass(frozen=True, slots=True)
class ReplaceOptions:
    channels: bool = True
    roles: bool = True


@dataclass(frozen=True, slots=True)
class UiOptions:
    color: Literal["auto", "always", "never"] = "auto"
    max_listed: int = 8


@dataclass(frozen=True, slots=True)
class Settings:
    language: str = "auto"
    source: int | None = None
    target: int | None = None
    audit_reason: str = DEFAULT_AUDIT_REASON
    copy: CopyOptions = field(default_factory=CopyOptions)
    replace: ReplaceOptions = field(default_factory=ReplaceOptions)
    ui: UiOptions = field(default_factory=UiOptions)


@dataclass(frozen=True, slots=True)
class LoadedSettings:
    settings: Settings
    path: Path | None


_CHOICES: dict[str, tuple[str, ...]] = {
    "copy.announcement_channels": ("text", "skip"),
    "ui.color": ("auto", "always", "never"),
}
_SERVER_IDS = frozenset({"source", "target"})
_TEXT_LIMITS = {"language": 35, "audit_reason": MAX_AUDIT_REASON}

TEMPLATE = """\
# CloneX settings. Every value below is the default.
# Docs: docs/configuration.md. Account tokens can never be stored here.

# "auto" follows your system. Run `clonex --list-languages` for the options.
language = "auto"

# Set these to skip the prompts.
# source = 111111111111111111
# target = 222222222222222222

# Shown in the destination's audit log. At most 512 characters.
audit_reason = "CloneX: user-confirmed structure copy"

[copy]
roles = true
everyone_permissions = true
categories = true
text_channels = true
voice_channels = true
# "text" recreates announcement channels as text channels. "skip" leaves them out.
announcement_channels = "text"
# Turning this off removes every channel's allow/deny rules, so private channels can become visible.
permission_overwrites = true
server_name = true
server_icon = true

# Delete what already exists in the destination first. Set both to false to only add.
[replace]
channels = true
roles = true

[ui]
# "auto", "always" or "never". NO_COLOR is also respected.
color = "auto"
# How many items each adjustment list shows before "...and N more".
max_listed = 8
"""


def user_config_dir() -> Path:
    """The per-user settings folder that is conventional on each platform."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "CloneX"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CloneX"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "clonex"


def user_config_path() -> Path:
    return user_config_dir() / "config.toml"


def _flatten(table: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in table.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


_DEFAULTS = _flatten(asdict(Settings()))


def _server_id(key: str, value: Any) -> int:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < _MAX_SNOWFLAKE:
        raise ConfigError("config.error.type", key=key, expected_key="config.expected.server_id")
    return value


def validated(key: str, value: Any) -> Any:
    """Return ``value`` if it suits ``key``; otherwise raise a :class:`ConfigError`."""
    if key.rsplit(".", 1)[-1] == "token":
        raise ConfigError("config.error.token", variable=TOKEN_VARIABLE)
    if key not in _DEFAULTS:
        raise ConfigError("config.error.unknown", key=key)
    if key in _SERVER_IDS:
        return _server_id(key, value)
    if key in _CHOICES:
        if value not in _CHOICES[key]:
            raise ConfigError("config.error.choice", key=key, choices=", ".join(_CHOICES[key]))
        return value
    default = _DEFAULTS[key]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ConfigError("config.error.type", key=key, expected_key="config.expected.boolean")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ConfigError("config.error.type", key=key, expected_key="config.expected.integer")
        return value
    limit = _TEXT_LIMITS[key]
    if not isinstance(value, str) or not 0 < len(value.strip()) <= limit:
        raise ConfigError(
            "config.error.type", key=key, expected_key="config.expected.text", limit=limit
        )
    return value.strip()


def parse_override(text: str) -> tuple[str, Any]:
    """Split ``KEY=VALUE``, reading the value as TOML so ``false`` and ``8`` keep their types."""
    key, separator, raw = text.partition("=")
    if not separator or not key.strip():
        raise ConfigError("config.error.override", value=text)
    raw = raw.strip()
    try:
        return key.strip(), tomllib.loads(f"value = {raw}")["value"]
    except tomllib.TOMLDecodeError:
        return key.strip(), raw


def find_config(explicit: str | None, environ: Mapping[str, str]) -> Path | None:
    """Pick the one settings file to use: explicit, then local, then per-user."""
    chosen = explicit or environ.get(CONFIG_VARIABLE)
    if chosen:
        path = Path(chosen).expanduser()
        if not path.is_file():
            raise ConfigError("config.error.missing", path=path)
        return path
    for candidate in (Path.cwd() / CONFIG_FILENAME, user_config_path()):
        if candidate.is_file():
            return candidate
    return None


def _read_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            table = tomllib.load(handle)
    except OSError as error:
        raise ConfigError("config.error.unreadable", path=path) from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError("config.error.invalid", path=path, detail=error) from error
    return {key: validated(key, value) for key, value in _flatten(table).items()}


def _build(values: Mapping[str, Any]) -> Settings:
    sections: dict[str, dict[str, Any]] = {"copy": {}, "replace": {}, "ui": {}}
    top: dict[str, Any] = {}
    for key, value in values.items():
        section, dot, name = key.partition(".")
        if dot:
            sections[section][name] = value
        else:
            top[key] = value
    return Settings(
        **top,
        copy=CopyOptions(**sections["copy"]),
        replace=ReplaceOptions(**sections["replace"]),
        ui=UiOptions(**sections["ui"]),
    )


def load_settings(
    explicit_path: str | None = None,
    overrides: Iterable[str] = (),
    environ: Mapping[str, str] | None = None,
) -> LoadedSettings:
    environment = os.environ if environ is None else environ
    path = find_config(explicit_path, environment)
    merged = dict(_DEFAULTS)
    if path is not None:
        merged.update(_read_file(path))
    language = environment.get(LANGUAGE_VARIABLE, "").strip()
    if language:
        merged["language"] = language
    for override in overrides:
        key, value = parse_override(override)
        merged[key] = validated(key, value)
    return LoadedSettings(_build(merged), path)


def flat_settings(settings: Settings) -> dict[str, Any]:
    return _flatten(asdict(settings))


def write_template(path: Path) -> Path:
    """Create a commented settings file, refusing to replace an existing one."""
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(TEMPLATE)
    except FileExistsError as error:
        raise ConfigError("config.error.exists", path=path) from error
    return path
