"""
Clean interest rate data: BIS central bank policy rates and Datastream bond yields.

Sources:
  data/bis_cbpol/          — BIS WS_CBPOL daily, columns: date, freq, ref_area, obs_value
  data/ds_bond_yields_10y/ — tr_ds_econ monthly, columns: date_, dsmnemonic, close_

Output:
  output/interest_rates/cbpol_wide.{parquet,csv}       date × ISO2 country
  output/interest_rates/bond_yield_10y_wide.{parquet,csv}  date × ISO2 country

Usage:
  python clean/interest_rates.py
  python clean/interest_rates.py --no-csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

OUT_DIR = Path("output/interest_rates")

# Map Datastream bond yield mnemonics → ISO 3166-1 alpha-2 country codes
# (or XM for Eurozone)
MNEMONIC_TO_ISO2 = {
    "USTRCN10": "US",
    "UKMEDYLD": "GB",
    "BDGBOND.": "DE",
    "FRGBOND.": "FR",
    "ITGBOND.": "IT",
    "ESGBOND.": "ES",
    "NLGBOND.": "NL",
    "BGGBOND.": "BE",
    "PTGBOND.": "PT",
    "GRGBOND.": "GR",
    "OEGBOND.": "AT",
    "FNGBOND.": "FI",
    "IRGBOND.": "IE",
    "DKGBOND.": "DK",
    "SDGBOND.": "SE",
    "NWGBOND.": "NO",
    "SWGBOND.": "CH",
    "ICGBOND.": "IS",
    "HNGBOND.": "HU",
    "CZGBOND.": "CZ",
    "POGBOND.": "PL",
    "RMGBOND.": "RO",
    "RSGBOND.": "RU",
    "JPGBOND.": "JP",
    "AUGBOND.": "AU",
    "NZGBOND.": "NZ",
    "KOGBOND.": "KR",
    "CHGBOND.": "CN",
    "INGBOND.": "IN",
    "TWGBD10Y": "TW",
    "HKGBOND.": "HK",
    "MYGBOND.": "MY",
    "SPGBOND.": "SG",
    "THGBOND.": "TH",
    "PHGBOND.": "PH",
    "PKGBOND.": "PK",
    "CNGBOND.": "CA",
    "BRGBOND.": "BR",
    "MXGBOND.": "MX",
    "TKGBOND.": "TR",
    "EYGBOND.": "EG",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def save(df: pd.DataFrame, path: Path, write_csv: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path.with_suffix(".parquet"), index=False)
    if write_csv:
        df.to_csv(path.with_suffix(".csv"), index=False)
    print(f"  -> {path.with_suffix('.parquet')}")


def clean_cbpol(write_csv: bool) -> None:
    src = Path("data/bis_cbpol")
    if not src.exists():
        print("SKIP cbpol: data/bis_cbpol not found (run: python wrdsdl.py pull bis_cbpol)")
        return

    df = pd.read_parquet(src)
    df.columns = df.columns.str.lower()

    # BIS adapter output: date, freq, ref_area, obs_value
    if "ref_area" not in df.columns or "obs_value" not in df.columns:
        print(f"SKIP cbpol: unexpected columns {list(df.columns)}")
        return

    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["date", "obs_value"])
    df = df.rename(columns={"ref_area": "country", "obs_value": "rate"})

    # Deduplicate (keep last per date × country in case of overlapping pulls)
    df = (
        df.sort_values(["date", "country"])
        .groupby(["date", "country"], as_index=False)["rate"]
        .last()
    )

    wide = (
        df.pivot_table(index="date", columns="country", values="rate", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .sort_values("date")
    )

    n_countries = wide.shape[1] - 1
    print(f"CBPOL: {len(wide):,} dates × {n_countries} countries | "
          f"{wide.date.min().date()} – {wide.date.max().date()}")
    save(wide, OUT_DIR / "cbpol_wide", write_csv)


def clean_bond_yields(write_csv: bool) -> None:
    src = Path("data/ds_bond_yields_10y")
    if not src.exists():
        print("SKIP bond yields: data/ds_bond_yields_10y not found "
              "(run: python wrdsdl.py pull ds_bond_yields_10y)")
        return

    df = pd.read_parquet(src)
    df.columns = df.columns.str.lower()

    if "dsmnemonic" not in df.columns or "close_" not in df.columns:
        print(f"SKIP bond yields: unexpected columns {list(df.columns)}")
        return

    df["date"] = pd.to_datetime(df.get("date_", df.get("date")))
    df = df.dropna(subset=["date", "close_"])

    # Map mnemonic → ISO2
    df["country"] = df["dsmnemonic"].map(MNEMONIC_TO_ISO2)
    unmapped = df[df["country"].isna()]["dsmnemonic"].unique()
    if len(unmapped):
        print(f"  WARNING: unmapped mnemonics (dropped): {list(unmapped)}")
    df = df.dropna(subset=["country"])

    df = (
        df.sort_values(["date", "country"])
        .groupby(["date", "country"], as_index=False)["close_"]
        .last()
    )

    wide = (
        df.pivot_table(index="date", columns="country", values="close_", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .sort_values("date")
    )

    n_countries = wide.shape[1] - 1
    print(f"Bond yields: {len(wide):,} dates × {n_countries} countries | "
          f"{wide.date.min().date()} – {wide.date.max().date()}")
    save(wide, OUT_DIR / "bond_yield_10y_wide", write_csv)


def main() -> None:
    args = parse_args()
    clean_cbpol(args.csv)
    clean_bond_yields(args.csv)


if __name__ == "__main__":
    main()
