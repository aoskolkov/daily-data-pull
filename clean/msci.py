"""
Clean MSCI equity index data → macrodata/msci/.

Reads:  data/msci/   (long Parquet: date, iso2, gross_tr, price_idx)
Writes: macrodata/msci/msci_gross_tr_wide.{parquet,csv}   — gross total return index
        macrodata/msci/msci_price_wide.{parquet,csv}       — price return index
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "msci_indices"
OUT_DIR = ROOT / "macrodata" / "msci"


def main(no_csv: bool = False) -> None:
    if not DATA_DIR.exists() or not any(DATA_DIR.iterdir()):
        print("msci: no data in data/msci/ — run: python wrdsdl.py pull msci_indices")
        return

    df = pd.read_parquet(DATA_DIR)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for col, label in [("gross_tr", "msci_gross_tr_wide"), ("price_idx", "msci_price_wide")]:
        sub = df.dropna(subset=[col])
        # Deduplicate (date, iso2) across partition boundaries
        sub = sub.groupby(["date", "iso2"])[col].last().reset_index()
        wide = sub.pivot(index="date", columns="iso2", values=col).sort_index()
        wide.columns.name = None
        wide.index.name = "date"

        out_path = OUT_DIR / label
        wide.to_parquet(str(out_path) + ".parquet")
        if not no_csv:
            wide.to_csv(str(out_path) + ".csv")
        print(f"  {label}: {wide.shape[0]} dates × {wide.shape[1]} countries"
              f" → macrodata/msci/{label}.parquet")


if __name__ == "__main__":
    main(no_csv="--no-csv" in sys.argv)
