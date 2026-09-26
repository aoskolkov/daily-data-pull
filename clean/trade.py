"""
Clean IMF trade in goods → macrodata/trade/.

Reads:  data/imf_trade_goods_m/    ITG monthly, ~108 economies, 1957-01–
        data/imf_trade_goods_a/    ITG annual, 191 economies, 1948–
        data/imf_trade_bilateral/  IMTS annual reporter x partner, 1948–

Writes: macrodata/trade/goods_{exports,imports,balance}_{monthly,annual}_wide.{parquet,csv}
            date x reporter ISO3, USD. Exports are FOB, imports CIF, so the
            balance is not the BPM6 trade balance (imports include freight and
            insurance); imf_bop goods_net is the BPM6 figure.
        macrodata/trade/trade_goods_long.{parquet,csv}       date, iso3c, freq, indicator, value
        macrodata/trade/bilateral_trade_long.parquet         year, reporter, partner, indicator, value
        macrodata/trade/bilateral_{exports,imports}_{year}.{parquet,csv}  matrix for --matrix YEAR
        macrodata/trade/trade_meta.csv

Counterpart codes that are not ISO3 economies (IMF aggregates such as W00 =
world, plus "not specified" codes) are dropped from the bilateral matrices and
listed in trade_meta.csv.

Usage
-----
  python clean/trade.py
  python clean/trade.py --matrix 2024     # also write reporter x partner matrices
  python clean/trade.py --no-csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "macrodata" / "trade"

_ISO3 = r"^[A-Z]{3}$"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean IMF trade in goods (ITG totals + IMTS bilateral).")
    p.add_argument("--matrix", metavar="YEAR", type=int, default=None,
                   help="Also write reporter x partner matrices for this year")
    p.add_argument("--no-csv", action="store_false", dest="csv")
    p.set_defaults(csv=True)
    return p.parse_args()


def _load(name: str) -> pd.DataFrame | None:
    path = DATA / name
    if not path.exists() or not any(path.iterdir()):
        print(f"  Skipping {name}: not yet pulled  (python wrdsdl.py pull {name})")
        return None
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.dropna(subset=["value"])


def _save(df: pd.DataFrame, stem: str, csv: bool, index: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"{stem}.parquet", index=index)
    if csv:
        df.to_csv(OUT / f"{stem}.csv", index=index)
    print(f"  -> {stem}.parquet{'  + .csv' if csv else ''}")


def totals(df: pd.DataFrame, freq_label: str, csv: bool) -> pd.DataFrame:
    """Wide exports/imports/balance per reporter; returns the long frame."""
    long = df[["date", "country", "indicator", "value"]].rename(columns={"country": "iso3c"})
    long = long[long["iso3c"].str.match(_ISO3, na=False)]

    wide = long.pivot_table(index="date", columns=["indicator", "iso3c"], values="value", aggfunc="last")
    for ind, stem in [("exports_fob_usd", "goods_exports"), ("imports_cif_usd", "goods_imports")]:
        if ind in wide.columns.get_level_values(0):
            _save(wide[ind].sort_index().reset_index(), f"{stem}_{freq_label}_wide", csv)

    if {"exports_fob_usd", "imports_cif_usd"} <= set(wide.columns.get_level_values(0)):
        bal = (wide["exports_fob_usd"] - wide["imports_cif_usd"]).sort_index()
        _save(bal.reset_index(), f"goods_balance_{freq_label}_wide", csv)

    n = long["iso3c"].nunique()
    print(f"  {freq_label}: {len(long):,} obs, {n} economies, "
          f"{long['date'].min().date()} – {long['date'].max().date()}")
    return long.assign(freq=freq_label)


def bilateral(df: pd.DataFrame, csv: bool, matrix_year: int | None) -> list[str]:
    """Long reporter x partner file; returns the dropped non-ISO3 partner codes."""
    df = df.rename(columns={"country": "reporter", "counterpart_country": "partner"})
    df["year"] = df["date"].dt.year
    keep = df["reporter"].str.match(_ISO3, na=False) & df["partner"].str.match(_ISO3, na=False)
    codes = set(df["partner"].dropna()) | set(df["reporter"].dropna())
    dropped = sorted(c for c in codes if not pd.Series([c]).str.match(_ISO3).iat[0])

    long = (df.loc[keep, ["year", "reporter", "partner", "indicator", "value"]]
            .sort_values(["year", "reporter", "partner", "indicator"])
            .reset_index(drop=True))
    _save(long, "bilateral_trade_long", csv)
    print(f"  bilateral: {len(long):,} obs, {long['reporter'].nunique()} reporters x "
          f"{long['partner'].nunique()} partners, {long['year'].min()}–{long['year'].max()}"
          + (f"; dropped {len(dropped)} non-ISO3 codes" if dropped else ""))

    if matrix_year:
        for ind, stem in [("exports_fob_usd", "bilateral_exports"), ("imports_cif_usd", "bilateral_imports")]:
            sub = long[(long["year"] == matrix_year) & (long["indicator"] == ind)]
            if sub.empty:
                continue
            mat = sub.pivot_table(index="reporter", columns="partner", values="value", aggfunc="last")
            mat.columns.name = None
            _save(mat.reset_index(), f"{stem}_{matrix_year}", csv)
            print(f"  matrix {ind} {matrix_year}: {mat.shape[0]} x {mat.shape[1]}")
    return dropped


def main() -> None:
    args = parse_args()
    longs: list[pd.DataFrame] = []

    for name, label in [("imf_trade_goods_m", "monthly"), ("imf_trade_goods_a", "annual")]:
        df = _load(name)
        if df is not None:
            longs.append(totals(df, label, args.csv))

    if longs:
        _save(pd.concat(longs, ignore_index=True).sort_values(["freq", "date", "iso3c", "indicator"]),
              "trade_goods_long", args.csv)

    dropped: list[str] = []
    bil = _load("imf_trade_bilateral")
    if bil is not None:
        dropped = bilateral(bil, args.csv, args.matrix)

    if longs or bil is not None:
        OUT.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{
            "source": "IMF ITG (country totals) + IMTS (bilateral), api.imf.org",
            "units": "USD",
            "exports": "free on board (FOB)",
            "imports": "cost, insurance and freight (CIF) — balance is not BPM6; see imf_bop goods_net",
            "dropped_partner_codes": ";".join(dropped),
        }]).to_csv(OUT / "trade_meta.csv", index=False)
        print("  -> trade_meta.csv")


if __name__ == "__main__":
    main()
