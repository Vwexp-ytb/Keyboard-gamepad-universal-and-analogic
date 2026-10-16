# PyInstaller spec for the graphical edition.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

root = Path(SPECPATH)
datas = [(str(root / "config"), "config"), (str(root / "locales"), "locales"),
         (str(root / "profiles"), "profiles")]
binaries = []
hiddenimports = [
    "hid", "vgamepad", "vgamepad.win.virtual_gamepad", "vgamepad.win.vigem_client",
    "vgamepad.win.vigem_commons", "vgamepad.lin.virtual_gamepad", "tkinter",
]
for package in ("keyboard", "mouse"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports
datas += collect_data_files("vgamepad")
binaries += collect_dynamic_libs("vgamepad")

a = Analysis(
    [str(root / "main_gui.py")], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False, optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name="ACE60-Gamepad-GUI", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=True, console=False,
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None,
)
