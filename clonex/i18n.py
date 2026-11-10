"""Interface translations.

``locales/en.json`` is the source text and every other catalog translates it. A key that a
catalog lacks falls back to English, so a partial or hand-made translation can never break a
copy. Files in ``<settings folder>/locales`` add languages, or override shipped ones, without
rebuilding the program.
"""

from __future__ import annotations

import json
import locale
import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from clonex.config import ConfigError, user_config_dir

AUTO = "auto"
DEFAULT_LANGUAGE = "en"
_META = "_meta"
_SYSTEM_VARIABLES = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")
_NON_LANGUAGES = frozenset({"", "C", "POSIX"})
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_ALIASES = {
    "nb": "no",
    "nn": "no",
    "tl": "fil",
    "in": "id",
    "iw": "he",
    "zh": "zh-cn",
    "zh-hans": "zh-cn",
    "zh-sg": "zh-cn",
    "zh-hant": "zh-tw",
    "zh-hk": "zh-tw",
    "zh-mo": "zh-tw",
    "pt-pt": "pt",
    "es-es": "es",
}


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    name: str
    english_name: str


@dataclass(slots=True)
class _State:
    english: dict[str, str] = field(default_factory=dict)
    active: dict[str, str] = field(default_factory=dict)
    code: str = DEFAULT_LANGUAGE


_state = _State()


def _packaged_files() -> dict[str, Any]:
    folder = resources.files("clonex") / "locales"
    return {p.name.removesuffix(".json"): p for p in folder.iterdir() if p.name.endswith(".json")}


def _user_files() -> dict[str, Any]:
    folder = user_config_dir() / "locales"
    return {p.stem: p for p in folder.glob("*.json")} if folder.is_dir() else {}


def _catalog_files() -> dict[str, Any]:
    return {**_packaged_files(), **_user_files()}


def _read_catalog(source: Any) -> dict[str, Any]:
    with source.open("r", encoding="utf-8") as handle:
        catalog = json.load(handle)
    if not isinstance(catalog, dict):
        raise ValueError("A language file must contain one JSON object.")
    return catalog


def _english() -> dict[str, str]:
    if not _state.english:
        catalog = _read_catalog(_packaged_files()[DEFAULT_LANGUAGE])
        catalog.pop(_META, None)
        _state.english = catalog
    return _state.english


def _fill(template: str, values: dict[str, object]) -> str:
    # Plain substitution: a downloaded catalog must not get str.format's attribute access.
    return _PLACEHOLDER.sub(lambda match: str(values.get(match[1], match[0])), template)


def t(key: str, /, **values: object) -> str:
    """Return the text for ``key`` in the active language."""
    template = _state.active.get(key) or _english().get(key, key)
    return _fill(template, values)


def error_text(error: ConfigError) -> str:
    """Render a settings error, resolving any message-key arguments it carries."""
    values = dict(error.values)
    if "expected_key" in values:
        limit = values.pop("limit", "")
        values["expected"] = t(str(values.pop("expected_key")), limit=limit)
    return t(error.key, **values)


def active_language() -> str:
    return _state.code


def _candidates(requested: str) -> Iterator[str]:
    """Yield lowercase catalog codes to try, most specific first."""
    code = requested.split(".")[0].split("@")[0].replace("_", "-").strip().lower()
    yield _ALIASES.get(code, code)
    language, _, region = code.partition("-")
    if language == "es" and region:
        yield "es-419"  # Every Spanish region except Spain, which the alias above handled.
    yield _ALIASES.get(language, language)


def match_language(requested: str | None) -> str | None:
    """Return the catalog code that best serves ``requested``, or ``None``."""
    if not requested:
        return None
    by_lower = {code.lower(): code for code in _catalog_files()}
    return next((by_lower[c] for c in _candidates(requested) if c in by_lower), None)


def detect_system_language() -> str | None:
    """Read the language of the user's session on any platform."""
    for variable in _SYSTEM_VARIABLES:
        for value in os.environ.get(variable, "").split(":"):
            if value.split(".")[0] not in _NON_LANGUAGES:
                return value
    if sys.platform == "win32":
        import ctypes

        return locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleLocale"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() or None
    return None


def activate(requested: str = AUTO) -> str:
    """Switch the interface language and return the code that was chosen."""
    if requested.strip().lower() == AUTO:
        code = match_language(detect_system_language()) or DEFAULT_LANGUAGE
    else:
        matched = match_language(requested)
        if matched is None:
            raise ConfigError("language.error.unknown", code=requested)
        code = matched
    source = _catalog_files()[code]
    try:
        catalog = _read_catalog(source)
    except (OSError, ValueError) as error:
        raise ConfigError("language.error.invalid", path=source) from error
    catalog.pop(_META, None)
    _state.active, _state.code = catalog, code
    return code


def available_languages() -> list[Language]:
    languages = []
    for code, source in _catalog_files().items():
        meta = _read_catalog(source).get(_META, {})
        languages.append(Language(code, meta.get("name", code), meta.get("english", code)))
    return sorted(languages, key=lambda language: language.code.lower())


def _answers(key: str) -> frozenset[str]:
    combined = f"{_english()[key]},{_state.active.get(key, '')}"
    return frozenset(word.strip().casefold() for word in combined.split(",") if word.strip())


def yes_answers() -> frozenset[str]:
    """Accepted ways of saying yes; English always works alongside the active language."""
    return _answers("answer.yes")


def no_answers() -> frozenset[str]:
    return _answers("answer.no") | {""}


def normalize_digits(text: str) -> str:
    """Convert any script's decimal digits, such as Arabic-Indic, to ASCII."""
    return "".join(
        str(unicodedata.decimal(character)) if character.isdecimal() else character
        for character in text
    )
