"""
Clean WDI value added by sector → macrodata/sectors/.

Reads:  data/wb_sectors/   (World Bank WDI, annual 1960–2025)
Writes: macrodata/sectors/{label}_wide.{parquet,csv}   date x ISO3, one file per series
        macrodata/sectors/sectors_long.{parquet,csv}   date, iso3c, label, value
        macrodata/sectors/sectors_meta.csv             label -> WDI code, unit, coverage

WDI has four sectors only: agriculture, industry (including construction),
manufacturing (a subset of industry) and services. Agriculture + industry +
services is GDP at basic prices; the gap to GDP is taxes less subsidies on
products. Finer ISIC detail is not available from WDI or the IMF.

Aggregates (world, income and region groups) are dropped from the wide files;
they stay in sectors_long with is_aggregate=True.

Usage
-----
  python clean/sectors.py
  python clean/sectors.py --no-csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from _paths import DATA_ROOT, MACRODATA_ROOT

SRC = DATA_ROOT / "wb_sectors"
OUT = MACRODATA_ROOT / "sectors"

# WDI code -> (output label, unit)
SERIES: dict[str, tuple[str, str]] = {
    "NV.AGR.TOTL.KD":    ("va_agriculture_real",    "constant 2015 US$"),
    "NV.IND.TOTL.KD":    ("va_industry_real",       "constant 2015 US$"),
    "NV.IND.MANF.KD":    ("va_manufacturing_real",  "constant 2015 US$"),
    "NV.SRV.TOTL.KD":    ("va_services_real",       "constant 2015 US$"),
    "NV.AGR.TOTL.CD":    ("va_agriculture_usd",     "current US$"),
    "NV.IND.TOTL.CD":    ("va_industry_usd",        "current US$"),
    "NV.IND.MANF.CD":    ("va_manufacturing_usd",   "current US$"),
    "NV.SRV.TOTL.CD":    ("va_services_usd",        "current US$"),
    "NV.AGR.TOTL.ZS":    ("va_agriculture_share",   "% of GDP"),
    "NV.IND.TOTL.ZS":    ("va_industry_share",      "% of GDP"),
    "NV.IND.MANF.ZS":    ("va_manufacturing_share", "% of GDP"),
    "NV.SRV.TOTL.ZS":    ("va_services_share",      "% of GDP"),
    "NV.AGR.TOTL.KD.ZG": ("va_agriculture_growth",  "% per year"),
    "NV.IND.TOTL.KD.ZG": ("va_industry_growth",     "% per year"),
    "NV.IND.MANF.KD.ZG": ("va_manufacturing_growth", "% per year"),
    "NV.SRV.TOTL.KD.ZG": ("va_services_growth",     "% per year"),
    "NV.AGR.EMPL.KD":    ("va_per_worker_agriculture", "constant 2015 US$ per worker"),
    "NV.IND.EMPL.KD":    ("va_per_worker_industry",    "constant 2015 US$ per worker"),
    "NV.SRV.EMPL.KD":    ("va_per_worker_services",    "constant 2015 US$ per worker"),
    "SL.AGR.EMPL.ZS":    ("emp_share_agriculture",  "% of employment (ILO modelled)"),
    "SL.IND.EMPL.ZS":    ("emp_share_industry",     "% of employment (ILO modelled)"),
    "SL.SRV.EMPL.ZS":    ("emp_share_services",     "% of employment (ILO modelled)"),
    "NV.MNF.FBTO.ZS.UN": ("manf_food_beverages_tobacco", "% of manufacturing VA (sparse)"),
    "NV.MNF.TXTL.ZS.UN": ("manf_textiles_clothing", "% of manufacturing VA (sparse)"),
    "NV.MNF.CHEM.ZS.UN": ("manf_chemicals",         "% of manufacturing VA (sparse)"),
    "NV.MNF.MTRN.ZS.UN": ("manf_machinery_transport", "% of manufacturing VA (sparse)"),
    "NV.MNF.TECH.ZS.UN": ("manf_medium_high_tech",  "% of manufacturing VA (sparse)"),
    "NV.MNF.OTHR.ZS.UN": ("manf_other",             "% of manufacturing VA (sparse)"),
}


def save(df: pd.DataFrame, stem: str, csv: bool, index: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"{stem}.parquet", index=index)
    if csv:
        df.to_csv(OUT / f"{stem}.csv", index=index)


def main(csv: bool = True) -> None:
    if not SRC.exists() or not any(SRC.iterdir()):
        print(f"sectors: no data in {SRC.name} — run: python wrdsdl.py pull wb_sectors")
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
         .sort_values(["label", "iso3c", "date"]), "sectors_long", csv)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(meta).to_csv(OUT / "sectors_meta.csv", index=False)
    print(f"  -> sectors_long, sectors_meta.csv in {OUT}")


if __name__ == "__main__":
    main(csv="--no-csv" not in sys.argv)
