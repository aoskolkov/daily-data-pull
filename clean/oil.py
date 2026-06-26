"""
Clean oil price data from raw downloads.

Sources
-------
  data/ds_wti_front/   WTI front-month continuous (Datastream NCLCS00, monthly batch on WRDS)
  data/fred_wti_spot/  WTI spot price (FRED DCOILWTICO, daily)

Both sources are already in USD/barrel — no cross-rate conversion needed.
Cleaning tasks: normalize column names, standardize dates, optional merge.

Output
------
  output/oil/ds_wti_front.parquet    Datastream series (long: date, price_usd_bbl)
  output/oil/fred_wti_spot.parquet   FRED series (long: date, price_usd_bbl)
  output/oil/oil_merged.parquet      Both merged on date (--merge)
  output/oil/oil_merged.csv          CSV version of merged (--merge)

Usage
-----
  python clean/oil.py               # clean whichever sources have been pulled
  python clean/oil.py --merge       # also write a merged wide file
  python clean/oil.py --no-csv      # skip CSV output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_OUTPUT = "output/oil"

DS_INPUT = "data/ds_wti_front"
FRED_INPUT = "data/fred_wti_spot"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean oil price data from raw Parquet downloads.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--merge", action="store_true", help="Write a merged file with both sources side by side")
    parser.add_argument("--no-csv", action="store_false", dest="csv", help="Skip CSV output")
    parser.set_defaults(csv=True)
    return parser.parse_args()


# ── Source-specific loaders ───────────────────────────────────────────────────

def _detect_price_col(df: pd.DataFrame) -> str | None:
    """Find the price column by name heuristic."""
    candidates = [c for c in df.columns if c.lower() in ("p", "price", "value", "close", "close_", "dsp", "px_last", "level", "settlement")]
    if candidates:
        return candidates[0]
    # Fall back to any numeric column that's not a date/code
    skip = {"date", "date_", "datadate", "code", "mnemonic", "dscd", "source", "series", "frequency"}
    numeric = [c for c in df.columns if c.lower() not in skip and pd.api.types.is_numeric_dtype(df[c])]
    return numeric[0] if len(numeric) == 1 else None


def _detect_date_col(df: pd.DataFrame) -> str | None:
    candidates = [c for c in df.columns if c.lower() in ("date", "date_", "datadate", "period")]
    return candidates[0] if candidates else None


def load_fred(input_dir: str) -> pd.DataFrame | None:
    """
    FRED adapter output schema: date, series, value, source
    Returns long DataFrame: date, price_usd_bbl
    """
    path = Path(input_dir)
    if not path.exists():
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()

    date_col = _detect_date_col(df) or "date"
    df["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    df = df.dropna(subset=["date"])

    price_col = "value" if "value" in df.columns else _detect_price_col(df)
    if not price_col:
        print(f"WARNING: Could not identify price column in FRED data. Columns: {list(df.columns)}")
        return None

    df["price_usd_bbl"] = pd.to_numeric(df[price_col], errors="coerce")
    result = df[["date", "price_usd_bbl"]].dropna().sort_values("date").reset_index(drop=True)
    print(f"FRED (fred_wti_spot): {len(result):,} rows, "
          f"{result['date'].min()} -> {result['date'].max()}")
    return result


def load_datastream(input_dir: str) -> pd.DataFrame | None:
    """
    Datastream adapter output schema varies by institution.
    Heuristically detect date and price columns.
    Returns long DataFrame: date, price_usd_bbl

    [VERIFY] If this fails, inspect the raw data:
        import pandas as pd; print(pd.read_parquet('data/ds_wti_front').head())
    Then set --ds-date-col / --ds-price-col if auto-detection is wrong.
    """
    path = Path(input_dir)
    if not path.exists():
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()

    date_col = _detect_date_col(df)
    if not date_col:
        print(f"WARNING: Could not detect date column in Datastream data. Columns: {list(df.columns)}")
        print("Inspect with: import pandas as pd; pd.read_parquet('data/ds_wti_front').head()")
        return None

    df["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    df = df.dropna(subset=["date"])

    price_col = _detect_price_col(df)
    if not price_col:
        print(f"WARNING: Could not identify price column in Datastream data. Columns: {list(df.columns)}")
        print("Inspect with: import pandas as pd; pd.read_parquet('data/ds_wti_front').head()")
        return None

    df["price_usd_bbl"] = pd.to_numeric(df[price_col], errors="coerce")
    result = df[["date", "price_usd_bbl"]].dropna().sort_values("date").reset_index(drop=True)
    print(f"Datastream (ds_wti_front): {len(result):,} rows, "
          f"{result['date'].min()} -> {result['date'].max()}")
    return result


# ── Output helpers ────────────────────────────────────────────────────────────

def save(df: pd.DataFrame, path: Path, write_csv: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path.with_suffix(".parquet"), index=False)
    print(f"Saved: {path.with_suffix('.parquet').resolve()}")
    if write_csv:
        df.to_csv(path.with_suffix(".csv"), index=False)
        print(f"Saved: {path.with_suffix('.csv').resolve()}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)

    df_fred = load_fred(FRED_INPUT)
    df_ds = load_datastream(DS_INPUT)

    if df_fred is None and df_ds is None:
        print(
            "No oil data found. Pull first:\n"
            "  python wrdsdl.py pull fred_wti_spot\n"
            "  python wrdsdl.py pull ds_wti_front",
            file=sys.stderr,
        )
        sys.exit(1)

    if df_fred is not None:
        save(df_fred, out_dir / "fred_wti_spot", args.csv)

    if df_ds is not None:
        save(df_ds, out_dir / "ds_wti_front", args.csv)

    if args.merge:
        frames: list[pd.DataFrame] = []
        if df_fred is not None:
            frames.append(df_fred.rename(columns={"price_usd_bbl": "fred_wti_spot"}))
        if df_ds is not None:
            frames.append(df_ds.rename(columns={"price_usd_bbl": "ds_wti_front"}))

        if len(frames) == 1:
            merged = frames[0]
        else:
            merged = frames[0].merge(frames[1], on="date", how="outer").sort_values("date")

        save(merged, out_dir / "oil_merged", args.csv)

        if df_fred is not None and df_ds is not None:
            common = merged.dropna(subset=["fred_wti_spot", "ds_wti_front"])
            if not common.empty:
                corr = common["fred_wti_spot"].corr(common["ds_wti_front"])
                diff = (common["fred_wti_spot"] - common["ds_wti_front"]).abs()
                print(f"\nCross-check ({len(common):,} overlapping dates):")
                print(f"  correlation:  {corr:.6f}")
                print(f"  mean abs diff: {diff.mean():.4f} USD/bbl")
                print(f"  max abs diff:  {diff.max():.4f} USD/bbl")


if __name__ == "__main__":
    main()
