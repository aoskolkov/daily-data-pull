"""
Clean WDI final consumption → macrodata/consumption/.

Reads:  data/wb_consumption/   (World Bank WDI, annual 1960–2025)
Writes: macrodata/consumption/{label}_wide.{parquet,csv}    date x ISO3
        macrodata/consumption/consumption_long.{parquet,csv}
        macrodata/consumption/consumption_meta.csv

Consumption is split by who does the consuming — households (including NPISHs),
general government, and the total. WDI has no breakdown by purpose (COICOP) or
by durability. Quarterly consumption for ~93 economies is in
macrodata/na_quarterly/ (IMF QNEA).

Aggregates (world, income and region groups) are dropped from the wide files;
they stay in consumption_long with is_aggregate=True.

Usage
-----
  python clean/consumption.py
  python clean/consumption.py --no-csv
"""

from __future__ import annotations

import sys

import pandas as pd
from _paths import DATA_ROOT, MACRODATA_ROOT

SRC = DATA_ROOT / "wb_consumption"
OUT = MACRODATA_ROOT / "consumption"

SERIES: dict[str, tuple[str, str]] = {
    "NE.CON.PRVT.KD":    ("cons_household_real",     "constant 2015 US$"),
    "NE.CON.PRVT.CD":    ("cons_household_usd",      "current US$"),
    "NE.CON.PRVT.ZS":    ("cons_household_share",    "% of GDP"),
    "NE.CON.PRVT.PC.KD": ("cons_household_pc_real",  "constant 2015 US$ per capita"),
    "NE.CON.PRVT.KD.ZG": ("cons_household_growth",   "% per year"),
    "NE.CON.GOVT.KD":    ("cons_government_real",    "constant 2015 US$"),
    "NE.CON.GOVT.CD":    ("cons_government_usd",     "current US$"),
    "NE.CON.GOVT.ZS":    ("cons_government_share",   "% of GDP"),
    "NE.CON.GOVT.KD.ZG": ("cons_government_growth",  "% per year"),
    "NE.CON.TOTL.KD":    ("cons_total_real",         "constant 2015 US$"),
    "NE.CON.TOTL.CD":    ("cons_total_usd",          "current US$"),
    "NE.CON.TOTL.ZS":    ("cons_total_share",        "% of GDP"),
    "NE.CON.TOTL.KD.ZG": ("cons_total_growth",       "% per year"),
    "NY.GDP.MKTP.KD":    ("gdp_real",                "constant 2015 US$"),
}


def save(df: pd.DataFrame, stem: str, csv: bool, index: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"{stem}.parquet", index=index)
    if csv:
        df.to_csv(OUT / f"{stem}.csv", index=index)


def main(csv: bool = True) -> None:
    if not SRC.exists() or not any(SRC.iterdir()):
        print(f"consumption: no data in {SRC.name} — run: python wrdsdl.py pull wb_consumption")
        return

    df = pd.read_parquet(SRC)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.dropna(subset=["value"]).rename(columns={"country": "iso3c"})
    df["label"] = df["series"].map(lambda s: SERIES.get(s, (s, ""))[0])

    countries = df[~df["is_aggregate"].fillna(False).astype(bool)]
    meta = []
    for code, (label, unit) in SERIES.items():
        sub = countries[countries["series"] == code]
        if sub.empty:
            print(f"  {label}: no data"); continue
        wide = (sub.groupby(["date", "iso3c"])["value"].last().unstack("iso3c").sort_index())
        wide.columns.name = None
        save(wide.reset_index(), f"{label}_wide", csv)
        meta.append({"label": label, "wdi_code": code, "unit": unit,
                     "economies": wide.shape[1], "date_min": wide.index.min().year,
                     "date_max": wide.index.max().year, "obs": len(sub)})
    print(f"  wrote {len(meta)} wide files, {countries['iso3c'].nunique()} economies, "
          f"{df['date'].min().year}–{df['date'].max().year}")

    save(df[["date", "iso3c", "country_name", "is_aggregate", "series", "label", "value"]]
         .sort_values(["label", "iso3c", "date"]), "consumption_long", csv)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(meta).to_csv(OUT / "consumption_meta.csv", index=False)
    print(f"  -> consumption_long, consumption_meta.csv in {OUT}")


if __name__ == "__main__":
    main(csv="--no-csv" not in sys.argv)
