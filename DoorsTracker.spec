# -*- mode: python ; coding: utf-8 -*-


block_cipher = None


a = Analysis(
    ['DoorsTracker.py'],
    pathex=[],
    binaries=[],
    # The door randomizer's files that gui/Doors/rules.py and checks.py read as text when the tracker starts.
    # The modules checks.py imports are found from its imports
    datas=[(f'ALttPDoorRandomizer/{name}', 'ALttPDoorRandomizer') for name in ('Rules.py', 'BaseClasses.py', 'Regions.py', 'DoorShuffle.py', 'MultiClient.py', 'InitialSram.py', 'Dungeons.py')]
    # and its item pictures, for the items panel
    + [('ALttPDoorRandomizer/data/itemgfx', 'ALttPDoorRandomizer/data/itemgfx')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'pandas', 'numpy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas + Tree('./data', prefix='data', excludes=['tmp','*.pyc']),
    [],
    name='DoorsTracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
