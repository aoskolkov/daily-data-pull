"""
Data locations for the clean scripts (standalone twin of src/paths.py — the clean
scripts deliberately do not import from src/).

Resolution order: DDP_DATA_ROOT / DDP_MACRODATA_ROOT env vars, then
config/paths.yaml, then ./data and ./macrodata inside the repo.

Usage:
    from _paths import DATA_ROOT, MACRODATA_ROOT
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "paths.yaml"


def _root(env_var: str, config_key: str, default: str) -> Path:
    value = os.getenv(env_var)
    if not value and CONFIG_FILE.exists():
        try:
            import yaml
            value = (yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}).get(config_key)
        except Exception as exc:
            print(f"WARNING: could not read {CONFIG_FILE}: {exc}")
    path = Path(str(value)).expanduser() if value else Path(default)
    return path if path.is_absolute() else (ROOT / path)


DATA_ROOT = _root("DDP_DATA_ROOT", "data_root", "data")
MACRODATA_ROOT = _root("DDP_MACRODATA_ROOT", "macrodata_root", "macrodata")
