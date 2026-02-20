"""Smoke test — verifies all critical imports work. Used by CI after PyInstaller build."""

import sys

errors = []

try:
    from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
except Exception as e:
    errors.append(f"cryptography: {e}")

try:
    import cloudscraper
    cloudscraper.CloudScraper()
except Exception as e:
    errors.append(f"cloudscraper: {e}")

try:
    from fuzzywuzzy import fuzz
    fuzz.ratio("a", "b")
except Exception as e:
    errors.append(f"fuzzywuzzy: {e}")

try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
except Exception as e:
    errors.append(f"rich: {e}")

try:
    import requests
    from requests_futures.sessions import FuturesSession
except Exception as e:
    errors.append(f"requests: {e}")

try:
    import qrcode
    qr = qrcode.QRCode()
    qr.add_data("test")
    qr.make()
except Exception as e:
    errors.append(f"qrcode: {e}")

if errors:
    for err in errors:
        print(f"FAIL: {err}", file=sys.stderr)
    sys.exit(1)
else:
    print("All imports OK")
