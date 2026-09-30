"""
Clean IMF quarterly national accounts → macrodata/na_quarterly/.

Reads:  data/imf_na_quarterly/   (IMF QNEA, 1990-Q1–present)
Writes: macrodata/na_quarterly/{label}_{real|nominal}_{sa|nsa}_wide.{parquet,csv}
            date x ISO3, values in domestic currency
        macrodata/na_quarterly/na_quarterly_long.{parquet,csv}
        macrodata/na_quarterly/na_quarterly_meta.csv   coverage per series

The only quarterly output and consumption data in this repo. Values are in
**domestic currency**, so they are not comparable across countries in levels —
use growth rates, ratios to GDP, or convert with macrodata/fx_spot/.

Coverage thins with detail: GDP ~115 economies, total and government consumption
~93–98, household-only consumption ~31. Seasonally adjusted (SA) and unadjusted
(NSA) are both kept; many economies publish only one of them.

Usage
-----
  python clean/na_quarterly.py
  python clean/na_quarterly.py --no-csv
"""

from __future__ import annotations

import sys

import pandas as pd
from _paths import DATA_ROOT, MACRODATA_ROOT

SRC = DATA_ROOT / "imf_na_quarterly"
OUT = MACRODATA_ROOT / "na_quarterly"

PRICE = {"Q": "real", "V": "nominal"}     # constant / current prices
ADJ = {"SA": "sa", "NSA": "nsa"}


def save(df: pd.DataFrame, stem: str, csv: bool, index: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"{stem}.parquet", index=index)
    if csv:
        df.to_csv(OUT / f"{stem}.csv", index=index)


def main(csv: bool = True) -> None:
    if not SRC.exists() or not any(SRC.iterdir()):
        print(f"na_quarterly: no data in {SRC.name} — run: python wrdsdl.py pull imf_na_quarterly")
        return

    df = pd.read_parquet(SRC)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.dropna(subset=["value"]).rename(columns={"country": "iso3c"})

    meta = []
    for (label, price, adj), sub in df.groupby(["indicator", "price_type", "s_adjustment"]):
        if price not in PRICE or adj not in ADJ:
            continue
        wide = (sub.groupby(["date", "iso3c"])["value"].last().unstack("iso3c").sort_index())
        wide.columns.name = None
        stem = f"{label}_{PRICE[price]}_{ADJ[adj]}_wide"
        save(wide.reset_index(), stem, csv)
        meta.append({"file": stem, "indicator": label, "prices": PRICE[price],
                     "adjustment": ADJ[adj], "economies": wide.shape[1],
                     "date_min": str(wide.index.min().date()), "date_max": str(wide.index.max().date()),
                     "obs": len(sub), "units": "domestic currency"})

    m = pd.DataFrame(meta).sort_values(["indicator", "prices", "adjustment"])
    print(f"  wrote {len(m)} wide files, {df['iso3c'].nunique()} economies, "
          f"{df['date'].min().date()} – {df['date'].max().date()}")
    print(m[m.adjustment == "sa"][["indicator", "prices", "economies"]].to_string(index=False))

    save(df[["date", "iso3c", "indicator", "price_type", "s_adjustment", "value"]]
         .sort_values(["indicator", "iso3c", "date"]), "na_quarterly_long", csv)
    OUT.mkdir(parents=True, exist_ok=True)
    m.to_csv(OUT / "na_quarterly_meta.csv", index=False)
    print(f"  -> na_quarterly_long, na_quarterly_meta.csv in {OUT}")


if __name__ == "__main__":
    main(csv="--no-csv" not in sys.argv)
