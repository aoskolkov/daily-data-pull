"""
Clean script for US Treasury TIC Major Foreign Holders data.

Input:  data/tic_foreign_holders/
Output: macrodata/tic_holdings_wide.{parquet,csv}   — date × country (billions USD)
        macrodata/tic_meta.csv

Source: mfhhis01.txt (2000–present historical archive) + mfh.txt (rolling current).
Holdings in billions USD. ~57 countries, monthly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "tic_foreign_holders"
OUT  = ROOT / "macrodata" / "tic"


def load() -> pd.DataFrame:
    if not DATA.exists():
        print(f"  Data not found at {DATA}. Run: python wrdsdl.py pull tic_foreign_holders", file=sys.stderr)
        sys.exit(1)
    df = pd.read_parquet(DATA)
    df["date"] = pd.to_datetime(df["date"])
    return df


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Clean TIC foreign holders data")
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV output")
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)

    df = load()
    print(f"  Loaded {len(df):,} rows from {DATA}")

    # Deduplicate (incremental pulls can overlap on the boundary month)
    df = df.groupby(["date", "country"], as_index=False)["holdings_bln_usd"].last()

    wide = (
        df.pivot(index="date", columns="country", values="holdings_bln_usd")
        .sort_index()
    )
    wide.columns.name = None

    n_countries = wide.shape[1]
    n_months    = len(wide)
    date_min    = wide.index.min().date()
    date_max    = wide.index.max().date()
    print(f"  {n_countries} countries, {n_months} months  ({date_min} – {date_max})")

    wide.to_parquet(OUT / "tic_holdings_wide.parquet")
    if not args.no_csv:
        wide.to_csv(OUT / "tic_holdings_wide.csv")
    print("  Saved tic_holdings_wide.parquet")

    meta = pd.DataFrame([{
        "file":        "tic_holdings_wide",
        "countries":   n_countries,
        "months":      n_months,
        "date_min":    str(date_min),
        "date_max":    str(date_max),
        "units":       "billions USD",
        "source":      "US Treasury TIC Major Foreign Holders (mfh.txt)",
        "note":        "Historical archive from mfhhis01.txt (2000-present) + current mfh.txt",
    }])
    meta.to_csv(OUT / "tic_meta.csv", index=False)
    print("  Saved tic_meta.csv")


if __name__ == "__main__":
    main()
