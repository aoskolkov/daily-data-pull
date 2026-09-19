"""
Clean FX forward (and spot) rates from raw WRDS Datastream data.

Raw source: data/fx_forward (from wrds_fx adapter)
Columns: fromcurrcode, tocurrcode, ratetypecode, exratedesc, exratedate, midrate, bidrate, offerrate

Raw quoting: midrate = units of fromcurrcode per 1 unit of tocurrcode, or per
100/1000 units when exratedesc says so (e.g. "US $ TO 100 JAPANESE YEN"):
  - fromcurrcode=JPY, tocurrcode=USD ("JPY TO USD"):  midrate ≈ 155    (JPY per USD)
  - fromcurrcode=USD, tocurrcode=EUR ("USD TO EUR"):  midrate ≈ 1.154  (USD per EUR)
  - fromcurrcode=USD, tocurrcode=JPY ("US $ TO 100 JAPANESE YEN"): ≈ 0.645 (USD per 100 JPY)

Output convention: USD per 1 unit of the currency (EUR ≈ 1.15, JPY ≈ 0.0064).
Note this is the inverse of clean/fx_spot.py, which reports local currency per USD.
  - CCY→USD: rate = 1 / midrate
  - USD→CCY: rate = midrate / multiplier   (multiplier = 100 or 1000 if quoted per 100/1000)
Both directions exist for the majors and agree once scaled.

Output
------
  macrodata/fx_forward/fx_forward_long.parquet         (date, currency, tenor, rate)
  macrodata/fx_forward/by_tenor/{tenor}_wide.parquet   date × currency (one file per tenor)
  macrodata/fx_forward/by_tenor/{tenor}_wide.csv

Usage
-----
  python clean/fx_forward.py
  python clean/fx_forward.py --no-csv
  python clean/fx_forward.py --tenors SPOT 1MFD 3MFD 6MFD 1YFD 2YFD 5YFD
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_INPUT = "data/fx_forward"
DEFAULT_OUTPUT = "macrodata/fx_forward"

# Ordered standard tenors for output naming
STANDARD_TENORS = [
    "SPOT", "ONFD", "TNFD", "SNFD", "1WFD", "2WFD", "3WFD",
    "1MFD", "2MFD", "3MFD", "4MFD", "5MFD", "6MFD", "7MFD", "8MFD", "9MFD",
    "10MF", "11MF", "12YF",
    "1YFD", "2YFD", "3YFD", "4YFD", "5YFD", "6YFD", "7YFD", "8YFD", "9YFD",
    "10YF", "12YF", "15YF", "20YF",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize raw Datastream FX forward Parquet to per-tenor wide format."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--tenors", nargs="+", default=None,
                        help="Subset of ratetypecodes to process (default: all)")
    parser.add_argument("--no-csv", action="store_false", dest="csv")
    parser.set_defaults(csv=True)
    return parser.parse_args()


def load_raw(input_dir: str) -> pd.DataFrame:
    path = Path(input_dir)
    if not path.exists():
        print(
            f"ERROR: Raw data not found at {path.resolve()}\n"
            "Run:  python wrdsdl.py pull fx_forward",
            file=sys.stderr,
        )
        sys.exit(1)
    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    return df


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert raw Datastream FX rates to a uniform 'USD per 1 unit of currency' long table.

    midrate is fromcurrcode per unit of tocurrcode (per 100/1000 units for pairs whose
    exratedesc reads "TO 100 ..." / "TO 1000 ..."), so:
      - tocurrcode == 'USD':   CCY per USD → invert
      - fromcurrcode == 'USD': USD per CCY → keep, after dividing by the multiplier

    Returns columns: date, currency, tenor, rate
    """
    df = df.copy()
    df["exratedate"] = pd.to_datetime(df["exratedate"], errors="coerce")
    df = df.dropna(subset=["exratedate", "midrate"])
    df = df[df["midrate"] > 0]
    # "US $ TO 100 JAPANESE YEN" etc. are quoted per 100 (or 1000) units of tocurrcode;
    # unscaled they put JPY 100x off in 1986-89 and COP/INR/HUF/ISK/IDR likewise.
    mult = df["exratedesc"].astype(str).str.extract(r"\bTO (\d+) ", expand=False).astype(float).fillna(1.0)
    df["midrate"] = df["midrate"] / mult

    usd_to_ccy = df[df["fromcurrcode"] == "USD"].copy()
    usd_to_ccy["currency"] = usd_to_ccy["tocurrcode"]
    usd_to_ccy["rate"] = usd_to_ccy["midrate"]

    ccy_to_usd = df[df["tocurrcode"] == "USD"].copy()
    ccy_to_usd["currency"] = ccy_to_usd["fromcurrcode"]
    ccy_to_usd["rate"] = 1.0 / ccy_to_usd["midrate"]

    long = pd.concat([
        usd_to_ccy[["exratedate", "currency", "ratetypecode", "rate"]],
        ccy_to_usd[["exratedate", "currency", "ratetypecode", "rate"]],
    ], ignore_index=True)

    long = long.rename(columns={"exratedate": "date", "ratetypecode": "tenor"})
    long["currency"] = long["currency"].str.upper()
    long = long[long["currency"] != "USD"]

    # Deduplicate: keep last per (date, currency, tenor)
    long = (
        long.sort_values(["date", "currency", "tenor"])
        .groupby(["date", "currency", "tenor"], as_index=False)["rate"]
        .last()
    )
    return long


def save(df: pd.DataFrame, path: Path, write_csv: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path.with_suffix(".parquet"), index=False)
    if write_csv:
        df.to_csv(path.with_suffix(".csv"), index=False)
    print(f"  -> {path.with_suffix('.parquet')}")


def main() -> None:
    args = parse_args()

    print(f"Loading raw FX forward data from: {args.input}")
    raw = load_raw(args.input)

    required = {"fromcurrcode", "tocurrcode", "ratetypecode", "exratedate", "midrate"}
    missing = required - set(raw.columns)
    if missing:
        print(f"ERROR: Missing columns: {missing}. Got: {list(raw.columns)}", file=sys.stderr)
        sys.exit(1)

    tenors_available = sorted(raw["ratetypecode"].unique())
    if args.tenors:
        tenors_to_use = [t for t in args.tenors if t in tenors_available]
        raw = raw[raw["ratetypecode"].isin(tenors_to_use)]
        print(f"Filtering to tenors: {tenors_to_use}")
    else:
        print(f"Found {len(tenors_available)} tenors: {tenors_available}")

    print("Normalizing to local-currency-per-USD...")
    long = normalize(raw)

    tenors = sorted(long["tenor"].unique())
    print(f"Long: {len(long):,} rows | {long['currency'].nunique()} currencies | "
          f"{len(tenors)} tenors | "
          f"{long['date'].min().date()} – {long['date'].max().date()}")

    out_dir = Path(args.output)

    # ── Long master file ──────────────────────────────────────────────────────
    save(long, out_dir / "fx_forward_long", args.csv)

    # ── Per-tenor wide files ──────────────────────────────────────────────────
    tenor_dir = out_dir / "by_tenor"
    for tenor in tenors:
        subset = long[long["tenor"] == tenor]
        wide = (
            subset.pivot_table(index="date", columns="currency", values="rate", aggfunc="last")
            .rename_axis(None, axis="columns")
            .reset_index()
            .sort_values("date")
        )
        save(wide, tenor_dir / f"{tenor}_wide", args.csv)

    print(f"Done. {len(tenors)} tenor files written to {out_dir / 'by_tenor'}")


if __name__ == "__main__":
    main()
