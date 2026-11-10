"""The Homebrew and Scoop files a release publishes."""

from __future__ import annotations

import json

import package_managers as pm

VERSION = "1.2.0"
NAMES = [
    f"clonex_{VERSION}_{system}_{arch}.{suffix}"
    for system, suffix in (("linux", "tar.gz"), ("darwin", "tar.gz"), ("windows", "zip"))
    for arch in ("amd64", "arm64")
]
SUMS = {name: f"{index:064x}" for index, name in enumerate(NAMES)}


def test_parse_sha256sum_output() -> None:
    text = "".join(f"{digest}  {name}\n" for name, digest in SUMS.items())
    assert pm.parse_checksums(text) == SUMS
    assert pm.parse_checksums(f"abc *{NAMES[0]}\n") == {NAMES[0]: "abc"}


def test_cask_covers_every_unix_build() -> None:
    cask = pm.homebrew_cask(VERSION, SUMS, "me/CloneX")
    for name in NAMES:
        if "windows" not in name:
            assert SUMS[name] in cask
    assert 'cask "clonex" do' in cask
    assert f'version "{VERSION}"' in cask
    assert '"com.apple.quarantine"' in cask
    assert "windows" not in cask


def test_scoop_manifest_covers_both_windows_builds() -> None:
    manifest = json.loads(pm.scoop_manifest(VERSION, SUMS, "me/CloneX"))
    assert manifest["version"] == VERSION
    x64 = manifest["architecture"]["64bit"]
    arm = manifest["architecture"]["arm64"]
    assert x64["hash"] == SUMS[f"clonex_{VERSION}_windows_amd64.zip"]
    assert arm["hash"] == SUMS[f"clonex_{VERSION}_windows_arm64.zip"]
    assert x64["bin"] == ["clonex.exe"]
    assert f"releases/download/v{VERSION}/" in x64["url"]
    assert manifest["license"] == "GPL-3.0-only"
