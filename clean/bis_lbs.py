"""
Clean BIS Locational Banking Statistics to wide format.

Source: data/bis_lbs/ — BIS WS_LBS_D_PUB, quarterly.
Filter: total cross-border claims, all instruments, all-currency USD-equivalent,
        all counterpart sectors (A), all counterpart countries aggregated (5J),
        immediate counterparty basis (N).

Output:
  macrodata/bis_lbs/bis_lbs_wide.{parquet,csv}   date × reporting-country ISO2, USD millions

Usage:
  python clean/bis_lbs.py
  python clean/bis_lbs.py --no-csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

SRC = Path("data/bis_lbs")
OUT = Path("macrodata/bis_lbs/bis_lbs_wide")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean BIS LBS cross-border bank claims to wide format.")
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not SRC.exists():
        print("SKIP: data/bis_lbs not found (run: python wrdsdl.py pull bis_lbs)")
        return

    df = pd.read_parquet(SRC)
    df.columns = df.columns.str.lower()

    df["date"] = pd.to_datetime(df["date"])

    # Total cross-border claims: all counterpart sectors, all counterpart countries
    # aggregated, immediate-counterparty basis. Excludes the 5A (all-reporters) aggregate.
    mask = (
        (df["l_cp_sector"] == "A") &
        (df["l_cp_country"] == "5J") &
        (df["l_pos_type"] == "N") &
        (df["l_rep_cty"] != "5A")
    )
    df = df[mask].copy()

    # Apply unit multiplier (unit_mult=6 → values in USD millions already)
    df["obs_value"] = pd.to_numeric(df["obs_value"], errors="coerce")
    df = df.dropna(subset=["obs_value", "l_rep_cty"])

    df = (
        df.sort_values(["date", "l_rep_cty"])
        .groupby(["date", "l_rep_cty"], as_index=False)["obs_value"]
        .last()
    )

    wide = (
        df.pivot_table(index="date", columns="l_rep_cty", values="obs_value", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .sort_values("date")
    )

    n_countries = wide.shape[1] - 1
    print(f"BIS LBS claims: {len(wide):,} quarters × {n_countries} reporting countries | "
          f"{wide['date'].min().date()} – {wide['date'].max().date()}")
    print(f"  reporting countries: {sorted(c for c in wide.columns if c != 'date')}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wide.to_parquet(OUT.with_suffix(".parquet"), index=False)
    print(f"  -> {OUT.with_suffix('.parquet')}")
    if args.csv:
        wide.to_csv(OUT.with_suffix(".csv"), index=False)
        print(f"  -> {OUT.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
