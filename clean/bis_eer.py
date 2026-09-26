"""
Clean BIS effective exchange rate data → macrodata/bis_eer/.

Reads:  data/bis_eer_real/     (REER, broad basket, 64 countries, monthly 1994–)
        data/bis_eer_nominal/  (NEER, narrow basket, 26 countries, monthly 1964–)
Writes: macrodata/bis_eer/reer_wide.{parquet,csv}   — real EER (ISO2 columns)
        macrodata/bis_eer/neer_wide.{parquet,csv}   — nominal EER (ISO2 columns)
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "macrodata" / "bis_eer"


def _clean_one(data_dir: Path, label: str, no_csv: bool) -> None:
    if not data_dir.exists() or not any(data_dir.iterdir()):
        print(f"bis_eer: no data in {data_dir.relative_to(ROOT)} — skipping")
        return

    df = pd.read_parquet(data_dir)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    # Pivot: rows=date, cols=ISO2
    sub = df.dropna(subset=["obs_value"])
    sub = sub.groupby(["date", "ref_area"])["obs_value"].last().reset_index()
    wide = sub.pivot(index="date", columns="ref_area", values="obs_value").sort_index()
    wide.columns.name = None
    wide.index.name = "date"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / label
    wide.to_parquet(str(out) + ".parquet")
    if not no_csv:
        wide.to_csv(str(out) + ".csv")
    print(f"  {label}: {wide.shape[0]} dates x {wide.shape[1]} countries"
          f" -> macrodata/bis_eer/{label}.parquet")


def main(no_csv: bool = False) -> None:
    _clean_one(ROOT / "data" / "bis_eer_real",    "reer_wide",  no_csv)
    _clean_one(ROOT / "data" / "bis_eer_nominal", "neer_wide",  no_csv)


if __name__ == "__main__":
    main(no_csv="--no-csv" in sys.argv)
