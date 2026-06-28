"""
Clean Datastream country equity index panel to wide format.

Source
------
  data/ds_equity_indices/   ~47 country indices, daily
  Raw schema: valuedate, dsindexmnem, indexdesc, region, isocurrcode, pi_, ri

pi_ = price index (ex-dividend total price level)
ri  = return index (total return including dividends)

Output
------
  macrodata/equity_indices/equity_pi_wide.parquet / .csv   date × ISO2 country, price index
  macrodata/equity_indices/equity_ri_wide.parquet / .csv   date × ISO2 country, return index
  macrodata/equity_indices/equity_meta.csv                 mnemonic → iso2/country/currency/description

Usage
-----
  python clean/equity_indices.py
  python clean/equity_indices.py --no-csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_STORAGE = "data"
DEFAULT_OUTPUT  = "macrodata/equity_indices"
DATASET_NAME    = "ds_equity_indices"

# Datastream equity index mnemonic → ISO 3166-1 alpha-2 country code.
# Note: D2BRFS$ is DJGL Brazil Financial Services, not IBOVESPA (update mnemonic when fixed).
MNEMONIC_TO_ISO2: dict[str, str] = {
    "DJINDUS": "US",
    "TTOCOMP": "CA",
    "DAXINDX": "DE",
    "FTATNOF": "GB",
    "FTEFRFY": "FR",
    "FITMISE": "IT",
    "MADRIDI": "ES",
    "AMSTEOE": "NL",
    "BRUSIDX": "BE",
    "OMXAFGX": "SE",
    "FTENOKE": "NO",
    "FTEDKKE": "DK",
    "WIFINDL": "FI",
    "FTECHFY": "CH",
    "WIASTR$": "AT",
    "POPSIGN": "PT",
    "GRAGENL": "GR",
    "ISEQUIT": "IE",
    "JAPDOWA": "JP",
    "AUSTOLD": "AU",
    "WINZEAL": "NZ",
    "HNGKNGI": "HK",
    "WISNGP$": "SG",
    "ISTGENS": "IL",
    "CHSCOMP": "CN",
    "IBOMSEN": "IN",
    "KORCOMP": "KR",
    "TAIWGHT": "TW",
    "FBMKLCI": "MY",
    "BNGKSET": "TH",
    "JAKCOMP": "ID",
    "PKSE100": "PK",
    "HCMNVNE": "VN",
    "WIMXCOL": "MX",
    "D2BRFS$": "BR",
    "ARGMERV": "AR",
    "IGPAGEN": "CL",
    "EGHREFG": "EG",
    "NSEINDX": "KE",
    "IFGDNG$": "NG",
    "WISAFRL": "ZA",
    "TRKISTB": "TR",
    "WIRUSSL": "RU",
    "WIPLNDL": "PL",
    "BUXINDX": "HU",
    "SBECZRL": "CZ",
    "IFGDSBL": "SA",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean Datastream equity index panel to wide Parquet/CSV.")
    p.add_argument("--storage-root", default=DEFAULT_STORAGE)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def save(df: pd.DataFrame, stem: Path, write_csv: bool) -> None:
    stem.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(stem.with_suffix(".parquet"), index=False)
    print(f"  -> {stem.with_suffix('.parquet')}")
    if write_csv:
        df.to_csv(stem.with_suffix(".csv"), index=False)
        print(f"  -> {stem.with_suffix('.csv')}")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output)

    path = Path(args.storage_root) / DATASET_NAME
    if not path.exists():
        print(
            "No equity index data found. Pull first:\n"
            "  python wrdsdl.py pull ds_equity_indices",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_parquet(path)
    df.columns = df.columns.str.lower()
    df["date"] = pd.to_datetime(df["valuedate"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date", "dsindexmnem"])

    n_series = df["dsindexmnem"].nunique()
    print(f"  ds_equity_indices: {len(df):,} rows, "
          f"{n_series} indices, "
          f"{df['date'].min().date()} – {df['date'].max().date()}")

    def pivot_field(field: str) -> pd.DataFrame:
        sub = df.dropna(subset=[field])
        wide = (
            sub.groupby(["date", "dsindexmnem"])[field]
            .last()
            .unstack("dsindexmnem")
            .sort_index()
            .rename_axis(index="date", columns=None)
            .reset_index()
        )
        # Rename mnemonic columns → ISO2. Keep unmapped mnemonics as-is.
        rename_map = {m: iso2 for m, iso2 in MNEMONIC_TO_ISO2.items() if m in wide.columns}
        unmapped = [c for c in wide.columns if c != "date" and c not in rename_map]
        if unmapped:
            print(f"    WARNING: no ISO2 mapping for mnemonics (kept as-is): {unmapped}")
        wide = wide.rename(columns=rename_map)
        return wide

    for field, label in [("pi_", "pi"), ("ri", "ri")]:
        if field not in df.columns:
            print(f"  {field} not in data — skipping")
            continue
        wide = pivot_field(field)
        n_cols = wide.shape[1] - 1
        print(f"  equity_{label}_wide: {len(wide):,} dates × {n_cols} countries")
        save(wide, out_dir / f"equity_{label}_wide", args.csv)

    # Metadata: one row per mnemonic with iso2 mapping added
    meta_cols = [c for c in ["dsindexmnem", "indexdesc", "region", "isocurrcode"] if c in df.columns]
    meta = (
        df[meta_cols]
        .drop_duplicates("dsindexmnem")
        .sort_values("dsindexmnem")
        .reset_index(drop=True)
    )
    meta["iso2"] = meta["dsindexmnem"].map(MNEMONIC_TO_ISO2)
    meta_path = out_dir / "equity_meta.csv"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta.to_csv(meta_path, index=False)
    print(f"  -> {meta_path}  ({len(meta)} indices, "
          f"{meta['iso2'].notna().sum()} with ISO2 mapping)")


if __name__ == "__main__":
    main()
