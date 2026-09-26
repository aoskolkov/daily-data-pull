"""
Clean script for IMF World Economic Outlook (WEO) data.

Input:  data/imf_weo/
Output: macrodata/imf_weo/weo_{subject}_wide.{parquet,csv}  — one file per subject:
            index date (annual, Jan 1 of each year) × country-name columns
        macrodata/imf_weo/weo_long.{parquet,csv}  — all subjects, long:
            (date, country, subject_code, subject_descriptor, units, value)
        macrodata/imf_weo/weo_meta.csv  — subject → descriptor, units, coverage

The WEO data is an annual panel: 196 countries × 15 subjects × 50 years
(1980–2029, including IMF projections). Units differ by subject — see the units
column: e.g. GGXWDG_NGDP is % of GDP, GGXWDG is national currency (billions),
NGDPD is billions of USD.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "imf_weo"
OUT  = ROOT / "macrodata" / "imf_weo"


def load() -> pd.DataFrame:
    if not DATA.exists():
        print(f"  Data not found at {DATA}. Run: python wrdsdl.py pull imf_weo", file=sys.stderr)
        sys.exit(1)
    df = pd.read_parquet(DATA)
    df["date"] = pd.to_datetime(df["date"])
    return df


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Clean IMF WEO data")
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV output")
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)

    df = load()
    print(f"  Loaded {len(df):,} rows from {DATA}")

    subjects = sorted(df["subject_code"].unique())
    countries = sorted(df["country"].unique())
    dates = sorted(df["date"].unique())
    print(f"  {len(subjects)} subjects × {len(countries)} countries × {len(dates)} years  ({dates[0].year}–{dates[-1].year})")

    # Write one wide file per subject (date × country)
    for subj in subjects:
        sub = df[df["subject_code"] == subj]
        desc = sub["subject_descriptor"].iloc[0] if len(sub) else subj
        units = sub["units"].iloc[0] if len(sub) else ""
        wide = (
            sub.groupby(["date", "country"])["value"]
            .last()
            .unstack("country")
            .sort_index()
        )
        wide.columns.name = None
        wide.to_parquet(OUT / f"weo_{subj.lower()}_wide.parquet")
        if not args.no_csv:
            wide.to_csv(OUT / f"weo_{subj.lower()}_wide.csv")
        print(f"    {subj:15s}  {wide.shape[1]:3d} countries  {wide.shape[0]:3d} years  | {desc[:55]}")

    # Write combined long file (parquet + CSV) for easy inspection (not pivoted, all subjects)
    summary_cols = ["date", "country", "subject_code", "subject_descriptor", "units", "value"]
    keep = [c for c in summary_cols if c in df.columns]
    df_out = df[keep].sort_values(["subject_code", "country", "date"]).reset_index(drop=True)
    df_out.to_parquet(OUT / "weo_long.parquet")
    if not args.no_csv:
        df_out.to_csv(OUT / "weo_long.csv", index=False)
    print(f"  Saved weo_long.parquet ({len(df_out):,} rows)")

    # Metadata
    meta_rows = []
    for subj in subjects:
        sub = df[df["subject_code"] == subj]
        meta_rows.append({
            "subject_code":       subj,
            "subject_descriptor": sub["subject_descriptor"].iloc[0] if len(sub) else "",
            "units":              sub["units"].iloc[0] if len(sub) else "",
            "countries":          sub["country"].nunique(),
            "years":              sub["date"].nunique(),
            "year_min":           sub["date"].min().year if len(sub) else None,
            "year_max":           sub["date"].max().year if len(sub) else None,
        })
    pd.DataFrame(meta_rows).to_csv(OUT / "weo_meta.csv", index=False)
    print("  Saved weo_meta.csv")


if __name__ == "__main__":
    main()
