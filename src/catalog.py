"""Pull provenance catalog — one JSON-Lines entry per pull."""

from __future__ import annotations

import json
from pathlib import Path

_CATALOG_FILE = "_catalog.jsonl"


def update_catalog(meta: dict, storage_root: str = "./data") -> None:
    """Append a pull record to the catalog."""
    p = Path(storage_root) / _CATALOG_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(meta, default=str) + "\n")


def read_catalog(storage_root: str = "./data") -> list[dict]:
    p = Path(storage_root) / _CATALOG_FILE
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def print_catalog(storage_root: str = "./data") -> None:
    entries = read_catalog(storage_root)
    if not entries:
        print("Catalog is empty. Run 'python wrdsdl.py pull <dataset>' first.")
        return

    by_dataset: dict[str, list[dict]] = {}
    for entry in entries:
        by_dataset.setdefault(entry.get("dataset", "?"), []).append(entry)

    for dataset, pulls in by_dataset.items():
        latest = pulls[-1]
        rows = latest.get("rows", "?")
        print(f"\n{dataset}")
        print(f"  source:   {latest.get('source', '?')}")
        print(f"  rows:     {rows:,}" if isinstance(rows, int) else f"  rows:     {rows}")
        print(f"  pulled:   {latest.get('pulled_at', '?')}")
        print(f"  coverage: {latest.get('date_min', '?')} -> {latest.get('date_max', '?')}")
        print(f"  n_pulls:  {len(pulls)}")
