"""
Clean VIX term structure and SVIX data.

VIX sources (FRED, daily):
  data/vix/    CBOE VIX  (30-day)
  data/vix9d/  CBOE VXST (9-day)
  data/vix3m/  CBOE VXV  (3-month)
  data/vix6m/  CBOE VXMT (6-month)
  data/vvix/   CBOE VVIX (vol-of-vol)

SVIX source (Martin 2017, file download):
  data/svix/   as stored by wrdsdl after reading downloads/svix.csv

All VIX-family series are annualised percentage points (e.g. 20 = 20% p.a.).
SVIX is typically stored as a decimal (e.g. 0.20); this script converts to
percentage points to match the VIX convention, but prints both so you can verify.

Output
------
  output/vol/vol_daily.parquet    wide: (date, vix, vix9d, vix3m, vix6m, vvix, svix)
  output/vol/vol_daily.csv
  output/vol/vol_long.parquet     long: (date, series, value)

Usage
-----
  python clean/vol.py
  python clean/vol.py --no-svix       # skip SVIX if file not yet downloaded
  python clean/vol.py --no-csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

DEFAULT_OUTPUT = "output/vol"
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
    p = argparse.ArgumentParser(description="Clean VIX term structure and SVIX to a daily wide file.")
    p.add_argument("--storage-root", default=STORAGE_ROOT)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--no-svix", action="store_false", dest="svix",
                   help="Skip SVIX even if data is present")
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(svix=True, csv=True)
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


def load_svix(storage_root: str) -> pd.DataFrame | None:
    """
    SVIX from Martin (2017). File may use various column names and units.
    Detects the value column and normalises to annualised % (×100 if decimal).
    """
    path = Path(storage_root) / "svix"
    if not path.exists():
        print("  svix: not pulled yet — skipping  "
              "(place Martin's file at downloads/svix.csv and run: python wrdsdl.py pull svix)")
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    # Identify the SVIX value column: prefer 'svix', then any numeric non-id column
    skip = {"date", "source", "series"}
    candidates = [c for c in df.columns if c not in skip and pd.api.types.is_numeric_dtype(df[c])]
    if not candidates:
        print("  svix: no numeric value column found — skipping")
        return None

    svix_col = "svix" if "svix" in candidates else candidates[0]
    series = pd.to_numeric(df[svix_col], errors="coerce")

    # Normalise units: if values look like decimals (< 2 for the median), ×100 to get %
    median_val = series.median()
    if pd.notna(median_val) and median_val < 2.0:
        print(f"  svix: median={median_val:.4f} — looks like decimal; converting ×100 to annualised %")
        series = series * 100
    else:
        print(f"  svix: median={median_val:.2f} — treating as annualised % already")

    result = pd.DataFrame({"date": df["date"], "svix": series}).dropna().sort_values("date").reset_index(drop=True)
    print(f"  svix: {len(result):,} obs, "
          f"{result['date'].min().date()} – {result['date'].max().date()}")
    return result


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Load all series ───────────────────────────────────────────────────────
    print("Loading VIX series...")
    frames: list[pd.DataFrame] = []
    for dataset_name, col_name in VIX_SERIES:
        df = load_fred_series(dataset_name, col_name, args.storage_root)
        if df is not None:
            frames.append(df)

    if args.svix:
        df_svix = load_svix(args.storage_root)
        if df_svix is not None:
            frames.append(df_svix)

    if not frames:
        print("No data loaded. Pull VIX series first:\n"
              "  python wrdsdl.py pull vix vix3m vix6m vvix")
        return

    # ── Merge to wide ─────────────────────────────────────────────────────────
    wide = frames[0]
    for df in frames[1:]:
        wide = wide.merge(df, on="date", how="outer")
    wide = wide.sort_values("date").reset_index(drop=True)

    print(f"\nWide: {len(wide):,} dates × {wide.shape[1] - 1} series  "
          f"({wide['date'].min().date()} – {wide['date'].max().date()})")

    # Quick sanity check on VIX/SVIX relationship (vix² ≥ svix² always)
    if "vix" in wide.columns and "svix" in wide.columns:
        common = wide[["date", "vix", "svix"]].dropna()
        if not common.empty:
            violations = (common["vix"] < common["svix"]).sum()
            if violations > 0:
                print(f"  WARNING: {violations} dates where vix < svix — check units/convention")
            else:
                vrp_median = (common["vix"] ** 2 - common["svix"] ** 2).median()
                print(f"  VIX² - SVIX² (variance risk premium) median: {vrp_median:.2f} (pct² annual)")

    pq_path = out_dir / "vol_daily.parquet"
    wide.to_parquet(pq_path, index=False)
    print(f"Saved: {pq_path.resolve()}")

    if args.csv:
        csv_path = out_dir / "vol_daily.csv"
        wide.to_csv(csv_path, index=False)
        print(f"Saved: {csv_path.resolve()}")

    # ── Long format ───────────────────────────────────────────────────────────
    id_cols = ["date"]
    val_cols = [c for c in wide.columns if c != "date"]
    long = wide.melt(id_vars=id_cols, value_vars=val_cols, var_name="series", value_name="value").dropna()
    long = long.sort_values(["series", "date"]).reset_index(drop=True)
    long_path = out_dir / "vol_long.parquet"
    long.to_parquet(long_path, index=False)
    print(f"Saved: {long_path.resolve()}")


if __name__ == "__main__":
    main()
