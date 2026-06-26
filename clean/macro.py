"""
Clean macro data from World Bank raw downloads.

Produces two outputs per indicator (wide country × year) plus a combined
country-year panel with all available indicators as columns.

Sources (all World Bank, annual, ~180 countries)
-------
  data/wb_gdp_usd/          GDP current USD
  data/wb_gdp_growth/       GDP growth rate (%)
  data/wb_gdp_pcap_usd/     GDP per capita current USD
  data/wb_consumption_hh/   Household final consumption current USD
  data/wb_consumption_govt/ Government final consumption current USD
  data/wb_investment/       Gross fixed capital formation current USD
  data/wb_exports/          Exports of goods and services current USD
  data/wb_imports/          Imports of goods and services current USD
  data/wb_current_account/  Current account balance current USD
  data/wb_fdi_inflows/      FDI net inflows current USD
  data/wb_fdi_outflows/     FDI net outflows current USD
  data/wb_portfolio_equity/ Portfolio equity net inflows current USD

Outputs
-------
  output/macro/wide/wb_gdp_usd.csv          one file per indicator (year × iso3c)
  output/macro/panel/macro_panel.parquet    long panel (year, iso3c, country_name, var, value)
  output/macro/panel/macro_panel_wide.csv   wide panel (year, iso3c, country_name, gdp_usd, ...)

Usage
-----
  python clean/macro.py
  python clean/macro.py --no-csv
  python clean/macro.py --no-panel      # skip building the combined panel
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

STORAGE_ROOT = "data"
DEFAULT_OUTPUT = "output/macro"

# dataset_name -> short column name used in the panel
INDICATORS: dict[str, str] = {
    "wb_gdp_usd":          "gdp_usd",
    "wb_gdp_growth":       "gdp_growth_pct",
    "wb_gdp_pcap_usd":     "gdp_pcap_usd",
    "wb_consumption_hh":   "consumption_hh_usd",
    "wb_consumption_govt": "consumption_govt_usd",
    "wb_investment":       "investment_usd",
    "wb_exports":          "exports_usd",
    "wb_imports":          "imports_usd",
    "wb_current_account":  "current_account_usd",
    "wb_fdi_inflows":      "fdi_inflows_usd",
    "wb_fdi_outflows":     "fdi_outflows_usd",
    "wb_portfolio_equity": "portfolio_equity_usd",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean World Bank macro data to wide and panel formats.")
    parser.add_argument("--storage-root", default=STORAGE_ROOT, help=f"Raw data root (default: {STORAGE_ROOT})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--no-csv", action="store_false", dest="csv", help="Skip CSV output")
    parser.add_argument("--no-panel", action="store_false", dest="panel", help="Skip combined panel output")
    parser.set_defaults(csv=True, panel=True)
    return parser.parse_args()


def load_wb(dataset_name: str, storage_root: str) -> pd.DataFrame | None:
    """
    World Bank raw schema: date, country_name, iso2c, iso3c, indicator, value, source
    Returns long DataFrame with year (int) column added.
    """
    path = Path(storage_root) / dataset_name
    if not path.exists():
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "value"])
    df["year"] = df["date"].dt.year

    n = df["iso3c"].nunique() if "iso3c" in df.columns else "?"
    print(f"  {dataset_name}: {len(df):,} obs, {n} countries, "
          f"{df['year'].min()}–{df['year'].max()}")
    return df


def to_wide(df: pd.DataFrame, col_id: str = "iso3c") -> pd.DataFrame:
    """Pivot to wide: rows = year, columns = iso3c country codes."""
    col = col_id if col_id in df.columns and df[col_id].notna().any() else "country_name"
    return (
        df.pivot_table(index="year", columns=col, values="value", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .sort_values("year")
    )


def save(df: pd.DataFrame, path: Path, write_csv: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path.with_suffix(".parquet"), index=False)
    if write_csv:
        df.to_csv(path.with_suffix(".csv"), index=False)
    print(f"  -> {path.with_suffix('.parquet').name}" +
          (f"  + .csv" if write_csv else ""))


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    wide_dir = out_dir / "wide"
    panel_dir = out_dir / "panel"

    # ── Per-indicator wide files ───────────────────────────────────────────────
    print("Loading indicators...")
    loaded: dict[str, pd.DataFrame] = {}

    for dataset_name, short_name in INDICATORS.items():
        df = load_wb(dataset_name, args.storage_root)
        if df is None:
            continue
        loaded[short_name] = df
        wide = to_wide(df)
        save(wide, wide_dir / dataset_name, args.csv)

    if not loaded:
        print(
            "\nNo macro data found. Pull first, e.g.:\n"
            "  python wrdsdl.py pull wb_gdp_usd\n"
            "  python wrdsdl.py pull --all",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n{len(loaded)}/{len(INDICATORS)} indicators loaded.")

    if not args.panel:
        return

    # ── Combined panel ────────────────────────────────────────────────────────
    # Long panel: year, iso3c, country_name, variable, value
    print("\nBuilding combined panel...")
    long_frames: list[pd.DataFrame] = []
    for short_name, df in loaded.items():
        id_cols = [c for c in ("year", "iso3c", "iso2c", "country_name") if c in df.columns]
        frame = df[id_cols + ["value"]].copy()
        frame["variable"] = short_name
        long_frames.append(frame)

    panel_long = (
        pd.concat(long_frames, ignore_index=True)
        .sort_values(["year", "iso3c", "variable"])
        .reset_index(drop=True)
    )

    panel_long_path = panel_dir / "macro_panel"
    panel_long_path.parent.mkdir(parents=True, exist_ok=True)
    panel_long.to_parquet(panel_long_path.with_suffix(".parquet"), index=False)
    print(f"  Long panel: {len(panel_long):,} obs "
          f"({panel_long['year'].min()}–{panel_long['year'].max()}, "
          f"{panel_long['iso2c'].nunique()} countries, "
          f"{panel_long['variable'].nunique()} variables)")
    print(f"  -> {panel_long_path.with_suffix('.parquet').name}")

    # Wide panel: one row per (year, country), one column per indicator
    id_index = [c for c in ("year", "iso3c", "iso2c", "country_name") if c in panel_long.columns]
    panel_wide = (
        panel_long
        .pivot_table(index=id_index, columns="variable", values="value", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .sort_values(["year", "iso3c"])
        .reset_index(drop=True)
    )

    # Reorder columns: identifiers first, then grouped by topic
    col_order = id_index
    topic_order = [v for v in INDICATORS.values() if v in panel_wide.columns]
    panel_wide = panel_wide[col_order + topic_order]

    panel_wide_path = panel_dir / "macro_panel_wide"
    panel_wide.to_parquet(panel_wide_path.with_suffix(".parquet"), index=False)
    print(f"  Wide panel: {len(panel_wide):,} country-years × {len(topic_order)} variables")
    print(f"  -> {panel_wide_path.with_suffix('.parquet').name}")

    if args.csv:
        panel_wide.to_csv(panel_wide_path.with_suffix(".csv"), index=False)
        print(f"  -> {panel_wide_path.with_suffix('.csv').name}")


if __name__ == "__main__":
    main()
