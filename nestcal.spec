# PyInstaller spec. Build with: pyinstaller --noconfirm nestcal.spec
# Produces dist/Nestcal.app on macOS and dist/nestcal/ elsewhere.
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
# These load timezone data and submodules dynamically, which static analysis misses.
for package in ("icalendar", "recurring_ical_events", "tzdata", "certifi"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

analysis = Analysis(
    ["nestcal_tray.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Nestcal",
    console=False,
)
collected = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    name="nestcal",
)
app = BUNDLE(
    collected,
    name="Nestcal.app",
    bundle_identifier="com.github.fluffynuts.nestcal",
    info_plist={
        # menu-bar only: no Dock icon, no app-switcher entry
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
