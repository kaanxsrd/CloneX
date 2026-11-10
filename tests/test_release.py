"""Versioning rules enforced by scripts/release.py."""

from __future__ import annotations

import datetime as dt

import pytest
import release

SOURCE = '"""Doc."""\n\n__version__ = "1.4.2"\n'
DAY = dt.date(2026, 3, 9)
CHANGELOG = """# Changelog

Intro.

## [Unreleased]

### Fixed

- Something important.

## [1.4.2] - 2026-02-01

### Added

- Older work.

"""


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        ("patch", "1.4.3"),
        ("minor", "1.5.0"),
        ("major", "2.0.0"),
        ("1.10.0", "1.10.0"),
        ("v2.0.1", "2.0.1"),
    ],
)
def test_next_version(request_: str, expected: str) -> None:
    assert release.next_version("1.4.2", request_) == expected


@pytest.mark.parametrize("request_", ["1.4.2", "1.4.1", "0.9.9", "banana", "1.2", "1.2.3.4"])
def test_versions_must_move_forward_and_be_well_formed(request_: str) -> None:
    with pytest.raises(release.ReleaseError):
        release.next_version("1.4.2", request_)


def test_version_is_compared_numerically() -> None:
    assert release.next_version("1.9.0", "1.10.0") == "1.10.0"


def test_replace_version_changes_only_the_version() -> None:
    assert release.replace_version(SOURCE, "2.0.0") == '"""Doc."""\n\n__version__ = "2.0.0"\n'


def test_rolled_changelog_keeps_notes_under_the_new_heading() -> None:
    rolled = release.roll_changelog(CHANGELOG, "1.5.0", DAY)
    assert "## [Unreleased]\n\n## [1.5.0] - 2026-03-09\n\n### Fixed" in rolled
    assert release.release_notes(rolled, "1.5.0") == "### Fixed\n\n- Something important."
    assert release.release_notes(rolled, "1.4.2") == "### Added\n\n- Older work."


def test_empty_unreleased_section_is_refused() -> None:
    empty = CHANGELOG.replace("### Fixed\n\n- Something important.\n\n", "")
    with pytest.raises(release.ReleaseError, match="Add the changes"):
        release.roll_changelog(empty, "1.5.0", DAY)


def test_a_roll_cannot_be_applied_to_the_new_empty_section() -> None:
    rolled = release.roll_changelog(CHANGELOG, "1.5.0", DAY)
    with pytest.raises(release.ReleaseError, match="Add the changes"):
        release.roll_changelog(rolled, "1.6.0", DAY)


def test_notes_for_an_unknown_version_fail() -> None:
    with pytest.raises(release.ReleaseError, match="no section"):
        release.release_notes(CHANGELOG, "9.9.9")


def test_tag_must_match_the_code_and_the_changelog() -> None:
    release.check("v1.4.2", SOURCE, CHANGELOG)
    with pytest.raises(release.ReleaseError, match="does not match"):
        release.check("v1.4.3", SOURCE, CHANGELOG)
    with pytest.raises(release.ReleaseError, match="no section"):
        release.check("v1.4.2", SOURCE, "# Changelog\n")


@pytest.mark.parametrize("tag", ["1.4.2", "v1.4", "vX.Y.Z", "release-1.4.2"])
def test_malformed_tags_are_refused(tag: str) -> None:
    with pytest.raises(release.ReleaseError):
        release.tag_version(tag)


def test_project_version_is_well_formed() -> None:
    assert release.read_version(release.VERSION_FILE.read_text(encoding="utf-8"))
