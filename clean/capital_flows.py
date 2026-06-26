"""
Clean IMF BOP (flows) and IIP (stocks) data.

Produces:
  - Per-indicator wide files: year × country
  - A combined long panel: (year, iso2c, indicator, value)
  - A combined wide panel: (year, iso2c, <indicator columns>)

The five financial-account components (BPM6 sign convention):
  FDI           — direct investment
  portfolio_eq  — portfolio equity
  portfolio_dbt — portfolio debt
  other         — other investment (banking, loans, deposits, trade credit)
  reserves      — reserve assets

Each is split assets / liabilities / net where available.

Input:  data/imf_bop/   data/imf_iip/
Output: output/capital_flows/

Usage
-----
  python clean/capital_flows.py
  python clean/capital_flows.py --source bop   # flows only
  python clean/capital_flows.py --source iip   # stocks only
  python clean/capital_flows.py --no-csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_OUTPUT = "output/capital_flows"

try:
    import sys as _sys
    _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from src.crosswalk import load_crosswalk, map_iso2_to_iso3 as _map_iso2_to_iso3
    _XW = load_crosswalk()
    def _to_iso3(s: pd.Series) -> pd.Series:
        return _map_iso2_to_iso3(_XW, s)
except Exception:
    def _to_iso3(s: pd.Series) -> pd.Series:   # type: ignore[misc]
        return s  # no-op if crosswalk not available

# Maps raw IMF indicator code -> human label used in output columns.
# Update if discovery reveals different codes at your institution.
INDICATOR_LABELS: dict[str, str] = {
    # BOP flows
    "BFDI":   "fdi_net",
    "BFDIA":  "fdi_assets",
    "BFDIL":  "fdi_liab",
    "BFPIE":  "port_eq_net",
    "BFPIEA": "port_eq_assets",
    "BFPIEL": "port_eq_liab",
    "BFPID":  "port_dbt_net",
    "BFPIDA": "port_dbt_assets",
    "BFPIDL": "port_dbt_liab",
    "BFOI":   "other_net",
    "BFOIA":  "other_assets",
    "BFOIL":  "other_liab",
    "BFRA":   "reserves_net",
    # IIP stocks
    "IADIP":  "fdi_assets_pos",
    "ILDIP":  "fdi_liab_pos",
    "IAPIE":  "port_eq_assets_pos",
    "ILPIE":  "port_eq_liab_pos",
    "IAPID":  "port_dbt_assets_pos",
    "ILPID":  "port_dbt_liab_pos",
    "IAOI":   "other_assets_pos",
    "ILOI":   "other_liab_pos",
    "IARA":   "reserves_pos",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean IMF BOP/IIP data to wide and panel formats.")
    p.add_argument("--storage-root", default="data")
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--source", choices=["bop", "iip", "all"], default="all")
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def load_imf(dataset_name: str, storage_root: str) -> pd.DataFrame | None:
    path = Path(storage_root) / dataset_name
    if not path.exists():
        print(f"Skipping {dataset_name}: not yet pulled  (python wrdsdl.py pull {dataset_name})")
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()

    # Normalise the country column — IMF uses REF_AREA (typically ISO2)
    if "ref_area" in df.columns and "iso2c" not in df.columns:
        df = df.rename(columns={"ref_area": "iso2c"})

    # Map to iso3c (crosswalk falls back to original value if not found)
    if "iso2c" in df.columns:
        df["iso3c"] = _to_iso3(df["iso2c"])

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "value"])
    df["year"] = df["date"].dt.year

    # Apply human labels where available
    if "indicator" in df.columns:
        df["indicator_raw"] = df["indicator"]
        df["indicator"] = df["indicator"].map(INDICATOR_LABELS).fillna(df["indicator"])

    n_countries = df["iso3c"].nunique() if "iso3c" in df.columns else "?"
    n_indicators = df["indicator"].nunique() if "indicator" in df.columns else "?"
    print(f"  {dataset_name}: {len(df):,} obs, {n_countries} countries, "
          f"{n_indicators} indicators, {df['year'].min()}–{df['year'].max()}")
    return df


def to_wide(df: pd.DataFrame, index_col: str = "year", col_col: str = "iso3c") -> pd.DataFrame:
    return (
        df.pivot_table(index=index_col, columns=col_col, values="value", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .sort_values(index_col)
    )


def save(df: pd.DataFrame, path: Path, write_csv: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path.with_suffix(".parquet"), index=False)
    suffix = "  + .csv" if write_csv else ""
    print(f"  -> {path.with_suffix('.parquet').name}{suffix}")
    if write_csv:
        df.to_csv(path.with_suffix(".csv"), index=False)


def process(df: pd.DataFrame, label: str, out_dir: Path, write_csv: bool) -> pd.DataFrame:
    """Write per-indicator wide files; return the long frame for panel assembly."""
    wide_dir = out_dir / "wide"
    long_parts: list[pd.DataFrame] = []
    id_col = "iso3c" if "iso3c" in df.columns else "iso2c"

    for indicator, group in df.groupby("indicator"):
        wide = to_wide(group[["year", id_col, "value"]])
        save(wide, wide_dir / f"{indicator}", write_csv)
        part = group[["year", id_col, "indicator", "value"]].copy()
        part.rename(columns={id_col: "iso3c"}, inplace=True)
        part["dataset"] = label
        long_parts.append(part)

    return pd.concat(long_parts, ignore_index=True) if long_parts else pd.DataFrame()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    all_long: list[pd.DataFrame] = []

    if args.source in ("bop", "all"):
        df_bop = load_imf("imf_bop", args.storage_root)
        if df_bop is not None:
            long = process(df_bop, "bop_flow", out_dir, args.csv)
            all_long.append(long)

    if args.source in ("iip", "all"):
        df_iip = load_imf("imf_iip", args.storage_root)
        if df_iip is not None:
            long = process(df_iip, "iip_stock", out_dir, args.csv)
            all_long.append(long)

    if not all_long:
        print("\nNothing processed. Pull first:\n"
              "  python wrdsdl.py pull imf_bop\n"
              "  python wrdsdl.py pull imf_iip", file=sys.stderr)
        sys.exit(1)

    panel_long = (
        pd.concat(all_long, ignore_index=True)
        .sort_values(["year", "iso3c", "dataset", "indicator"])
        .reset_index(drop=True)
    )
    panel_dir = out_dir / "panel"
    save(panel_long, panel_dir / "capital_flows_long", args.csv)
    print(f"  Long panel: {len(panel_long):,} obs, "
          f"{panel_long['iso3c'].nunique()} countries, "
          f"{panel_long['indicator'].nunique()} indicators")

    panel_wide = (
        panel_long.pivot_table(
            index=["year", "iso3c", "dataset"], columns="indicator", values="value", aggfunc="last"
        )
        .rename_axis(None, axis="columns")
        .reset_index()
        .sort_values(["dataset", "year", "iso3c"])
        .reset_index(drop=True)
    )
    save(panel_wide, panel_dir / "capital_flows_wide", args.csv)
    print(f"  Wide panel: {len(panel_wide):,} country-years × {panel_wide.shape[1] - 3} indicators")


if __name__ == "__main__":
    main()
