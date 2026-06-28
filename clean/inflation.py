"""
Clean inflation data from raw downloads.

Sources
-------
  data/wb_cpi/        World Bank CPI index (2010=100), annual, ~180 countries
  data/wb_inflation/  World Bank CPI inflation rate (%), annual, ~180 countries
  data/oecd_cpi/      OECD CPI monthly, ~40 countries

Outputs
-------
  macrodata/inflation/wb_cpi_wide.parquet      dates × countries (CPI level, annual)
  macrodata/inflation/wb_cpi_wide.csv
  macrodata/inflation/wb_inflation_wide.parquet dates × countries (inflation %, annual)
  macrodata/inflation/wb_inflation_wide.csv
  macrodata/inflation/oecd_cpi_wide.parquet    dates × countries (CPI level, monthly)
  macrodata/inflation/oecd_cpi_wide.csv

All wide outputs: rows = dates, columns = ISO3 country codes (iso3c).

Usage
-----
  python clean/inflation.py
  python clean/inflation.py --no-csv
  python clean/inflation.py --source wb       # only World Bank
  python clean/inflation.py --source oecd     # only OECD
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_OUTPUT = "macrodata/inflation"

WB_CPI_INPUT = "data/wb_cpi"
WB_INF_INPUT = "data/wb_inflation"
OECD_INPUT = "data/oecd_cpi"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean inflation data to wide country format.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--source", choices=["wb", "oecd", "all"], default="all",
                        help="Which source(s) to process (default: all)")
    parser.add_argument("--no-csv", action="store_false", dest="csv", help="Skip CSV output")
    parser.set_defaults(csv=True)
    return parser.parse_args()


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_worldbank(input_dir: str, label: str) -> pd.DataFrame | None:
    """
    World Bank raw schema: date, country_name, iso2c, iso3c, indicator, value, source
    Returns long DataFrame ready for pivot.
    """
    path = Path(input_dir)
    if not path.exists():
        print(f"Skipping {label}: not yet pulled (run: python wrdsdl.py pull {Path(input_dir).name})")
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "value"])

    n_countries = df["country_name"].nunique() if "country_name" in df.columns else "?"
    print(f"{label}: {len(df):,} obs, {n_countries} countries, "
          f"{df['date'].min().year}–{df['date'].max().year}")
    return df


def load_oecd(input_dir: str) -> pd.DataFrame | None:
    """
    OECD raw schema: date, country_iso3, indicator, value, source
    Returns long DataFrame ready for pivot.
    """
    path = Path(input_dir)
    if not path.exists():
        print("Skipping oecd_cpi: not yet pulled (run: python wrdsdl.py pull oecd_cpi)")
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "value"])

    n_countries = df["country_iso3"].nunique() if "country_iso3" in df.columns else "?"
    print(f"OECD CPI: {len(df):,} obs, {n_countries} countries, "
          f"{df['date'].min().date()} – {df['date'].max().date()}")
    return df


# ── Normalization ─────────────────────────────────────────────────────────────

def wb_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot World Bank long data to wide: rows = year (int), columns = iso3c codes.
    Falls back to iso2c then country_name if iso3c is missing.
    """
    for candidate in ("iso3c", "iso2c", "country_name"):
        if candidate in df.columns and df[candidate].notna().any():
            col_id = candidate
            break
    else:
        col_id = df.columns[-1]

    wide = (
        df.pivot_table(index="date", columns=col_id, values="value", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .rename(columns={"date": "year"})
        .sort_values("year")
    )
    wide["year"] = wide["year"].dt.year
    return wide


def oecd_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot OECD long data to wide: rows = date, columns = ISO3 codes."""
    col_id = "country_iso3" if "country_iso3" in df.columns else "country"
    wide = (
        df.pivot_table(index="date", columns=col_id, values="value", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .sort_values("date")
    )
    return wide


# ── Output helpers ────────────────────────────────────────────────────────────

def save(df: pd.DataFrame, stem: str, out_dir: Path, write_csv: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pq_path = out_dir / f"{stem}.parquet"
    df.to_parquet(pq_path, index=False)
    print(f"Saved: {pq_path.resolve()}")
    if write_csv:
        csv_path = out_dir / f"{stem}.csv"
        df.to_csv(csv_path, index=False)
        print(f"Saved: {csv_path.resolve()}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    any_done = False

    if args.source in ("wb", "all"):
        df_cpi = load_worldbank(WB_CPI_INPUT, "World Bank CPI level")
        if df_cpi is not None:
            wide = wb_to_wide(df_cpi)
            n_countries = wide.shape[1] - 1  # exclude year column
            print(f"  Wide: {len(wide)} years × {n_countries} countries")
            save(wide, "wb_cpi_wide", out_dir, args.csv)
            any_done = True

        df_inf = load_worldbank(WB_INF_INPUT, "World Bank inflation rate")
        if df_inf is not None:
            wide = wb_to_wide(df_inf)
            n_countries = wide.shape[1] - 1
            print(f"  Wide: {len(wide)} years × {n_countries} countries")
            save(wide, "wb_inflation_wide", out_dir, args.csv)
            any_done = True

    if args.source in ("oecd", "all"):
        df_oecd = load_oecd(OECD_INPUT)
        if df_oecd is not None:
            wide = oecd_to_wide(df_oecd)
            n_countries = wide.shape[1] - 1
            print(f"  Wide: {len(wide)} months × {n_countries} countries")
            save(wide, "oecd_cpi_wide", out_dir, args.csv)
            any_done = True

    if not any_done:
        print(
            "\nNothing processed. Pull data first:\n"
            "  python wrdsdl.py pull wb_cpi\n"
            "  python wrdsdl.py pull wb_inflation\n"
            "  python wrdsdl.py pull oecd_cpi",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
