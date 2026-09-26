"""
Country/currency crosswalk loader and lookup helpers.

The crosswalk CSV (config/currency_country.csv) is the single source of truth
for mapping between iso3c, iso2c, currency codes, and country name variants.
Regenerate it with:  python scripts/build_crosswalk.py

Usage:
  from src.crosswalk import load_crosswalk, currency_to_iso3, iso2_to_iso3

  xw = load_crosswalk()
  countries = currency_to_iso3(xw, "DEM", date="1995-01-01")   # ['DEU']
  countries = currency_to_iso3(xw, "EUR", date="2005-01-01")   # 12 eurozone countries
  iso3  = iso2_to_iso3(xw, "DE")                               # 'DEU'
  iso2  = iso3_to_iso2(xw, "DEU")                              # 'DE'
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

DEFAULT_PATH = Path("config/currency_country.csv")

_CACHED: pd.DataFrame | None = None


def load_crosswalk(path: str | Path | None = None) -> pd.DataFrame:
    """
    Load and cache the crosswalk DataFrame.

    Returns a DataFrame with at minimum these columns:
      iso3c, iso2c, wb_code, currency_code, valid_from, valid_to,
      country_name_en, wb_name, common_name
    """
    global _CACHED
    if _CACHED is not None and path is None:
        return _CACHED

    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"Crosswalk not found at {p.resolve()}\n"
            "Run:  python scripts/build_crosswalk.py"
        )

    df = pd.read_csv(p, dtype=str).fillna("")
    _CACHED = df
    return df


def _parse_date(s: str) -> pd.Timestamp | None:
    if not s:
        return None
    try:
        return pd.Timestamp(s)
    except Exception:
        return None


def currency_to_iso3(xw: pd.DataFrame, currency_code: str, date: str | None = None) -> list[str]:
    """
    Return list of iso3c codes that used `currency_code` at `date`.

    If `date` is None, returns countries currently using that currency
    (rows where valid_to is empty).
    """
    mask = xw["currency_code"].str.upper() == currency_code.upper()

    if date is not None:
        ts = pd.Timestamp(date)
        def _active(row: pd.Series) -> bool:
            vf = _parse_date(row["valid_from"])
            vt = _parse_date(row["valid_to"])
            if vf and ts < vf:
                return False
            if vt and ts > vt:
                return False
            return True
        active = xw[mask].apply(_active, axis=1)
        result = xw[mask][active]["iso3c"].dropna().unique().tolist()
    else:
        result = xw[mask & (xw["valid_to"] == "")]["iso3c"].dropna().unique().tolist()

    return sorted(r for r in result if r)


def iso2_to_iso3(xw: pd.DataFrame, iso2c: str) -> str | None:
    """Return the iso3c code for an iso2c country code (current entry only)."""
    rows = xw[(xw["iso2c"].str.upper() == iso2c.upper()) & (xw["valid_to"] == "")]
    if rows.empty:
        # Fall back to any entry
        rows = xw[xw["iso2c"].str.upper() == iso2c.upper()]
    if rows.empty:
        return None
    v = rows.iloc[0]["iso3c"]
    return v if v else None


def iso3_to_iso2(xw: pd.DataFrame, iso3c: str) -> str | None:
    """Return the iso2c code for an iso3c country code."""
    rows = xw[(xw["iso3c"].str.upper() == iso3c.upper()) & (xw["valid_to"] == "")]
    if rows.empty:
        rows = xw[xw["iso3c"].str.upper() == iso3c.upper()]
    if rows.empty:
        return None
    v = rows.iloc[0]["iso2c"]
    return v if v else None


def map_iso2_to_iso3(xw: pd.DataFrame, series: pd.Series) -> pd.Series:
    """Vectorised iso2c -> iso3c mapping for a whole Series of country codes."""
    lookup = (
        xw[xw["valid_to"] == ""][["iso2c", "iso3c"]]
        .drop_duplicates("iso2c")
        .set_index("iso2c")["iso3c"]
    )
    return series.map(lookup).fillna(series)   # fall back to original if not found


def apply_currency_crosswalk(
    df: pd.DataFrame,
    xw: pd.DataFrame,
    currency_col: str = "currency",
    date_col: str = "date",
) -> pd.DataFrame:
    """
    Expand a (date, currency, ...) DataFrame to (date, iso3c, ...) by
    joining each currency to the countries that used it on that date.

    Rows where the currency maps to multiple countries (e.g. EUR) are
    duplicated — one row per country.  The original currency_col is kept.

    Returns the expanded DataFrame with a new 'iso3c' column.
    """
    if df.empty:
        return df.assign(iso3c="")

    xw_clean = xw[xw["iso3c"] != ""].copy()
    xw_clean["_vf"] = pd.to_datetime(xw_clean["valid_from"], errors="coerce")
    xw_clean["_vt"] = pd.to_datetime(xw_clean["valid_to"],   errors="coerce")

    df = df.copy()
    df["_date"] = pd.to_datetime(df[date_col], errors="coerce")

    # Cross-join on currency code, then filter validity window
    merged = df.merge(
        xw_clean[["currency_code", "iso3c", "_vf", "_vt"]].rename(
            columns={"currency_code": currency_col}
        ),
        on=currency_col,
        how="left",
    )
    valid = (
        (merged["_vf"].isna() | (merged["_date"] >= merged["_vf"])) &
        (merged["_vt"].isna() | (merged["_date"] <= merged["_vt"]))
    )
    result = merged[valid].drop(columns=["_vf", "_vt", "_date"])
    return result.reset_index(drop=True)
