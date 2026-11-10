"""Cut a release, and let CI confirm that a tag is safe to publish.

    python scripts/release.py patch|minor|major|X.Y.Z   bump, roll the changelog, commit, tag
    python scripts/release.py check vX.Y.Z              CI: tag, code and changelog must agree
    python scripts/release.py notes vX.Y.Z              CI: print that version's changelog section

Nothing here pushes. Publishing is ``git push --follow-tags``, which triggers release.yml.
Standard library only, so it runs before any dependency is installed.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "clonex" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
_VERSION_LINE = re.compile(r'^__version__ = "(\d+\.\d+\.\d+)"$', re.MULTILINE)
_VERSION = re.compile(r"\d+\.\d+\.\d+")
_UNRELEASED = "## [Unreleased]"
_BUMPS = ("major", "minor", "patch")


class ReleaseError(Exception):
    """The release cannot proceed; the message says why."""


def read_version(source: str) -> str:
    match = _VERSION_LINE.search(source)
    if match is None:
        raise ReleaseError(f"No __version__ line found in {VERSION_FILE.name}.")
    return match.group(1)


def replace_version(source: str, version: str) -> str:
    return _VERSION_LINE.sub(f'__version__ = "{version}"', source, count=1)


def _as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def next_version(current: str, request: str) -> str:
    """Resolve ``major``/``minor``/``patch`` or an explicit version; it must move forward."""
    if request in _BUMPS:
        major, minor, patch = _as_tuple(current)
        return {
            "major": f"{major + 1}.0.0",
            "minor": f"{major}.{minor + 1}.0",
            "patch": f"{major}.{minor}.{patch + 1}",
        }[request]
    candidate = request.removeprefix("v")
    if _VERSION.fullmatch(candidate) is None:
        raise ReleaseError(f"Use major, minor, patch, or X.Y.Z; got {request!r}.")
    if _as_tuple(candidate) <= _as_tuple(current):
        raise ReleaseError(f"{candidate} is not newer than the current version {current}.")
    return candidate


def _section_span(changelog: str, heading_start: int) -> tuple[int, int]:
    body_start = changelog.index("\n", heading_start) + 1
    following = re.compile(r"^## \[", re.MULTILINE).search(changelog, body_start)
    return body_start, following.start() if following else len(changelog)


def roll_changelog(changelog: str, version: str, day: dt.date) -> str:
    """Turn the Unreleased notes into a dated section and leave an empty Unreleased behind."""
    start = changelog.find(_UNRELEASED)
    if start < 0:
        raise ReleaseError(f"{CHANGELOG.name} has no {_UNRELEASED} section.")
    body_start, body_end = _section_span(changelog, start)
    if not changelog[body_start:body_end].strip():
        raise ReleaseError(f"Add the changes to {_UNRELEASED} in {CHANGELOG.name} first.")
    heading = f"## [{version}] - {day:%Y-%m-%d}\n"
    return f"{changelog[:body_start]}\n{heading}{changelog[body_start:]}"


def release_notes(changelog: str, version: str) -> str:
    """Return the body of one version's changelog section."""
    heading = re.compile(rf"^## \[{re.escape(version)}\]", re.MULTILINE).search(changelog)
    if heading is None:
        raise ReleaseError(f"{CHANGELOG.name} has no section for {version}.")
    body_start, body_end = _section_span(changelog, heading.start())
    notes = changelog[body_start:body_end].strip()
    if not notes:
        raise ReleaseError(f"The {version} section of {CHANGELOG.name} is empty.")
    return notes


def tag_version(tag: str) -> str:
    if not tag.startswith("v") or _VERSION.fullmatch(tag[1:]) is None:
        raise ReleaseError(f"Release tags look like v1.2.3; got {tag!r}.")
    return tag[1:]


def check(tag: str, version_source: str, changelog: str) -> None:
    version = tag_version(tag)
    declared = read_version(version_source)
    if declared != version:
        raise ReleaseError(f"Tag {tag} does not match __version__ {declared}.")
    release_notes(changelog, version)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ReleaseError(f"git {' '.join(arguments)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def cut(request: str) -> None:
    source, changelog = _read(VERSION_FILE), _read(CHANGELOG)
    version = next_version(read_version(source), request)
    if _git("status", "--porcelain"):
        raise ReleaseError("Commit or stash your changes before cutting a release.")
    if _git("tag", "--list", f"v{version}"):
        raise ReleaseError(f"Tag v{version} already exists.")
    rolled = roll_changelog(changelog, version, dt.date.today())
    _write(VERSION_FILE, replace_version(source, version))
    _write(CHANGELOG, rolled)
    _git("add", str(VERSION_FILE), str(CHANGELOG))
    _git("commit", "-m", f"chore: release {version}")
    _git("tag", "-a", f"v{version}", "-m", f"CloneX {version}")
    print(f"Created commit and tag v{version}. Publish with:\n\n    git push --follow-tags\n")


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 1 and argv[0] not in {"check", "notes"}:
            cut(argv[0])
        elif len(argv) == 2 and argv[0] == "check":
            check(argv[1], _read(VERSION_FILE), _read(CHANGELOG))
            print(f"{argv[1]} is consistent with the code and the changelog.")
        elif len(argv) == 2 and argv[0] == "notes":
            print(release_notes(_read(CHANGELOG), tag_version(argv[1])))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
