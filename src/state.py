"""Per-dataset incremental watermarks, stored in data/_state.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_STATE_FILE = "_state.json"


def _path(storage_root: str) -> Path:
    return Path(storage_root) / _STATE_FILE


def load_watermark(dataset_name: str, storage_root: str = "./data"):
    """Return the stored watermark for a dataset, or None if never pulled."""
    p = _path(storage_root)
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        state = json.load(f)
    return state.get(dataset_name, {}).get("watermark")


def save_watermark(dataset_name: str, value, storage_root: str = "./data") -> None:
    """Persist a watermark for a dataset."""
    p = _path(storage_root)
    state: dict = {}
    if p.exists():
        with p.open(encoding="utf-8") as f:
            state = json.load(f)
    state.setdefault(dataset_name, {})
    state[dataset_name]["watermark"] = str(value)
    state[dataset_name]["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def clear_watermark(dataset_name: str, storage_root: str = "./data") -> None:
    """Remove watermark so the next pull performs a full refresh."""
    p = _path(storage_root)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        state = json.load(f)
    state.pop(dataset_name, None)
    with p.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
