"""
Clean BIS long consumer price series → macrodata/bis_cpi/.

Reads:  data/bis_cpi_long_m/   monthly, 63 economies, 1913-01–
        data/bis_cpi_long_a/   annual, 63 economies, 1700–
Writes: macrodata/bis_cpi/cpi_index_monthly_wide.{parquet,csv}   index, 2010=100
        macrodata/bis_cpi/cpi_yoy_monthly_wide.{parquet,csv}     year-on-year, per cent
        macrodata/bis_cpi/cpi_index_annual_wide.{parquet,csv}
        macrodata/bis_cpi/cpi_yoy_annual_wide.{parquet,csv}
        macrodata/bis_cpi/bis_cpi_meta.csv                       coverage per economy

Columns are ISO2 codes. UNIT_MEASURE 628 = index, 771 = year-on-year per cent
(both published by the BIS, so YoY is not recomputed here).

Much longer than macrodata/cpi_monthly/ (IMF IFS via Datastream: 1950–, 164
countries) but only 63 economies — use the two together.

Usage
-----
  python clean/bis_cpi.py
  python clean/bis_cpi.py --no-csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from _paths import DATA_ROOT, MACRODATA_ROOT

OUT = MACRODATA_ROOT / "bis_cpi"
UNITS = {628: "index", 771: "yoy"}


def _save(wide: pd.DataFrame, stem: str, no_csv: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    wide.to_parquet(OUT / f"{stem}.parquet")
    if not no_csv:
        wide.to_csv(OUT / f"{stem}.csv")
    print(f"  {stem}: {wide.shape[0]} dates x {wide.shape[1]} economies "
          f"({wide.index.min().date()} – {wide.index.max().date()})")


def _clean_one(name: str, freq_label: str, no_csv: bool) -> pd.DataFrame | None:
    src = DATA_ROOT / name
    if not src.exists() or not any(src.iterdir()):
        print(f"bis_cpi: no data in {name} — skipping  (python wrdsdl.py pull {name})")
        return None

    df = pd.read_parquet(src)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.dropna(subset=["obs_value"])

    frames = []
    for code, unit in UNITS.items():
        sub = df[df["unit_measure"] == code]
        if sub.empty:
            continue
        wide = (sub.groupby(["date", "ref_area"])["obs_value"].last()
                .unstack("ref_area").sort_index())
        wide.columns.name = None
        wide.index.name = "date"
        _save(wide, f"cpi_{unit}_{freq_label}_wide", no_csv)
        frames.append(sub.assign(unit=unit))
    return pd.concat(frames, ignore_index=True) if frames else None


def main(no_csv: bool = False) -> None:
    parts = [p for p in (_clean_one("bis_cpi_long_m", "monthly", no_csv),
                         _clean_one("bis_cpi_long_a", "annual", no_csv)) if p is not None]
    if not parts:
        return

    all_obs = pd.concat(parts, ignore_index=True)
    meta = (all_obs.groupby(["ref_area", "freq", "unit"])
            .agg(date_min=("date", "min"), date_max=("date", "max"), obs=("obs_value", "size"))
            .reset_index())
    meta["units"] = meta["unit"].map({"index": "index, 2010=100", "yoy": "per cent per year"})
    OUT.mkdir(parents=True, exist_ok=True)
    meta.to_csv(OUT / "bis_cpi_meta.csv", index=False)
    print(f"  bis_cpi_meta.csv: {meta['ref_area'].nunique()} economies")


if __name__ == "__main__":
    main(no_csv="--no-csv" in sys.argv)
