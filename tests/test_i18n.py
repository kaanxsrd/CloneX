"""Translations: completeness, safety, detection, and adding new languages."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from clonex import config, i18n
from clonex.config import ConfigError
from clonex.i18n import t

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "clonex" / "locales"
ENGLISH: dict[str, str] = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
ENGLISH.pop("_meta")
TRANSLATIONS = sorted(path.stem for path in LOCALES.glob("*.json") if path.stem != "en")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
SOURCES = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "clonex").rglob("*.py"))
# Text that intentionally stays the same across scripts and languages.
UNTRANSLATED_ALLOWED = {
    "adjust.channel_item",
    "changes.item_everyone",
    "issue.capacity_item",
    "issue.parent_category_item",
    "order.item",
    "list.separator",
    "answer.yes",
    "answer.no",
    "menu.select",
}


def catalog(code: str) -> dict[str, str]:
    data = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if key != "_meta"}


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text))


def test_every_key_in_the_code_exists_in_english() -> None:
    used = set(re.findall(r'\bt\(\s*["\']([a-z_]+\.[a-z_.]+)["\']', SOURCES))
    assert used, "the scan must find translation calls"
    assert used - ENGLISH.keys() == set()


def test_every_english_key_is_used() -> None:
    literals = set(re.findall(r'["\']([a-z_]+\.[a-z_.]+)["\']', SOURCES))
    assert ENGLISH.keys() - literals == set()


@pytest.mark.parametrize("code", TRANSLATIONS)
class TestEveryShippedTranslation:
    def test_has_exactly_the_english_keys(self, code: str) -> None:
        keys = catalog(code).keys()
        assert ENGLISH.keys() - keys == set(), "missing"
        assert keys - ENGLISH.keys() == set(), "unexpected"

    def test_keeps_every_placeholder(self, code: str) -> None:
        for key, text in catalog(code).items():
            assert placeholders(text) == placeholders(ENGLISH[key]), key

    def test_has_a_name(self, code: str) -> None:
        meta = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))["_meta"]
        assert meta["name"].strip() and meta["english"].strip()

    def test_is_really_translated(self, code: str) -> None:
        text = catalog(code)
        same = [
            key
            for key, value in text.items()
            if value == ENGLISH[key] and key not in UNTRANSLATED_ALLOWED and " " in value
        ]
        assert len(same) <= len(text) * 0.05, same

    def test_yes_and_no_never_overlap(self, code: str) -> None:
        i18n.activate(code)
        assert not i18n.yes_answers() & i18n.no_answers()

    def test_renders_the_whole_interface(self, code: str) -> None:
        from dataclasses import replace

        from test_terminal import ISSUE, SUMMARY, make_ui

        from clonex.ui.demo import demo

        i18n.activate(code)
        ui = make_ui(70)
        demo(ui)
        full = replace(
            SUMMARY,
            issues=(ISSUE,),
            renamed_roles=((1, "a"),),
            converted_channels=((2, "b", "news"),),
            skipped_channels=((3, "c", "forum"),),
            skipped_member_overwrites=2,
            skipped_member_channels=1,
            retained_role="Admin",
            limited_bitrates=1,
            static_icon=True,
            excluded_channels=1,
        )
        ui.preview(full)
        ui.completed(full)
        ui.preview_complete()
        ui.cancelled()
        ui.error("x")
        assert "{" not in ui.console.file.getvalue().replace("{}", "")  # type: ignore[attr-defined]


def test_answers_work_in_the_active_language_and_in_english() -> None:
    i18n.activate("tr")
    assert {"e", "evet", "y", "yes"} <= i18n.yes_answers()
    assert {"h", "hayir", "hay\u0131r", "n", "no", ""} <= i18n.no_answers()
    i18n.activate("en")
    assert "evet" not in i18n.yes_answers()


def test_regional_codes_find_the_closest_language() -> None:
    assert i18n.match_language("pt_BR.UTF-8") == "pt-BR"
    assert i18n.match_language("pt_PT") == "pt"
    assert i18n.match_language("es_MX") == "es-419"
    assert i18n.match_language("es_ES") == "es"
    assert i18n.match_language("zh_Hant") == "zh-TW"
    assert i18n.match_language("zh_HK") == "zh-TW"
    assert i18n.match_language("zh") == "zh-CN"
    assert i18n.match_language("nb_NO") == "no"
    assert i18n.match_language("de_AT") == "de"
    assert i18n.match_language("tl") == "fil"


def test_every_discord_language_is_shipped() -> None:
    discord_locales = (
        "bg cs da de el en es es-419 fi fr hi hr hu id it ja ko lt nl no pl pt-BR ro ru sv th tr "
        "uk vi zh-CN zh-TW"
    )
    codes = {language.code for language in i18n.available_languages()}
    assert set(discord_locales.split()) <= codes


def test_missing_keys_fall_back_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    folder = config.user_config_dir() / "locales"
    folder.mkdir(parents=True)
    (folder / "xx.json").write_text('{"menu.exit": "Sortie"}', encoding="utf-8")
    assert i18n.activate("xx") == "xx"
    assert t("menu.exit") == "Sortie"
    assert t("menu.preview") == ENGLISH["menu.preview"]


def test_a_dropped_in_file_adds_or_overrides_a_language() -> None:
    folder = config.user_config_dir() / "locales"
    folder.mkdir(parents=True)
    (folder / "en.json").write_text('{"menu.exit": "Leave"}', encoding="utf-8")
    (folder / "qq.json").write_text('{"_meta": {"name": "Q", "english": "Qish"}}', encoding="utf-8")
    i18n.activate("en")
    assert t("menu.exit") == "Leave"
    assert any(language.code == "qq" for language in i18n.available_languages())


def test_a_broken_language_file_is_a_clear_error() -> None:
    folder = config.user_config_dir() / "locales"
    folder.mkdir(parents=True)
    (folder / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        i18n.activate("bad")
    assert caught.value.key == "language.error.invalid"


def test_catalogs_cannot_read_object_attributes() -> None:
    folder = config.user_config_dir() / "locales"
    folder.mkdir(parents=True)
    (folder / "xx.json").write_text('{"menu.exit": "{value.__class__} {value}"}', encoding="utf-8")
    i18n.activate("xx")
    assert t("menu.exit", value="ok") == "{value.__class__} ok"


def test_unknown_language_is_an_error() -> None:
    with pytest.raises(ConfigError) as caught:
        i18n.activate("not-a-language")
    assert caught.value.key == "language.error.unknown"


def test_auto_falls_back_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "detect_system_language", lambda: "xx_YY.UTF-8")
    assert i18n.activate("auto") == "en"
    monkeypatch.setattr(i18n, "detect_system_language", lambda: None)
    assert i18n.activate("auto") == "en"


@pytest.mark.parametrize(
    ("variable", "value", "expected"),
    [
        ("LANG", "tr_TR.UTF-8", "tr_TR.UTF-8"),
        ("LANGUAGE", "de:en", "de"),
        ("LC_ALL", "fr_FR", "fr_FR"),
    ],
)
def test_detection_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str, expected: str
) -> None:
    monkeypatch.setenv(variable, value)
    assert i18n.detect_system_language() == expected


def test_detection_ignores_the_c_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    assert i18n.detect_system_language() is None


def test_macos_detection_asks_the_system(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(i18n.sys, "platform", "darwin")
    monkeypatch.setattr(i18n.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout="ja_JP\n"))
    assert i18n.detect_system_language() == "ja_JP"


def test_english_is_always_available() -> None:
    assert i18n.match_language("EN") == "en"
    assert i18n.match_language("en_GB.UTF-8") == "en"


def test_digits_from_any_script_are_normalized() -> None:
    assert i18n.normalize_digits("١٢٣") == "123"
    assert i18n.normalize_digits("१२३") == "123"
    assert i18n.normalize_digits("１２") == "12"  # noqa: RUF001
    assert i18n.normalize_digits("a1") == "a1"
