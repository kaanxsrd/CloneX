"""License terms that have to travel with the code and every release."""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import build
import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_the_project_is_licensed_under_gpl_3() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 29 June 2007" in text


def test_the_original_project_stays_credited() -> None:
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    assert "https://github.com/ArviiSoft/server-mirror" in notice
    assert "Copyright (c) 2026 Server Mirror contributors" in notice
    assert "Permission is hereby granted, free of charge" in notice
    assert "ArviiSoft/server-mirror" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_every_archive_carries_the_license_and_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / build.BINARY
    executable.write_bytes(b"program")
    monkeypatch.setattr(build, "DIST", tmp_path)
    archive = build.package(executable, "1.2.3")
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
    else:
        with tarfile.open(archive) as bundle:
            names = set(bundle.getnames())
    assert names == {build.BINARY, "LICENSE", "NOTICE.md"}
