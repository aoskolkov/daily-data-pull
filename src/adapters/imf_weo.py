"""
Adapter for IMF World Economic Outlook (WEO) database.

The WEO is published twice a year (April and October) and covers ~190 countries
from the 1980s through a 5-year projection horizon. It is the IMF's flagship
source for fiscal variables (revenue, expenditure, primary balance, gross debt)
as well as GDP, inflation, current account, and unemployment.

This adapter downloads the tab-delimited bulk file directly from imf.org
(not the SDMX API, which is blocked on some networks).

Config keys (datasets.yaml)
----------------------------
  source:    imf_weo
  year:      2024          # WEO edition year
  edition:   2             # 1=April, 2=October
  subjects:  [GGREV, GGXCNL, GGXWDG]   # WEO subject codes; empty = all
  start:     "1980"        # drop projections and very old data before this year
  incremental_key: date

Selected WEO subject codes
---------------------------
  NGDPD       GDP, current USD (billions)
  NGDP_R      GDP, constant prices (index)
  NGDP_RPCH   GDP growth rate (%)
  PCPIPCH     Inflation rate, CPI (%)
  LUR         Unemployment rate (%)
  BCA         Current account balance (USD billions)
  BCA_NGDPD   Current account balance (% GDP)
  GGREV       General govt revenue (% GDP)
  GGEXP       General govt total expenditure (% GDP)
  GGXCNL      General govt net lending/borrowing (% GDP)  ← fiscal balance
  GGPB        General govt primary balance (% GDP)
  GGXWDG      General govt gross debt (% GDP)
  GGXWDN      General govt net debt (% GDP)
  GGR_NGDP    General govt revenue (% GDP)  [alternative code]

Output columns
--------------
  date, iso3c, country, subject_code, subject_descriptor, units, value
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

# IMF WEO bulk download URL pattern.
# year: 4-digit year; edition: 1 (April) or 2 (October)
_EDITION_LABELS = {1: "Apr", 2: "Oct"}
_EDITION_FULL  = {1: "April", 2: "October"}
# New CDN path (replaces the old /external/pubs/ft/weo/... path which now 404s)
_WEO_URL_TEMPLATE = (
    "https://www.imf.org/-/media/Files/Publications/WEO/WEO-Database/"
    "{year}/{month_full}/WEO{month}{year}all.xls"
)

# Local cache path — avoids re-downloading if file already present for same edition
_CACHE_DIR = Path("downloads/imf_weo")


def _edition_url(year: int, edition: int) -> str:
    month = _EDITION_LABELS[edition]
    month_full = _EDITION_FULL[edition]
    return _WEO_URL_TEMPLATE.format(year=year, month=month, month_full=month_full)


def _cache_path(year: int, edition: int) -> Path:
    month = _EDITION_LABELS[edition]
    return _CACHE_DIR / f"WEO{month}{year}all.xls"


def _download(year: int, edition: int) -> Path:
    import requests

    dest = _cache_path(year, edition)
    if dest.exists():
        print(f"  Using cached file: {dest}")
        return dest

    url = _edition_url(year, edition)
    print(f"  Downloading IMF WEO {_EDITION_LABELS[edition]}{year} from {url}...")
    dest.parent.mkdir(parents=True, exist_ok=True)

    resp = requests.get(url, timeout=120)
    if resp.status_code == 404:
        raise FileNotFoundError(
            f"WEO file not found at {url}.\n"
            f"Check that year={year} and edition={edition} are correct.\n"
            f"Editions: 1=April, 2=October."
        )
    resp.raise_for_status()
    if resp.content[:9].lower().startswith(b"<!doctype"):
        raise RuntimeError(
            f"IMF returned an HTML page instead of a data file.\n"
            f"URL may have changed: {url}"
        )

    dest.write_bytes(resp.content)
    print(f"  Saved to {dest} ({len(resp.content):,} bytes)")
    return dest


def _parse_weo(path: Path, subjects: list[str], start: str) -> pd.DataFrame:
    """
    Parse the WEO Excel/tab-delimited file into a long DataFrame.
    The WEO file uses tab-separated .xls format (actually TSV with .xls extension).
    """
    # WEO .xls files are UTF-16 LE tab-delimited text (not binary Excel)
    try:
        df = pd.read_csv(str(path), sep="\t", encoding="utf-16-le", low_memory=False)
    except Exception:
        df = pd.read_csv(str(path), sep="\t", encoding="utf-16", low_memory=False)

    df.columns = df.columns.str.strip()

    # Filter subjects if specified
    if subjects:
        subj_col = next((c for c in df.columns if "WEO Subject Code" in c or c == "WEO Subject Code"), None)
        if subj_col:
            df = df[df[subj_col].isin(subjects)]

    # Identify year columns (they look like 4-digit integers: 1980, 1981, ...)
    year_cols = [c for c in df.columns if str(c).strip().isdigit() and 1970 <= int(str(c).strip()) <= 2040]
    if not year_cols:
        raise ValueError(f"No year columns found in WEO file. Columns: {list(df.columns)[:20]}")

    # Identify metadata columns
    meta_cols = [c for c in df.columns if c not in year_cols]

    # Melt to long format
    long = df.melt(id_vars=meta_cols, value_vars=year_cols, var_name="_year", value_name="value")
    long["_year"] = long["_year"].astype(str).str.strip().astype(int)
    long["date"] = pd.to_datetime(long["_year"].astype(str) + "-01-01")

    # Clean value: remove commas and "n/a" markers
    long["value"] = (
        long["value"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("--", "", regex=False)
        .str.strip()
    )
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"])

    # Date filter
    long = long[long["date"] >= pd.to_datetime(start + "-01-01")]

    # Standardise key column names — WEO column names change slightly across editions
    col_map: dict[str, str] = {}
    for c in meta_cols:
        lc = c.strip().lower()
        if "iso" in lc and "country" in lc:
            col_map[c] = "iso3c"
        elif lc == "country" or lc == "country name":
            col_map[c] = "country"
        elif "subject code" in lc:
            col_map[c] = "subject_code"
        elif "subject descriptor" in lc:
            col_map[c] = "subject_descriptor"
        elif "units" in lc:
            col_map[c] = "units"
        elif "scale" in lc:
            col_map[c] = "scale"
    long = long.rename(columns=col_map)

    keep = [c for c in ["date", "iso3c", "country", "subject_code", "subject_descriptor", "units", "value"]
            if c in long.columns]
    long = long[keep].sort_values(["subject_code", "date", "iso3c"] if "iso3c" in keep else ["date"]).reset_index(drop=True)
    return long


def pull(conn, config: dict, watermark=None) -> pd.DataFrame:
    year: int = int(config.get("year", 2024))
    edition: int = int(config.get("edition", 2))
    subjects: list[str] = config.get("subjects", [])
    start: str = str(config.get("start", "1980"))

    path = _download(year, edition)
    df = _parse_weo(path, subjects, start)

    if watermark is not None:
        df = df[df["date"] > pd.to_datetime(str(watermark))]

    n_countries = df["iso3c"].nunique() if "iso3c" in df.columns else df["country"].nunique() if "country" in df.columns else "?"
    n_subjects = df["subject_code"].nunique() if "subject_code" in df.columns else "?"
    print(f"  {len(df):,} rows, {n_subjects} subjects, {n_countries} countries, "
          f"{df['date'].min().year} – {df['date'].max().year}")
    return df
