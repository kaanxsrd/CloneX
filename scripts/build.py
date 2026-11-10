"""Build the standalone executable and prove it starts before anyone downloads it.

    uv run --group build python scripts/build.py

The result is ``dist/clonex_<version>_<os>_<arch>.tar.gz`` (``.zip`` on Windows). An archive
keeps the executable bit, which GitHub's artifact storage and browsers would otherwise lose.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SPEC = ROOT / "packaging" / "clonex.spec"
LEGAL_FILES = (ROOT / "LICENSE", ROOT / "NOTICE.md")
BINARY = "clonex.exe" if sys.platform == "win32" else "clonex"
_SYSTEMS = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
_MACHINES = {"amd64": "amd64", "x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


def read_version() -> str:
    source = (ROOT / "clonex" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"$', source, re.MULTILINE)
    if match is None:
        raise SystemExit("Could not read __version__ from clonex/__init__.py.")
    return match.group(1)


def archive_stem(version: str) -> str:
    machine = platform.machine().lower()
    return f"clonex_{version}_{_SYSTEMS[sys.platform]}_{_MACHINES.get(machine, machine)}"


def smoke_test(executable: Path, version: str) -> None:
    """Exercise the frozen binary; a hidden-import mistake only shows up at runtime."""
    environment = {**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
    environment.pop("DISCORD_USER_TOKEN", None)
    environment["CLONEX_LANG"] = "en"
    catalog = json.loads((ROOT / "clonex" / "locales" / "tr.json").read_text(encoding="utf-8"))
    translated_title = catalog["panel.complete"]
    checks: tuple[tuple[list[str], str], ...] = (
        (["--version"], f"CloneX {version}"),
        (["--check"], "Installation OK"),
        (["--demo"], "Demo finished"),
        (["--list-languages"], "Türkçe"),
        (["--lang", "tr", "--demo"], translated_title),
    )
    for arguments, expected in checks:
        print(f"smoke test: {executable.name} {' '.join(arguments)}")
        result = subprocess.run(
            [str(executable), *arguments],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if result.returncode != 0 or expected not in result.stdout:
            raise SystemExit(
                f"Expected {expected!r}, exit code {result.returncode}:\n"
                f"{result.stdout}\n{result.stderr}"
            )


def package(executable: Path, version: str) -> Path:
    stem = archive_stem(version)
    if sys.platform == "win32":
        archive = DIST / f"{stem}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(executable, executable.name)
            for path in LEGAL_FILES:
                bundle.write(path, path.name)
        return archive
    archive = DIST / f"{stem}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(executable, executable.name)
        for path in LEGAL_FILES:
            bundle.add(path, path.name)
    return archive


def main() -> None:
    version = read_version()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--log-level",
            "WARN",
            "--distpath",
            str(DIST),
            "--workpath",
            str(ROOT / "build"),
            str(SPEC),
        ],
        check=True,
    )
    executable = DIST / BINARY
    smoke_test(executable, version)
    archive = package(executable, version)
    print(f"built {archive.relative_to(ROOT)} ({archive.stat().st_size / 2**20:.1f} MiB)")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"path={archive}\n")


if __name__ == "__main__":
    main()
