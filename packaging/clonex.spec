# PyInstaller recipe for the standalone executable. Run it through scripts/build.py.

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
VERSION = re.search(
    r'^__version__ = "(\d+\.\d+\.\d+)"$',
    (ROOT / "clonex" / "__init__.py").read_text(encoding="utf-8"),
    re.MULTILINE,
).group(1)

version_resource = None
icon = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    icon = str(ROOT / "packaging" / "clonex.ico")
    numbers = (*map(int, VERSION.split(".")), 0)
    version_resource = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("FileDescription", "CloneX"),
                            StringStruct("FileVersion", VERSION),
                            StringStruct("InternalName", "clonex"),
                            StringStruct("OriginalFilename", "clonex.exe"),
                            StringStruct("ProductName", "CloneX"),
                            StringStruct("ProductVersion", VERSION),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )

analysis = Analysis(
    [str(ROOT / "clonex" / "__main__.py")],
    pathex=[str(ROOT)],
    # Generated protobuf and FFI modules are loaded in ways static analysis cannot follow.
    hiddenimports=[*collect_submodules("discord_protos"), *collect_submodules("curl_cffi")],
    datas=[
        (str(ROOT / "clonex" / "locales"), "clonex/locales"),
        *collect_data_files("curl_cffi"),
        *collect_data_files("certifi"),
    ],
    binaries=collect_dynamic_libs("curl_cffi"),
    excludes=["PIL", "nacl", "numpy", "pydoc", "pytest", "setuptools", "tkinter", "unittest"],
)
# Voice playback is never used, so the bundled Opus codecs are dead weight.
analysis.binaries = [item for item in analysis.binaries if "libopus" not in item[0]]
analysis.datas = [item for item in analysis.datas if "libopus" not in item[0]]

EXE(
    PYZ(analysis.pure),
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="clonex",
    console=True,
    upx=False,  # UPX-packed executables are flagged by antivirus software far more often.
    icon=icon,
    version=version_resource,
)
