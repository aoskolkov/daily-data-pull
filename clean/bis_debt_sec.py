"""
Clean script for BIS international debt securities data.

Input:  data/bis_debt_sec/   (amounts outstanding, all maturities; see datasets.yaml)
Output: macrodata/bis_debt_sec/bis_debt_sec_by_nat_wide.{parquet,csv}   — by issuer nationality
        macrodata/bis_debt_sec/bis_debt_sec_by_res_wide.{parquet,csv}   — by issuer residence
        macrodata/bis_debt_sec/bis_debt_sec_meta.csv

The BIS data has two key country dimensions:
  issuer_res  — country where the issuer is resident
  issuer_nat  — country of the issuer's ultimate nationality

"3P" is BIS code "all countries excluding residents"; paired with a country in the
other dimension it gives the published aggregate:

"By nationality" (issuer_res='3P', issuer_nat=<country>): international debt issued
by entities of that nationality, wherever they are resident. The series usually
cited in reports (US, 2026-Q2: ~$7.1tn).

"By residence" (issuer_res=<country>, issuer_nat='3P'): international debt issued
by entities resident in that country, whatever their nationality (US: ~$3.1tn).

Each country also has rows by issuer sector (issuer_bus_imm/ult) and currency group
(issue_cur_group D/F); those are sub-totals, so only the all-sector ('1'),
all-currency ('A') row is kept. Summing every row (as before 2026-09-19) counted
the same debt several times.

Amounts are USD millions (unit_mult=6, unit_measure=USD).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "bis_debt_sec"
OUT  = ROOT / "macrodata" / "bis_debt_sec"

_ISO2_RE = r'^[A-Z]{2}$'   # strict 2-letter codes; excludes aggregates like 1C, 3P, 4T


def _is_iso2(s: pd.Series) -> pd.Series:
    return s.str.match(_ISO2_RE, na=False)


def load() -> pd.DataFrame:
    if not DATA.exists():
        print(f"  Data not found at {DATA}. Run: python wrdsdl.py pull bis_debt_sec", file=sys.stderr)
        sys.exit(1)
    df = pd.read_parquet(DATA)
    df["date"] = pd.to_datetime(df["date"])
    return df


def make_wide(df: pd.DataFrame, country_col: str, filter_col: str, filter_val: str) -> pd.DataFrame:
    """Pivot to wide: date × country."""
    total = (
        (df[filter_col] == filter_val) & _is_iso2(df[country_col])
        & (df["issuer_bus_imm"].astype(str) == "1") & (df["issuer_bus_ult"].astype(str) == "1")
        & (df["issue_cur_group"].astype(str) == "A")
    )
    sub = df[total].dropna(subset=["obs_value"])
    # One total row per country and quarter; last() only absorbs partition-boundary repeats.
    agg = sub.groupby(["date", country_col], as_index=False)["obs_value"].last()
    wide = agg.pivot(index="date", columns=country_col, values="obs_value").sort_index()
    wide.columns.name = None
    return wide


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Clean BIS international debt securities")
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV output")
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)

    df = load()
    print(f"  Loaded {len(df):,} rows from {DATA}")

    # By nationality (issuer_res='3P'): securities of entities from that country, issued abroad
    by_nat = make_wide(df, country_col="issuer_nat", filter_col="issuer_res", filter_val="3P")
    print(f"  By nationality: {by_nat.shape[1]} countries, {len(by_nat)} quarters  ({by_nat.index.min().date()} – {by_nat.index.max().date()})")

    # By residence (issuer_nat='3P'): securities issued by entities resident in that country
    by_res = make_wide(df, country_col="issuer_res", filter_col="issuer_nat", filter_val="3P")
    print(f"  By residence:   {by_res.shape[1]} countries, {len(by_res)} quarters  ({by_res.index.min().date()} – {by_res.index.max().date()})")

    by_nat.to_parquet(OUT / "bis_debt_sec_by_nat_wide.parquet")
    by_res.to_parquet(OUT / "bis_debt_sec_by_res_wide.parquet")
    print("  Saved parquet files.")

    if not args.no_csv:
        by_nat.to_csv(OUT / "bis_debt_sec_by_nat_wide.csv")
        by_res.to_csv(OUT / "bis_debt_sec_by_res_wide.csv")
        print("  Saved CSV files.")

    # Metadata
    meta = pd.DataFrame({
        "file":          ["bis_debt_sec_by_nat_wide", "bis_debt_sec_by_res_wide"],
        "countries":     [by_nat.shape[1],            by_res.shape[1]],
        "quarters":      [len(by_nat),                len(by_res)],
        "date_min":      [str(by_nat.index.min().date()), str(by_res.index.min().date())],
        "date_max":      [str(by_nat.index.max().date()), str(by_res.index.max().date())],
        "units":         ["USD millions",              "USD millions"],
        "description":   [
            "Intl debt securities outstanding by issuer nationality (issuer_res=3P)",
            "Intl debt securities outstanding by issuer residence (issuer_nat=3P)",
        ],
    })
    meta.to_csv(OUT / "bis_debt_sec_meta.csv", index=False)
    print("  Saved metadata.")


if __name__ == "__main__":
    main()
