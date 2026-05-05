# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('config', 'config'), ('dictionaries', 'dictionaries'), ('hot_words', 'hot_words'), ('src/ui/templates', 'src/ui/templates'), ('src/ui/static', 'src/ui/static')],
    hiddenimports=['pyaudiowpatch', 'dashscope', 'openai', 'flask', 'flask_cors', 'numpy', 'pyaudio', 'pythonosc', 'requests', 'httpx', 'onnxruntime', 'dotenv'],
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
    [],
    exclude_binaries=True,
    name='VRC-Translator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='NONE',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VRC-Translator',
)
