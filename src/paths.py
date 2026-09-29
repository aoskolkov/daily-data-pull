"""
Where raw data and clean outputs live.

Resolution order (first hit wins):
  1. environment variables DDP_DATA_ROOT / DDP_MACRODATA_ROOT
  2. config/paths.yaml (machine-specific, not tracked; see config/paths.example.yaml)
  3. ./data and ./macrodata inside the repo (the default — a fresh clone just works)

Keeping the roots outside the repo lets the ~1 GB of data live in Dropbox (or any
other synced folder) while git carries only code.

clean/_paths.py is the same resolver for the standalone clean scripts.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "paths.yaml"


def _from_config(key: str) -> str | None:
    if not CONFIG_FILE.exists():
        return None
    try:
        import yaml
        cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:                      # malformed file: fall back to defaults
        print(f"WARNING: could not read {CONFIG_FILE}: {exc}")
        return None
    value = cfg.get(key)
    return str(value) if value else None


def _root(env_var: str, config_key: str, default: str) -> Path:
    value = os.getenv(env_var) or _from_config(config_key) or default
    path = Path(value).expanduser()
    return path if path.is_absolute() else (ROOT / path)


def data_root() -> Path:
    """Directory holding one subfolder of raw Parquet per dataset."""
    return _root("DDP_DATA_ROOT", "data_root", "data")


def macrodata_root() -> Path:
    """Directory the clean scripts write to."""
    return _root("DDP_MACRODATA_ROOT", "macrodata_root", "macrodata")
