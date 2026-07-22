# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for formharvester.exe.

    uv run pyinstaller packaging/formharvester.spec

This is a spec file rather than a line of CLI flags because the splash screen
needs options the command line does not expose: PyInstaller draws its status
text in black by default, which is invisible on the dark splash image.

formharvester.ico and splash.png are committed build assets, both derived from
docs/logo.png.
"""

import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)  # noqa: F821 - SPECPATH is injected by PyInstaller

datas = [(os.path.join(ROOT, "src", "formharvester", "gui", "web"), "formharvester/gui/web")]
binaries = []
hiddenimports = []

# selenium and pywebview resolve their submodules lazily through __getattr__,
# so static analysis misses them and the frozen app fails at import time.
for package in ("selenium", "webview"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(  # noqa: F821
    [os.path.join(SPECPATH, "windows_entry.py")],  # noqa: F821
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

# Shown by the bootloader while the archive unpacks, before any Python runs.
# windows_entry.py animates the status text and closes this once the window
# is up.
splash = Splash(  # noqa: F821
    os.path.join(SPECPATH, "splash.png"),  # noqa: F821
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(24, 252),
    text_size=9,
    text_color="#7d8390",
    text_default="starting...",
    always_on_top=False,
)

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name="formharvester",
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon=os.path.join(SPECPATH, "formharvester.ico"),  # noqa: F821
)
