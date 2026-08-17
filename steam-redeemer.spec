# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_submodules

# cryptography has C extensions + OpenSSL bindings that need explicit collection
crypto_datas, crypto_binaries, crypto_hiddenimports = collect_all('cryptography')

# cloudscraper dynamically loads interpreters at runtime
cs_datas, cs_binaries, cs_hiddenimports = collect_all('cloudscraper')

# rich dynamically imports rich._unicode_data.unicode<ver> at runtime, which
# PyInstaller's static analysis can't see — collect it explicitly (see issue #8)
rich_datas, rich_binaries, rich_hiddenimports = collect_all('rich')

a = Analysis(
    ['src/__main__.py'],
    pathex=[],
    binaries=crypto_binaries + cs_binaries + rich_binaries,
    datas=crypto_datas + cs_datas + rich_datas,
    hiddenimports=[
        *crypto_hiddenimports,
        *cs_hiddenimports,
        *rich_hiddenimports,
        *collect_submodules('cryptography'),
        *collect_submodules('cloudscraper'),
        *collect_submodules('rich'),
        'fuzzywuzzy',
        'Levenshtein',
        'requests_futures',
        'qrcode',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='steam-redeemer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
)
