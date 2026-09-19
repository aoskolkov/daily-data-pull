"""
Sovereign external debt, arrears and partial default from World Bank IDS.

Rebuilds the data of Arellano, Mateos-Planas & Ríos-Rull, "Partial Default"
(JPE 2023, 131(6)), following their replication do-file
(Harvard Dataverse doi:10.7910/DVN/GXA5UX, partial_default_data-1.do):

  arrears   = interest + principal arrears, official + private creditors, PPG
              (a stock: "due but not paid, cumulative"; missing counts as 0)
  paydue    = arrears + debt service PPG, missing as 0       (DT.TDS.DPPG.CD)
  partial_default = arrears / paydue if arrears > 0 else 0
  in_default      = partial_default > 1%   (the code's cut-off, not "> 0")
  ratios to output divide by GDP in current US$, not GNI

Data sources and precedence, per country-year:
  1. Current IDS (source 6). Arrears = DT.{I,A}XA.{OFFT,PRVT}.CD — long-term,
     the public stand-in for the PPG arrears the paper got from the restricted
     Debtor Reporting System (the two agree to within 0.1% in aggregate).
  2. For countries IDS no longer covers (graduated to high income): current
     WDI (source 2) for debt and debt service, then the newest WDI archive
     vintage (source 57) holding the value, with DT.{I,A}XA.DPPG.CD arrears.
  IDS carries debt-service projections; years after the last actual debt-stock
  year are dropped.

Input:  data/wb_ids/  data/wb_ids_archive/  data/wb_wdi_macro/
Output: macrodata/sovereign_debt/
  ids_panel               country-year panel (all IDS + archive countries)
  ids_long                every pulled IDS series, long (actual years only)
  partial_default_wide    year x country
  replication_table1.csv  paper's Table 1 moments, paper vs this data

Usage
-----
  python clean/partial_default.py
  python clean/partial_default.py --no-csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "macrodata" / "sovereign_debt"

# The paper's sample: the 37 EMBI+ countries (online appendix), 1970–2019.
EMBI37 = ("ARG BGR BLZ BRA CHL DOM ECU GAB GHA IDN JAM MAR MEX NGA PAK PAN PER PHL POL "
          "RUS SLV SRB TTO TUR UKR URY VEN VNM ZAF CHN COL EGY HUN KOR LKA MYS TUN").split()
PAPER_YEARS = (1970, 2019)
PAPER_TABLE1 = {"frequency": 0.36, "mean_if_default": 0.38, "sd_if_default": 0.22, "episodes": 70}

ARREARS_IDS = ["DT.IXA.OFFT.CD", "DT.IXA.PRVT.CD", "DT.AXA.OFFT.CD", "DT.AXA.PRVT.CD"]
ARREARS_ARCHIVE = ["DT.IXA.DPPG.CD", "DT.AXA.DPPG.CD"]
DEFAULT_CUTOFF = 0.01


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def load(name: str) -> pd.DataFrame | None:
    path = DATA / name
    if not path.exists():
        print(f"Skipping: {name} not yet pulled  (python wrdsdl.py pull {name})")
        return None
    df = pd.read_parquet(path)
    df["year"] = pd.to_datetime(df["date"]).dt.year
    return df


def save(df: pd.DataFrame, stem: str, csv: bool, index: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"{stem}.parquet", index=index)
    if csv:
        df.to_csv(OUT / f"{stem}.csv", index=index)
    print(f"  -> {stem}.parquet{'  + .csv' if csv else ''}")


def wide(df: pd.DataFrame) -> pd.DataFrame:
    """(country, year) x series, last value wins."""
    return df.pivot_table(index=["country", "year"], columns="series", values="value", aggfunc="last")


def build_panel(ids: pd.DataFrame, arch: pd.DataFrame | None, wdi: pd.DataFrame | None) -> pd.DataFrame:
    ids = ids[~ids["is_aggregate"].fillna(False).astype(bool)]
    last_actual = int(ids.loc[ids["series"] == "DT.DOD.DPPG.CD", "year"].max())
    ids = ids[ids["year"] <= last_actual]

    w = wide(ids)
    panel = pd.DataFrame(index=w.index)
    panel["debt_ppg"] = w.get("DT.DOD.DPPG.CD")
    panel["debt_service_ppg"] = w.get("DT.TDS.DPPG.CD")
    for col, s in zip(["arrears_int_off", "arrears_int_priv", "arrears_prin_off", "arrears_prin_priv"], ARREARS_IDS):
        panel[col] = w.get(s)
    panel["arrears_ppg"] = panel[["arrears_int_off", "arrears_int_priv",
                                  "arrears_prin_off", "arrears_prin_priv"]].sum(axis=1, min_count=1)
    panel["data_source"] = "ids"

    # Countries missing from current IDS: WDI, then archive vintages (newest first)
    if arch is not None:
        gone = sorted(set(arch["country"]) - set(ids["country"]))
        parts = []
        if wdi is not None:
            parts.append(wdi[wdi["country"].isin(gone) & wdi["series"].isin(["DT.DOD.DPPG.CD", "DT.TDS.DPPG.CD"])]
                         .assign(rank=0, data_source="wdi"))
        for i, ver in enumerate(sorted(arch["version"].dropna().unique(), reverse=True), start=1):
            parts.append(arch[(arch["version"] == ver) & arch["country"].isin(gone)]
                         .assign(rank=i, data_source=f"wdi_archive_{ver}"))
        fill = (pd.concat(parts, ignore_index=True)
                .sort_values("rank")
                .drop_duplicates(["country", "series", "year"], keep="first"))
        fw = fill.pivot_table(index=["country", "year"], columns="series", values="value", aggfunc="first")
        src = (fill.sort_values(["country", "year", "rank"])
               .groupby(["country", "year"])["data_source"].agg(lambda s: "+".join(dict.fromkeys(s))))
        gp = pd.DataFrame(index=fw.index)
        gp["debt_ppg"] = fw.get("DT.DOD.DPPG.CD")
        gp["debt_service_ppg"] = fw.get("DT.TDS.DPPG.CD")
        gp["arrears_ppg"] = fw[[c for c in ARREARS_ARCHIVE if c in fw.columns]].sum(axis=1, min_count=1)
        gp["data_source"] = src
        panel = pd.concat([panel, gp])

    if wdi is not None:
        m = wide(wdi)
        macro = pd.DataFrame(index=m.index)
        macro["gdp_usd"] = m.get("NY.GDP.MKTP.CD")
        macro["rgdp_const_usd"] = m.get("NY.GDP.MKTP.KD")
        macro["cons_total_const_usd"] = m.get("NE.CON.TOTL.KD")
        macro["cons_hh_const_usd"] = m.get("NE.CON.PRVT.KD")
        panel = panel.join(macro, how="left")

    names = pd.concat([d[["country", "country_name"]] for d in (ids, arch, wdi) if d is not None])
    names = names.dropna().drop_duplicates("country").set_index("country")["country_name"]

    p = panel.reset_index().rename(columns={"country": "iso3c"})
    p.insert(1, "country_name", p["iso3c"].map(names))
    p["arrears_missing"] = p["arrears_ppg"].isna()
    arr = p["arrears_ppg"].fillna(0.0)                       # the paper's egen rowtotal
    p["paydue"] = arr + p["debt_service_ppg"].fillna(0.0)    # rowtotal again
    p["partial_default"] = np.where(arr > 0, arr / p["paydue"], 0.0)
    p["in_default"] = p["partial_default"] > DEFAULT_CUTOFF
    for c in ["debt_ppg", "debt_service_ppg", "arrears_ppg", "paydue"]:
        p[f"{c}_gdp"] = p[c] / p.get("gdp_usd")
    p["embi37"] = p["iso3c"].isin(EMBI37)
    return p.sort_values(["iso3c", "year"]).reset_index(drop=True)


def table1(panel: pd.DataFrame) -> pd.DataFrame:
    """Paper's Table 1 on the balanced 37-country 1970–2019 panel, missing = no default."""
    y0, y1 = PAPER_YEARS
    grid = pd.MultiIndex.from_product([EMBI37, range(y0, y1 + 1)], names=["iso3c", "year"])
    b = panel.set_index(["iso3c", "year"]).reindex(grid)
    pdf = b["partial_default"].fillna(0.0)
    dflt = pdf > DEFAULT_CUTOFF

    runs = (dflt != dflt.groupby(level=0).shift(fill_value=False)) & dflt
    cond = pdf[dflt]
    # do-file: country SD attached to each default year, then averaged over those
    # years (tabstat stdPD), i.e. countries weighted by their number of default years
    sd = cond.groupby(level=0).transform("std").mean()
    debt_gdp = (b["debt_ppg"] / b["gdp_usd"]).replace([np.inf, -np.inf], np.nan)
    ds_gdp = (b["debt_service_ppg"] / b["gdp_usd"]).replace([np.inf, -np.inf], np.nan)
    ours = {
        "frequency": dflt.mean(),
        "mean_if_default": cond.mean(),
        "sd_if_default": sd,
        "episodes": int(runs.sum()),
        "debt_ppg_gdp_mean": debt_gdp.mean(),
        "debt_service_ppg_gdp_mean": ds_gdp.mean(),
        "countries_with_data": int(b["debt_ppg"].notna().groupby(level=0).any().sum()),
    }
    rows = [{"moment": k, "this_data": v, "paper_jpe": PAPER_TABLE1.get(k)} for k, v in ours.items()]
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    ids = load("wb_ids")
    if ids is None:
        raise SystemExit(1)
    arch, wdi = load("wb_ids_archive"), load("wb_wdi_macro")

    panel = build_panel(ids, arch, wdi)
    print(f"  panel: {len(panel):,} country-years, {panel['iso3c'].nunique()} countries, "
          f"{panel['year'].min()}–{panel['year'].max()}; "
          f"{panel.loc[panel['embi37'], 'iso3c'].nunique()}/37 paper countries")
    save(panel, "ids_panel", args.csv)

    last_actual = int(ids.loc[ids["series"] == "DT.DOD.DPPG.CD", "year"].max())
    ids_long = ids.loc[ids["year"] <= last_actual,
                       ["year", "country", "country_name", "is_aggregate", "series", "value"]]
    save(ids_long.rename(columns={"country": "iso3c"}), "ids_long", args.csv)

    pdw = panel.pivot(index="year", columns="iso3c", values="partial_default").reset_index()
    pdw.insert(0, "date", pd.to_datetime(pdw.pop("year").astype(str) + "-01-01"))
    save(pdw, "partial_default_wide", args.csv)

    t1 = table1(panel)
    OUT.mkdir(parents=True, exist_ok=True)
    t1.to_csv(OUT / "replication_table1.csv", index=False)
    print("  -> replication_table1.csv")
    print(t1.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
