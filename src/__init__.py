"""eNkrypt's Steam Redeemer - Humble Bundle key extraction and Steam redemption."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

__version__ = "2026.08.17"
APP_NAME = "eNkrypt's Steam Redeemer"

# Project root — works both from source and as a PyInstaller binary
if getattr(sys, "frozen", False):
    ROOT_DIR = Path(os.path.dirname(sys.executable))
else:
    ROOT_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# State directory for session cookies
STATE_DIR = ROOT_DIR / ".state"
STATE_DIR.mkdir(exist_ok=True)

HUMBLE_COOKIE_FILE = STATE_DIR / "humble.cookies"
STEAM_COOKIE_FILE = STATE_DIR / "steam.cookies"
CONFIG_FILE = ROOT_DIR / "config.yaml"


def load_config() -> dict[str, Any]:
    """Load config.yaml. Returns empty dict if missing."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        import yaml
    except ImportError:
        # Fall back to basic parsing if PyYAML not installed
        config: dict[str, Any] = {}
        with open(CONFIG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    key, _, val = line.partition(":")
                    val = val.strip()
                    if val.lower() in ("true", "false"):
                        val = val.lower() == "true"
                    elif val.isdigit():
                        val = int(val)
                    config[key.strip()] = val
        return config
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict[str, Any]) -> None:
    """Write config dict to config.yaml."""
    try:
        import yaml
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
    except ImportError:
        with open(CONFIG_FILE, "w") as f:
            for key, val in config.items():
                f.write(f"{key}: {val}\n")
