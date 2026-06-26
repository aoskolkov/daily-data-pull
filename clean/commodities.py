"""
Clean Datastream commodity prices to wide format.

Sources (all from tr_ds_comds via wrds_ds_comds adapter)
---------------------------------------------------------
  data/ds_metals/          Precious + LME base metals
  data/ds_energy_comds/    Brent, natural gas, heating oil, gasoline
  data/ds_agri_comds/      Wheat, corn, soybeans, coffee, cocoa, sugar, cotton
  data/ds_comdy_indices/   S&P GSCI family + Refinitiv CRB

Raw schema per dataset
  date_, dsmnemonic, name, comdesc, unitdesc, isocur, close_, dsp

Price column: close_ is primary; dsp (Datastream price) fills gaps where close_
is null — some series store prices only in dsp.

Output
------
  output/commodities/metals_wide.parquet / .csv
  output/commodities/energy_wide.parquet / .csv
  output/commodities/agri_wide.parquet   / .csv
  output/commodities/indices_wide.parquet / .csv
  output/commodities/commodities_meta.csv    mnemonic metadata lookup

Usage
-----
  python clean/commodities.py
  python clean/commodities.py --no-csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DATASETS: dict[str, str] = {
    "ds_metals":        "metals",
    "ds_energy_comds":  "energy",
    "ds_agri_comds":    "agri",
    "ds_comdy_indices": "indices",
}

DEFAULT_STORAGE = "data"
DEFAULT_OUTPUT  = "output/commodities"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean Datastream commodity prices to wide Parquet/CSV.")
    p.add_argument("--storage-root", default=DEFAULT_STORAGE)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def load_dataset(dataset_name: str, storage_root: str) -> pd.DataFrame | None:
    path = Path(storage_root) / dataset_name
    if not path.exists():
        print(f"  {dataset_name}: not pulled yet — skipping")
        return None
    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    # Normalize date
    df["date"] = pd.to_datetime(df["date_"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date", "dsmnemonic"])
    # Price: close_ primary, dsp fallback
    df["price"] = df["close_"].where(df["close_"].notna(), df.get("dsp"))
    df = df.dropna(subset=["price"])
    print(f"  {dataset_name}: {len(df):,} rows, "
          f"{df['dsmnemonic'].nunique()} series, "
          f"{df['date'].min().date()} – {df['date'].max().date()}")
    return df


def to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot to date × mnemonic wide table. Last value wins on duplicate (date, mnemonic)."""
    return (
        df.groupby(["date", "dsmnemonic"])["price"]
        .last()
        .unstack("dsmnemonic")
        .sort_index()
        .rename_axis(index="date", columns=None)
        .reset_index()
    )


def build_meta(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """One metadata row per mnemonic across all datasets."""
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    meta_cols = [c for c in ["dsmnemonic", "name", "comdesc", "unitdesc", "isocur"] if c in combined.columns]
    return (
        combined[meta_cols]
        .drop_duplicates("dsmnemonic")
        .sort_values("dsmnemonic")
        .reset_index(drop=True)
    )


def save(df: pd.DataFrame, stem: Path, write_csv: bool) -> None:
    stem.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(stem.with_suffix(".parquet"), index=False)
    print(f"  -> {stem.with_suffix('.parquet')}")
    if write_csv:
        df.to_csv(stem.with_suffix(".csv"), index=False)
        print(f"  -> {stem.with_suffix('.csv')}")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)

    all_frames: list[pd.DataFrame] = []
    any_loaded = False

    for dataset_name, label in DATASETS.items():
        df = load_dataset(dataset_name, args.storage_root)
        if df is None:
            continue
        any_loaded = True
        all_frames.append(df)
        wide = to_wide(df)
        n_series = wide.shape[1] - 1  # exclude date col
        print(f"  {label}_wide: {len(wide):,} dates × {n_series} series")
        save(wide, out_dir / f"{label}_wide", args.csv)

    if not any_loaded:
        print(
            "No commodity data found. Pull first:\n"
            "  python wrdsdl.py pull ds_metals ds_energy_comds ds_agri_comds ds_comdy_indices",
            file=sys.stderr,
        )
        sys.exit(1)

    meta = build_meta(all_frames)
    if not meta.empty:
        meta_path = out_dir / "commodities_meta.csv"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta.to_csv(meta_path, index=False)
        print(f"  -> {meta_path}  ({len(meta)} series)")


if __name__ == "__main__":
    main()
