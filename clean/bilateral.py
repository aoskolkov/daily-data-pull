"""
Clean IMF CPIS and CDIS bilateral position data.

CPIS — Coordinated Portfolio Investment Survey
  Who (reporter) holds what (instrument) issued by whom (counterpart).
  ~94 reporters × ~246 counterparts, annual, 2001–present (IMF dataflow PIP).
  Instruments: total, equity, long-term debt, short-term debt.

CDIS — Coordinated Direct Investment Survey
  Who (reporter) has direct investment in/from whom (counterpart).
  Inward (liabilities) and outward (assets) positions.
  ~143 reporters, annual, 2009–present (IMF dataflow DIP).

Output format: long Parquet with columns
  (year, reporter, counterpart, indicator, value)

Optionally: reporter × counterpart matrices for a given year (--matrix).

Input:  data/imf_cpis/   data/imf_cdis/
Output: macrodata/bilateral/

Usage
-----
  python clean/bilateral.py
  python clean/bilateral.py --matrix 2022       # write reporter × counterpart CSVs for 2022
  python clean/bilateral.py --source cpis
  python clean/bilateral.py --source cdis
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_OUTPUT = "macrodata/bilateral"

# Indicator labels (portfolio_total, fdi_inward_total, ...) are assigned by the
# adapter from `labels:` in datasets.yaml; the IMF now publishes CPIS as PIP and
# CDIS as DIP on api.imf.org. Counterpart G001 is the world total.
CPIS_LABELS: dict[str, str] = {}
CDIS_LABELS: dict[str, str] = {}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean IMF CPIS/CDIS bilateral position data.")
    p.add_argument("--storage-root", default="data")
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--source", choices=["cpis", "cdis", "all"], default="all")
    p.add_argument("--matrix", metavar="YEAR", type=int, default=None,
                   help="Also write reporter × counterpart matrices for this year")
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def load_bilateral(dataset_name: str, storage_root: str, labels: dict[str, str]) -> pd.DataFrame | None:
    path = Path(storage_root) / dataset_name
    if not path.exists():
        print(f"Skipping {dataset_name}: not yet pulled  (python wrdsdl.py pull {dataset_name})")
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()

    # Normalise dimension column names — vary by IMF API version
    rename = {}
    for c in df.columns:
        u = c.upper()
        if u in ("COUNTRY", "REF_AREA") and "reporter" not in df.columns:
            rename[c] = "reporter"
        elif u in ("COUNTERPART_COUNTRY", "COUNTERPART_AREA", "CPART_AREA") and "counterpart" not in df.columns:
            rename[c] = "counterpart"
        elif u == "INDICATOR" and "indicator" not in df.columns:
            rename[c] = "indicator"
    df = df.rename(columns=rename)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "value"])
    df["year"] = df["date"].dt.year

    if "indicator" in df.columns:
        df["indicator"] = df["indicator"].map(labels).fillna(df["indicator"])

    n_rep  = df["reporter"].nunique()    if "reporter"    in df.columns else "?"
    n_cpt  = df["counterpart"].nunique() if "counterpart" in df.columns else "?"
    n_ind  = df["indicator"].nunique()   if "indicator"   in df.columns else "?"
    print(f"  {dataset_name}: {len(df):,} obs, "
          f"{n_rep} reporters × {n_cpt} counterparts, "
          f"{n_ind} indicators, "
          f"{df['year'].min()}–{df['year'].max()}")
    return df


def write_matrices(df: pd.DataFrame, year: int, out_dir: Path, write_csv: bool) -> None:
    """Write a reporter × counterpart matrix for each indicator in a given year."""
    subset = df[df["year"] == year]
    if subset.empty:
        print(f"  No data for year {year}")
        return

    mat_dir = out_dir / f"matrices_{year}"
    indicators = subset["indicator"].unique() if "indicator" in subset.columns else ["value"]

    for ind in indicators:
        if "indicator" in subset.columns:
            chunk = subset[subset["indicator"] == ind]
        else:
            chunk = subset
        mat = (
            chunk.pivot_table(index="reporter", columns="counterpart", values="value", aggfunc="last")
            .rename_axis(None, axis="columns")
        )
        mat_dir.mkdir(parents=True, exist_ok=True)
        mat.to_parquet((mat_dir / f"{ind}.parquet"))
        if write_csv:
            mat.to_csv(mat_dir / f"{ind}.csv")
        print(f"  Matrix {ind} ({year}): {mat.shape[0]} reporters × {mat.shape[1]} counterparts")


def save(df: pd.DataFrame, path: Path, write_csv: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path.with_suffix(".parquet"), index=False)
    suffix = "  + .csv" if write_csv else ""
    print(f"  -> {path.with_suffix('.parquet').name}{suffix}")
    if write_csv:
        df.to_csv(path.with_suffix(".csv"), index=False)


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)
    any_done = False

    if args.source in ("cpis", "all"):
        df = load_bilateral("imf_cpis", args.storage_root, CPIS_LABELS)
        if df is not None:
            keep = ["year", "reporter", "counterpart", "indicator", "value"]
            keep = [c for c in keep if c in df.columns]
            save(df[keep], out_dir / "cpis_long", args.csv)
            if args.matrix:
                write_matrices(df, args.matrix, out_dir / "cpis", args.csv)
            any_done = True

    if args.source in ("cdis", "all"):
        df = load_bilateral("imf_cdis", args.storage_root, CDIS_LABELS)
        if df is not None:
            keep = ["year", "reporter", "counterpart", "indicator", "value"]
            keep = [c for c in keep if c in df.columns]
            save(df[keep], out_dir / "cdis_long", args.csv)
            if args.matrix:
                write_matrices(df, args.matrix, out_dir / "cdis", args.csv)
            any_done = True

    if not any_done:
        print("\nNothing processed. Pull first:\n"
              "  python wrdsdl.py pull imf_cpis\n"
              "  python wrdsdl.py pull imf_cdis", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
