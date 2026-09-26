"""
Clean FX spot rates from raw WRDS data.

Reads raw comp.exrt_dly Parquet (pulled by wrdsdl) and produces:
  - Wide Parquet + CSV: one row per date, one column per currency
  - Units: local currency per 1 USD

The Compustat table uses an anchor base currency (typically GBP, not USD).
Both toUSD and fromUSD quote directions are handled via cross-rate through USD:

    rate(local/USD) = exratd(local/anchor) / exratd(USD/anchor)

This is the same logic as the original download_fx.py, but operating on
already-downloaded Parquet rather than querying WRDS directly.

Output
------
  macrodata/fx_spot/fx_spot_currency_wide.parquet   date × currency code
  macrodata/fx_spot/fx_spot_country_wide.parquet    date × iso3c  (via crosswalk)
  macrodata/fx_spot/fx_spot_long.parquet            (date, currency, exratd)
All rates, majors included, are local currency per 1 USD (the inverse of
clean/fx_forward.py, which reports USD per unit of currency).

Usage
-----
  python clean/fx_spot.py                   # data/fx_spot -> macrodata/fx_spot
  python clean/fx_spot.py --no-csv          # skip CSV output
  python clean/fx_spot.py --no-country      # skip country-indexed output
  python clean/fx_spot.py --input data/fx_spot --output macrodata/fx_spot
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_INPUT = "data/fx_spot"
DEFAULT_OUTPUT = "macrodata/fx_spot"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize raw FX spot Parquet to local/USD wide format."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--no-csv", action="store_false", dest="csv")
    parser.add_argument("--no-country", action="store_false", dest="country",
                        help="Skip country-indexed (iso3c) wide output")
    parser.set_defaults(csv=True, country=True)
    return parser.parse_args()


def load_raw(input_dir: str) -> pd.DataFrame:
    path = Path(input_dir)
    if not path.exists():
        print(
            f"ERROR: Raw data not found at {path.resolve()}\n"
            "Run first:  python wrdsdl.py pull fx_spot",
            file=sys.stderr,
        )
        sys.exit(1)
    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    return df


def detect_anchor_base(df: pd.DataFrame) -> str:
    """Return the dominant fromcurd by row count — this is the anchor base currency."""
    counts = df.groupby("fromcurd").size().sort_values(ascending=False)
    if counts.empty:
        raise ValueError("No fromcurd values in raw data")
    anchor = str(counts.index[0])
    print(f"Anchor base currency: {anchor}  ({counts.iloc[0]:,} rows, "
          f"{counts.iloc[1]:,} next)" if len(counts) > 1 else f"Anchor base currency: {anchor}")
    return anchor


def normalize_to_usd(df: pd.DataFrame, anchor: str) -> pd.DataFrame:
    """
    Convert anchor-quoted rates to local currency per 1 USD.

    Steps:
      1. Subset to rows where fromcurd == anchor.
      2. Extract the USD/anchor rate for each date (tocurd == 'USD').
      3. Divide every other rate by USD/anchor to get local/USD.
    """
    df_anchor = df[df["fromcurd"] == anchor].copy()

    usd_rates = (
        df_anchor[df_anchor["tocurd"] == "USD"][["datadate", "exratd"]]
        .rename(columns={"exratd": "usd_per_anchor"})
        .drop_duplicates(subset=["datadate"], keep="last")
    )

    if usd_rates.empty:
        raise ValueError(
            f"No USD/{anchor} rate found in raw data. Cannot compute cross-rates.\n"
            "Run 'python wrdsdl.py discover comp --table exrt_dly' to inspect the table."
        )

    df_merged = df_anchor.merge(usd_rates, on="datadate", how="inner")
    df_merged = df_merged[df_merged["usd_per_anchor"] != 0].copy()
    df_merged["rate_local_per_usd"] = df_merged["exratd"] / df_merged["usd_per_anchor"]

    return df_merged[["datadate", "tocurd", "rate_local_per_usd"]].rename(
        columns={"tocurd": "currency", "rate_local_per_usd": "exratd"}
    )


def to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot long-form (date, currency, rate) to wide (date × currency)."""
    wide = (
        df.pivot_table(index="datadate", columns="currency", values="exratd", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .rename(columns={"datadate": "date"})
        .sort_values("date")
    )
    return wide


def save(df: pd.DataFrame, path: Path, write_csv: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path.with_suffix(".parquet"), index=False)
    if write_csv:
        df.to_csv(path.with_suffix(".csv"), index=False)
    print(f"  -> {path.with_suffix('.parquet').name}")


def main() -> None:
    args = parse_args()

    print(f"Loading raw FX spot data from: {args.input}")
    df = load_raw(args.input)

    required = {"datadate", "fromcurd", "tocurd", "exratd"}
    missing = required - set(df.columns)
    if missing:
        print(f"ERROR: Raw data missing columns: {missing}. Got: {list(df.columns)}", file=sys.stderr)
        sys.exit(1)

    df["datadate"] = pd.to_datetime(df["datadate"], errors="coerce")
    df = df.dropna(subset=["datadate", "exratd"])

    anchor = detect_anchor_base(df)
    print("Computing cross-rates through USD...")
    df_long = normalize_to_usd(df, anchor)

    # Deduplicate: keep last observed rate per (date, currency)
    df_long = (
        df_long.sort_values(["datadate", "currency"])
        .groupby(["datadate", "currency"], as_index=False)["exratd"]
        .last()
    )
    df_long = df_long.rename(columns={"datadate": "date"})

    n_ccy = df_long["currency"].nunique()
    date_range = f"{df_long['date'].min().date()} – {df_long['date'].max().date()}"
    print(f"Long: {len(df_long):,} rows — {n_ccy} currencies, {date_range}")

    out_dir = Path(args.output)

    # ── Long master file ──────────────────────────────────────────────────────
    save(df_long, out_dir / "fx_spot_long", args.csv)

    # ── Currency-indexed wide (date × currency code) ──────────────────────────
    wide_ccy = (
        df_long.pivot_table(index="date", columns="currency", values="exratd", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .sort_values("date")
    )
    print(f"Currency wide: {len(wide_ccy):,} dates × {wide_ccy.shape[1] - 1} currencies")
    save(wide_ccy, out_dir / "fx_spot_currency_wide", args.csv)

    # ── Country-indexed wide (date × iso3c) ───────────────────────────────────
    if args.country:
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from src.crosswalk import load_crosswalk, apply_currency_crosswalk
            xw = load_crosswalk()
            expanded = apply_currency_crosswalk(
                df_long, xw, currency_col="currency", date_col="date"
            )
            if not expanded.empty and "iso3c" in expanded.columns:
                wide_ctry = (
                    expanded.pivot_table(
                        index="date", columns="iso3c", values="exratd", aggfunc="last"
                    )
                    .rename_axis(None, axis="columns")
                    .reset_index()
                    .sort_values("date")
                )
                print(f"Country wide: {len(wide_ctry):,} dates × {wide_ctry.shape[1] - 1} countries")
                save(wide_ctry, out_dir / "fx_spot_country_wide", args.csv)
            else:
                print("WARNING: crosswalk expansion returned no rows — country wide skipped")
        except FileNotFoundError:
            print("NOTE: config/currency_country.csv not found — run 'python scripts/build_crosswalk.py'")
            print("      Country-indexed wide output skipped.")
        except Exception as exc:
            print(f"WARNING: country-indexed output failed ({exc}). Currency-indexed saved.")


if __name__ == "__main__":
    main()
