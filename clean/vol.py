"""
Clean VIX term structure data.

VIX sources (FRED, daily):
  data/vix/    CBOE VIX  (30-day)
  data/vix3m/  CBOE VIX3M, formerly VXV (3-month)
Also loaded if present, but disabled in config/datasets.yaml (FRED download broken):
  data/vix9d/  CBOE VXST (9-day)
  data/vix6m/  CBOE VXMT (6-month)
  data/vvix/   CBOE VVIX (vol-of-vol)

All series are annualised percentage points (e.g. 20 = 20% p.a.).

Output
------
  macrodata/vol/vol_daily.parquet    wide: (date, vix, vix3m) — plus vix9d/vix6m/vvix if pulled
  macrodata/vol/vol_daily.csv
  macrodata/vol/vol_long.parquet     long: (date, series, value)

Usage
-----
  python clean/vol.py
  python clean/vol.py --no-csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

DEFAULT_OUTPUT = "macrodata/vol"
STORAGE_ROOT = "data"

# (dataset_name, output column name)
VIX_SERIES: list[tuple[str, str]] = [
    ("vix",   "vix"),
    ("vix9d", "vix9d"),
    ("vix3m", "vix3m"),
    ("vix6m", "vix6m"),
    ("vvix",  "vvix"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean VIX term structure to a daily wide file.")
    p.add_argument("--storage-root", default=STORAGE_ROOT)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def load_fred_series(dataset_name: str, col_name: str, storage_root: str) -> pd.DataFrame | None:
    """
    FRED adapter output schema: date, series, value, source
    Returns (date, col_name) DataFrame.
    """
    path = Path(storage_root) / dataset_name
    if not path.exists():
        print(f"  {dataset_name}: not pulled yet — skipping")
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    val_col = "value" if "value" in df.columns else next(
        (c for c in df.columns if c not in ("date", "series", "source")), None
    )
    if not val_col:
        print(f"  {dataset_name}: could not find value column — skipping")
        return None

    df[col_name] = pd.to_numeric(df[val_col], errors="coerce")
    result = df[["date", col_name]].dropna().sort_values("date").reset_index(drop=True)
    print(f"  {dataset_name} ({col_name}): {len(result):,} obs, "
          f"{result['date'].min().date()} – {result['date'].max().date()}")
    return result


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading VIX series...")
    frames: list[pd.DataFrame] = []
    for dataset_name, col_name in VIX_SERIES:
        df = load_fred_series(dataset_name, col_name, args.storage_root)
        if df is not None:
            frames.append(df)

    if not frames:
        print("No data loaded. Pull VIX series first:\n"
              "  python wrdsdl.py pull vix vix3m")
        return

    wide = frames[0]
    for df in frames[1:]:
        wide = wide.merge(df, on="date", how="outer")
    wide = wide.sort_values("date").reset_index(drop=True)

    print(f"\nWide: {len(wide):,} dates × {wide.shape[1] - 1} series  "
          f"({wide['date'].min().date()} – {wide['date'].max().date()})")

    pq_path = out_dir / "vol_daily.parquet"
    wide.to_parquet(pq_path, index=False)
    print(f"Saved: {pq_path.resolve()}")

    if args.csv:
        csv_path = out_dir / "vol_daily.csv"
        wide.to_csv(csv_path, index=False)
        print(f"Saved: {csv_path.resolve()}")

    id_cols = ["date"]
    val_cols = [c for c in wide.columns if c != "date"]
    long = wide.melt(id_vars=id_cols, value_vars=val_cols, var_name="series", value_name="value").dropna()
    long = long.sort_values(["series", "date"]).reset_index(drop=True)
    long_path = out_dir / "vol_long.parquet"
    long.to_parquet(long_path, index=False)
    print(f"Saved: {long_path.resolve()}")


if __name__ == "__main__":
    main()
