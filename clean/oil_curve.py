"""
Clean oil futures term structure from WRDS individual contract data.

WTI (NYMEX CL):  months 1-12 via ds_wti_curve  (NWS{MMYY} contracts, source=wrds_fut)
Brent (ICE):     months 1-12 via ds_brent_curve (LLC{MMYY} contracts, source=wrds_fut)

The wrds_fut adapter ranks contracts by lasttrddate on each date to build
nearby 1-12 (constant-maturity roll). Output column is 'nearby' (integer).

Also handles legacy Datastream mnemonic format (NCLCS00->F1, NCLCS01->F2, etc.)
in case the old multi-mnemonic format is used.

Tenor mapping:
  nearby column (int): 1=front month, 2=next month, ..., 12=12th nearby
  OR mnemonic column: NCLCS00->1, NCLCS01->2, ..., NCLCS11->12

Metrics computed (per commodity):
  slope_12_1   log(F12 / F1) / 11     annualised log slope per month
                                       negative = backwardation, positive = contango
  slope_6_1    log(F6  / F1) / 5      short-end slope
  spread_2_1   F2 - F1                front calendar spread (USD/bbl per roll)
  spread_3_1   F3 - F1
  basis        F1 - spot              futures premium over spot (USD/bbl)
                                       only if spot series (fred_wti_spot) is available

Output
------
  output/oil_curve/{commodity}_wide.parquet    date × F1..F12
  output/oil_curve/{commodity}_wide.csv
  output/oil_curve/{commodity}_long.parquet    (date, commodity, tenor, price)
  output/oil_curve/{commodity}_metrics.parquet (date, commodity, slope_12_1, …)
  output/oil_curve/oil_curve_long.parquet      both commodities combined

Usage
-----
  python clean/oil_curve.py
  python clean/oil_curve.py --no-brent      # skip if ds_brent_curve not pulled yet
  python clean/oil_curve.py --no-csv
  python clean/oil_curve.py --spot data/fred_wti_spot   # add basis column for WTI
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
import numpy as np

DEFAULT_OUTPUT = "output/oil_curve"
STORAGE_ROOT = "data"

# Dataset name -> (commodity label, mnemonic root for auto-numbering)
CURVE_DATASETS: dict[str, tuple[str, str]] = {
    "ds_wti_curve":   ("wti",   "NCLCS"),
    "ds_brent_curve": ("brent", ""),       # root TBD pending verification
}

# WTI spot dataset (for basis computation); override with --spot
DEFAULT_WTI_SPOT = "fred_wti_spot"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build oil futures term structure from Datastream data.")
    p.add_argument("--storage-root", default=STORAGE_ROOT)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--no-brent", action="store_true",
                   help="Skip Brent even if ds_brent_curve is present")
    p.add_argument("--spot", default=None, metavar="DATASET",
                   help="Dataset name (under storage-root) for spot prices to compute basis. "
                        f"Defaults to {DEFAULT_WTI_SPOT}")
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def _detect_date_col(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        cl = c.lower()
        if cl in ("date", "date_", "datadate", "period"):
            return c
    for c in df.columns:
        if "date" in c.lower():
            return c
    return None


def _detect_price_col(df: pd.DataFrame, skip: set[str]) -> str | None:
    preferred = ("p", "price", "value", "close", "px_last", "level", "ret")
    col_lower = {c: c.lower() for c in df.columns if c not in skip}
    for pref in preferred:
        for c, cl in col_lower.items():
            if cl == pref:
                return c
    for c, cl in col_lower.items():
        if pd.api.types.is_numeric_dtype(df[c]):
            return c
    return None


def _detect_mnemonic_col(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        if c.lower() in ("code", "mnemonic", "dscd", "mnemonicpulled", "mnemonic_pulled"):
            return c
    return None


def mnemonic_to_tenor(mnemonic: str, root: str, all_mnemonics: list[str]) -> int:
    """
    Return the 1-based tenor (F1 = front month) for a mnemonic.

    If the mnemonic ends in two digits matching the root pattern, parse from there.
    Otherwise fall back to position in the list.
    """
    if root:
        suffix = mnemonic.upper().replace(root.upper(), "")
        m = re.fullmatch(r"0*(\d+)", suffix)
        if m:
            return int(m.group(1)) + 1   # 00 -> 1, 01 -> 2, …

    try:
        idx = [mn.upper() for mn in all_mnemonics].index(mnemonic.upper())
        return idx + 1
    except ValueError:
        return len(all_mnemonics)


def load_curve(
    dataset_name: str,
    commodity: str,
    root: str,
    storage_root: str,
) -> pd.DataFrame | None:
    """
    Load all partitions for a curve dataset and return long format:
      (date, commodity, tenor, price)
    """
    path = Path(storage_root) / dataset_name
    if not path.exists():
        print(f"  {dataset_name}: not pulled yet — skipping  "
              f"(python wrdsdl.py pull {dataset_name})")
        return None

    df = pd.read_parquet(path)
    if df.empty:
        print(f"  {dataset_name}: empty — skipping")
        return None

    df.columns = [c.strip() for c in df.columns]

    date_col = _detect_date_col(df)
    if date_col is None:
        print(f"  {dataset_name}: could not find date column — skipping")
        return None

    df["date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["date"])

    mn_col = _detect_mnemonic_col(df)
    skip = {"date", date_col}
    if mn_col:
        skip.add(mn_col)

    price_col = _detect_price_col(df, skip)
    if price_col is None:
        print(f"  {dataset_name}: could not find price column — skipping")
        return None

    df["price"] = pd.to_numeric(df[price_col], errors="coerce")
    df = df.dropna(subset=["price"])

    # Assign tenors: prefer explicit nearby column (wrds_fut), then mnemonic, then default 1
    nearby_col = next((c for c in df.columns if c.lower() == "nearby"), None)
    all_mnemonics = sorted(df[mn_col].dropna().unique().tolist()) if mn_col else []
    if nearby_col is not None:
        df["tenor"] = pd.to_numeric(df[nearby_col], errors="coerce").astype("Int64")
    elif mn_col:
        df["tenor"] = df[mn_col].apply(
            lambda mn: mnemonic_to_tenor(str(mn), root, all_mnemonics)
        )
    else:
        df["tenor"] = 1

    df["commodity"] = commodity
    result = (
        df[["date", "commodity", "tenor", "price"]]
        .drop_duplicates(subset=["date", "tenor"], keep="last")
        .sort_values(["date", "tenor"])
        .reset_index(drop=True)
    )

    n_tenors = result["tenor"].nunique()
    print(f"  {dataset_name} ({commodity}): {len(result):,} obs, "
          f"{n_tenors} tenors, "
          f"{result['date'].min().date()} – {result['date'].max().date()}")
    return result


def load_spot(dataset_name: str, storage_root: str) -> pd.DataFrame | None:
    path = Path(storage_root) / dataset_name
    if not path.exists():
        return None

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    date_col = _detect_date_col(df)
    if date_col is None:
        return None

    df["date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["date"])

    val_col = "value" if "value" in df.columns else _detect_price_col(df, {"date", date_col})
    if val_col is None:
        return None

    df["spot"] = pd.to_numeric(df[val_col], errors="coerce")
    return df[["date", "spot"]].dropna().sort_values("date").reset_index(drop=True)


def compute_metrics(long: pd.DataFrame, spot: pd.DataFrame | None) -> pd.DataFrame:
    """
    Given long (date, commodity, tenor, price), return a metrics DataFrame.
    """
    wide = (
        long.pivot_table(index="date", columns="tenor", values="price", aggfunc="last")
        .rename(columns=lambda n: f"F{n}")
    )
    metrics = pd.DataFrame(index=wide.index)

    # Slope: log(F12 / F1) / 11  months (annualised per month)
    if "F1" in wide.columns and "F12" in wide.columns:
        common = wide[["F1", "F12"]].dropna()
        metrics.loc[common.index, "slope_12_1"] = (
            np.log(common["F12"] / common["F1"]) / 11
        )

    # Short-end slope: log(F6 / F1) / 5
    if "F1" in wide.columns and "F6" in wide.columns:
        common = wide[["F1", "F6"]].dropna()
        metrics.loc[common.index, "slope_6_1"] = (
            np.log(common["F6"] / common["F1"]) / 5
        )

    # Calendar spreads
    if "F1" in wide.columns and "F2" in wide.columns:
        metrics["spread_2_1"] = wide["F2"] - wide["F1"]
    if "F1" in wide.columns and "F3" in wide.columns:
        metrics["spread_3_1"] = wide["F3"] - wide["F1"]

    # Basis: F1 - spot (only for WTI if spot available)
    if spot is not None and "F1" in wide.columns:
        merged = wide[["F1"]].merge(spot.set_index("date")[["spot"]], left_index=True, right_index=True, how="inner")
        metrics.loc[merged.index, "basis"] = merged["F1"] - merged["spot"]

    metrics = metrics.dropna(how="all").reset_index()
    metrics.rename(columns={"index": "date"}, inplace=True)
    return metrics


def save(df: pd.DataFrame, path: Path, write_csv: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path.with_suffix(".parquet"), index=False)
    if write_csv:
        df.to_csv(path.with_suffix(".csv"), index=False)
    print(f"  -> {path.with_suffix('.parquet').resolve()}")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)

    spot_dataset = args.spot or DEFAULT_WTI_SPOT
    spot = load_spot(spot_dataset, args.storage_root)
    if spot is not None:
        print(f"  Spot loaded from {spot_dataset}: {len(spot):,} obs  (for basis)")
    else:
        print(f"  No spot data ({spot_dataset}) — basis column will be omitted")

    all_long: list[pd.DataFrame] = []

    for dataset_name, (commodity, root) in CURVE_DATASETS.items():
        if args.no_brent and commodity == "brent":
            continue

        print(f"\nLoading {commodity.upper()} curve...")
        long = load_curve(dataset_name, commodity, root, args.storage_root)
        if long is None or long.empty:
            continue

        all_long.append(long)

        # Wide: date × F1..F12
        wide = (
            long.pivot_table(index="date", columns="tenor", values="price", aggfunc="last")
            .rename(columns=lambda n: f"F{n}")
            .reset_index()
            .sort_values("date")
        )
        save(wide, out_dir / f"{commodity}_wide", args.csv)

        # Long with commodity column already present
        save(long, out_dir / f"{commodity}_long", args.csv)

        # Metrics
        spot_for_basis = spot if commodity == "wti" else None
        metrics = compute_metrics(long, spot_for_basis)
        if not metrics.empty:
            metrics["commodity"] = commodity
            save(metrics, out_dir / f"{commodity}_metrics", args.csv)

            # Print summary stats
            if "slope_12_1" in metrics.columns:
                s = metrics["slope_12_1"].dropna()
                pct_backw = (s < 0).mean() * 100
                print(f"  {commodity.upper()} slope_12_1: "
                      f"mean={s.mean():.4f}/mo, "
                      f"median={s.median():.4f}/mo, "
                      f"backwardation={pct_backw:.1f}% of dates")
            if "spread_2_1" in metrics.columns:
                sp = metrics["spread_2_1"].dropna()
                print(f"  {commodity.upper()} F2-F1 spread: "
                      f"mean={sp.mean():.2f}, median={sp.median():.2f} USD/bbl")
            if "basis" in metrics.columns:
                b = metrics["basis"].dropna()
                print(f"  WTI basis (F1-spot): mean={b.mean():.2f}, median={b.median():.2f} USD/bbl")

    if not all_long:
        print("\nNothing processed. Pull first:\n"
              "  python wrdsdl.py pull ds_wti_curve")
        return

    # Combined long file
    combined = pd.concat(all_long, ignore_index=True).sort_values(["commodity", "date", "tenor"])
    save(combined, out_dir / "oil_curve_long", args.csv)
    print(f"\nCombined long: {len(combined):,} obs, "
          f"{combined['commodity'].nunique()} commodities, "
          f"{combined['tenor'].nunique()} tenors")


if __name__ == "__main__":
    main()
