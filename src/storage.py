"""Partitioned Parquet storage and _meta.json sidecars."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def write_parquet(
    df: pd.DataFrame,
    dataset_name: str,
    partition_col: str | None = None,
    storage_root: str = "./data",
    append: bool = False,
) -> Path:
    """Write DataFrame to year-partitioned Parquet. Returns the dataset directory.

    append=False (full pull) replaces every year partition the data touches.
    append=True (incremental pull) merges into the existing partitions: stored
    rows dated on or after the first date in `df` are replaced, earlier rows are
    kept. This makes a re-run idempotent and absorbs the overlap from adapters
    whose watermark filter is inclusive (BIS startPeriod, FRED observation_start).
    """
    out_dir = Path(storage_root) / dataset_name
    out_dir.mkdir(parents=True, exist_ok=True)

    if partition_col and partition_col in df.columns:
        df = df.copy()
        dates = pd.to_datetime(df[partition_col], errors="coerce")
        df["_year"] = dates.dt.year
        cutoff = dates.min()
        for year, group in df.groupby("_year"):
            if pd.isna(year):
                continue
            year_dir = out_dir / f"year={int(year)}"
            year_dir.mkdir(exist_ok=True)
            path = year_dir / "part-0.parquet"
            group = group.drop(columns=["_year"])
            if append and path.exists():
                existing = pd.read_parquet(path)
                keep = pd.to_datetime(existing[partition_col], errors="coerce") < cutoff
                group = pd.concat([existing[keep], group], ignore_index=True)
            group.to_parquet(path, index=False)
    else:
        path = out_dir / "part-0.parquet"
        if append and path.exists():
            df = pd.concat([pd.read_parquet(path), df], ignore_index=True).drop_duplicates()
        df.to_parquet(path, index=False)

    return out_dir


def write_sidecar(meta: dict, dataset_name: str, storage_root: str = "./data") -> None:
    """Write _meta.json next to the dataset directory."""
    meta_path = Path(storage_root) / dataset_name / "_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta["pulled_at"] = datetime.now(timezone.utc).isoformat()
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)


def load_parquet(dataset_name: str, storage_root: str = "./data") -> pd.DataFrame:
    """Load all partitions for a dataset into a single DataFrame."""
    dataset_dir = Path(storage_root) / dataset_name
    if not dataset_dir.exists():
        return pd.DataFrame()
    return pd.read_parquet(dataset_dir)
