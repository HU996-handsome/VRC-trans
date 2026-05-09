# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None
src_dir = os.path.join(os.path.dirname(os.path.abspath(SPEC)), 'src')

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        (os.path.join(src_dir, 'ui', 'templates'), os.path.join('src', 'ui', 'templates')),
        (os.path.join(src_dir, 'ui', 'static'), os.path.join('src', 'ui', 'static')),
    ],
    hiddenimports=[
        'dashscope',
        'dashscope.audio.asr',
        'pyaudio',
        'pyaudiowpatch',
        'numpy',
        'httpx',
        'openai',
        'pythonosc',
        'pythonosc.udp_client',
        'googletrans',
        'httpx._transports.default',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'scipy', 'pandas',
        'torch', 'torchvision', 'torchaudio',
        'tensorboard', 'tensorflow',
        'PIL', 'Pillow',
        'cv2', 'opencv',
        'onnxruntime',
        'lxml',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VRC-Translator',
)
