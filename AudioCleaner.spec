# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        ('MediaInfo.exe', '.'),
        ('LIBCURL.DLL', '.'),
    ],
    datas=[
        ('audio_cleaner_icon.ico', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AudioCleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-compressed, --onefile, windowed (console=False) PyInstaller
    # builds are one of the most commonly false-positived patterns by
    # Windows Defender and other AV/EDR products -- and, worse, some of
    # them don't just quarantine the file on disk, they kill the *running*
    # process the moment its behaviour looks suspicious (which, for this
    # app, is exactly what normal operation looks like: rapidly rewriting
    # a lot of files). That would present as exactly "runs fine through
    # every file, then the app just closes, no error" -- with nothing for
    # AudioCleaner's own code to catch, because the OS terminated the
    # process out from under it. Disabling UPX removes the single biggest
    # contributor to that risk, at the cost of a somewhat larger exe.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='audio_cleaner_icon.ico',
)
