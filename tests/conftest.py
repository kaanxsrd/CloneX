"""Every test starts in English with no settings file and an empty environment."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from clonex import config, i18n

_CLEARED = (
    config.CONFIG_VARIABLE,
    config.LANGUAGE_VARIABLE,
    config.TOKEN_VARIABLE,
    "LANGUAGE",
    "LC_ALL",
    "LC_MESSAGES",
    "LANG",
)


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for variable in _CLEARED:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    i18n.activate("en")
    yield
    i18n.activate("en")
