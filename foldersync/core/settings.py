"""Persist UI settings (last sources, modes, window geometry) across runs.

Stored as JSON under the user config dir. Secrets (password/passphrase) are
never written — SSH auth relies on keys/agent.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict


def config_path() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, "foldersync", "settings.json")


def load() -> Dict[str, Any]:
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data: Dict[str, Any]) -> None:
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
