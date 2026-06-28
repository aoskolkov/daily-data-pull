"""
Adapter for MSCI Standard (Large+Mid Cap) country equity index data.

Uses MSCI's public webapp endpoint — no API key required.
Downloads monthly gross total return and price return index levels in USD.

Config keys:
  start        earliest date to pull (default "1990-01-01")
  frequency    "M" monthly (default) or "Q" quarterly

Russia (code 92392) is excluded: MSCI suspended the index post Feb 2022
and the endpoint returns HTTP 500 for that code.
"""

from __future__ import annotations

import io
import time
from datetime import date

import pandas as pd
import requests

# Standard (Large+Mid Cap) country indices: ISO2 → MSCI download code
_COUNTRY_CODES: dict[str, str] = {
    "AU": "60,C,30",    "AT": "61,C,30",    "BE": "62,C,30",    "BR": "63,C,30",
    "CA": "64,C,30",    "CL": "65,C,30",    "CN": "2713,C,30",  "CO": "1890,C,30",
    "CZ": "68,C,30",    "DK": "69,C,30",    "EG": "2877,C,30",  "FI": "70,C,30",
    "FR": "71,C,30",    "DE": "73,C,30",    "GR": "1146,C,30",  "HK": "75,C,30",
    "HU": "76,C,30",    "IN": "77,C,30",    "ID": "2879,C,30",  "IE": "79,C,30",
    "IL": "2352,C,30",  "IT": "81,C,30",    "JP": "83,C,30",    "KR": "85,C,30",
    "MY": "2880,C,30",  "MX": "2,C,30",     "NL": "89,C,30",    "NZ": "90,C,30",
    "NO": "91,C,30",    "PE": "2323,C,30",  "PH": "4,C,30",     "PL": "95,C,30",
    "PT": "1190,C,30",  "QA": "25558,C,30", "SG": "181,C,30",   "ZA": "2428,C,30",
    "ES": "98,C,30",    "SE": "99,C,30",    "CH": "100,C,30",   "TW": "66,C,30",
    "TH": "2881,C,30",  "TR": "102,C,30",   "AE": "25560,C,30", "GB": "103,C,30",
    "US": "104,C,30",
}

# Verbose column names returned by the endpoint → ISO2
_COL_TO_ISO2: dict[str, str] = {
    "AUSTRALIA Standard (Large+Mid Cap) ": "AU",
    "AUSTRIA Standard (Large+Mid Cap) ": "AT",
    "BELGIUM Standard (Large+Mid Cap) ": "BE",
    "BRAZIL Standard (Large+Mid Cap) ": "BR",
    "CANADA Standard (Large+Mid Cap) ": "CA",
    "CHILE Standard (Large+Mid Cap) ": "CL",
    "CHINA Standard (Large+Mid Cap) ": "CN",
    "COLOMBIA Standard (Large+Mid Cap) ": "CO",
    "CZECH REPUBLIC Standard (Large+Mid Cap) ": "CZ",
    "DENMARK Standard (Large+Mid Cap) ": "DK",
    "EGYPT Standard (Large+Mid Cap) ": "EG",
    "FINLAND Standard (Large+Mid Cap) ": "FI",
    "FRANCE Standard (Large+Mid Cap) ": "FR",
    "GERMANY Standard (Large+Mid Cap) ": "DE",
    "GREECE Standard (Large+Mid Cap) ": "GR",
    "HONG KONG Standard (Large+Mid Cap) ": "HK",
    "HUNGARY Standard (Large+Mid Cap) ": "HU",
    "INDIA Standard (Large+Mid Cap) ": "IN",
    "INDONESIA Standard (Large+Mid Cap) ": "ID",
    "IRELAND Standard (Large+Mid Cap) ": "IE",
    "ISRAEL Standard (Large+Mid Cap) ": "IL",
    "ITALY Standard (Large+Mid Cap) ": "IT",
    "JAPAN Standard (Large+Mid Cap) ": "JP",
    "KOREA Standard (Large+Mid Cap) ": "KR",
    "MALAYSIA Standard (Large+Mid Cap) ": "MY",
    "MEXICO Standard (Large+Mid Cap) ": "MX",
    "NETHERLANDS Standard (Large+Mid Cap) ": "NL",
    "NEW ZEALAND Standard (Large+Mid Cap) ": "NZ",
    "NORWAY Standard (Large+Mid Cap) ": "NO",
    "PERU Standard (Large+Mid Cap) ": "PE",
    "PHILIPPINES Standard (Large+Mid Cap) ": "PH",
    "POLAND Standard (Large+Mid Cap) ": "PL",
    "PORTUGAL Standard (Large+Mid Cap) ": "PT",
    "QATAR Standard (Large+Mid Cap) ": "QA",
    "SINGAPORE Standard (Large+Mid Cap) ": "SG",
    "SOUTH AFRICA Standard (Large+Mid Cap) ": "ZA",
    "SPAIN Standard (Large+Mid Cap) ": "ES",
    "SWEDEN Standard (Large+Mid Cap) ": "SE",
    "SWITZERLAND Standard (Large+Mid Cap) ": "CH",
    "TAIWAN Standard (Large+Mid Cap) ": "TW",
    "THAILAND Standard (Large+Mid Cap) ": "TH",
    "TURKEY Standard (Large+Mid Cap) ": "TR",
    "UNITED ARAB EMIRATES Standard (Large+Mid Cap) ": "AE",
    "UNITED KINGDOM Standard (Large+Mid Cap) ": "GB",
    "USA Standard (Large+Mid Cap) ": "US",
}

_BASE_URL = "https://www.msci.com/webapp/indexperf/charts"
_PRICE_LEVEL = {"gross": 41, "price": 0}
_CURRENCY_USD = 15
_BATCH_SIZE = 20  # max countries per request


def _fmt_date(dt: str) -> str:
    """Convert YYYY-MM-DD to MSCI's 'D Mon, YYYY' format (no leading zero on day)."""
    d = pd.Timestamp(dt)
    return f"{d.day} {d.strftime('%b')}, {d.year}"


def _fetch_one_batch(
    codes: list[str],
    start: str,
    end: str,
    price_level: int,
    frequency: str,
) -> pd.DataFrame:
    """Download a single batch of index codes; return raw wide DataFrame."""
    indices_str = "|".join(codes)
    # Must NOT use requests params= (it URL-encodes | → %7C which breaks the endpoint)
    url = (
        f"{_BASE_URL}?indices={indices_str}"
        f"&startDate={start}&endDate={end}"
        f"&priceLevel={price_level}&currency={_CURRENCY_USD}"
        f"&frequency={frequency}&scope=R&format=XLS&baseValue=false&site=gimi"
    )
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    if len(r.content) < 1000:
        raise RuntimeError(
            f"MSCI endpoint returned only {len(r.content)} bytes. "
            "The endpoint may be rate-limiting or the request is malformed."
        )
    df = pd.read_excel(io.BytesIO(r.content), header=6)
    # XLS has copyright/disclaimer rows after the data — drop them
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df["Date"] = df["Date"].dt.normalize()
    return df.set_index("Date")


def _download_return_type(
    start: str,
    end: str,
    return_type: str,
    frequency: str,
) -> pd.DataFrame:
    """Download all countries for one return type, return wide DataFrame (date × ISO2)."""
    codes = list(_COUNTRY_CODES.values())
    batches = [codes[i : i + _BATCH_SIZE] for i in range(0, len(codes), _BATCH_SIZE)]
    price_level = _PRICE_LEVEL[return_type]

    parts = []
    for i, batch in enumerate(batches):
        if i > 0:
            time.sleep(1)  # brief pause between requests
        df_batch = _fetch_one_batch(batch, start, end, price_level, frequency)
        parts.append(df_batch)

    wide = pd.concat(parts, axis=1)
    # Rename verbose column names to ISO2
    rename = {col: _COL_TO_ISO2[col] for col in wide.columns if col in _COL_TO_ISO2}
    unknown = [c for c in wide.columns if c not in _COL_TO_ISO2]
    if unknown:
        print(f"  WARNING: unrecognised MSCI column(s) — dropping: {unknown}")
    wide = wide[list(rename.keys())].rename(columns=rename)
    return wide


def pull(config: dict, watermark=None) -> pd.DataFrame:
    """
    Pull MSCI country equity index levels.

    Returns long DataFrame with columns: date, iso2, gross_tr, price_idx.
    """
    start = str(watermark) if watermark is not None else config.get("start", "1990-01-01")
    end = str(date.today())
    frequency = config.get("frequency", "M")

    # MSCI endpoint expects dates as "1 Jan, 1990" (no leading zero on day)
    start_fmt = _fmt_date(start)
    end_fmt = _fmt_date(end)

    print(f"  MSCI: pulling {frequency} gross TR + price, {start} → {end} ...")

    gross = _download_return_type(start_fmt, end_fmt, "gross", frequency)
    time.sleep(1)
    price = _download_return_type(start_fmt, end_fmt, "price", frequency)

    gross_long = (
        gross.reset_index()
        .rename(columns={"Date": "date"})
        .melt(id_vars="date", var_name="iso2", value_name="gross_tr")
    )
    price_long = (
        price.reset_index()
        .rename(columns={"Date": "date"})
        .melt(id_vars="date", var_name="iso2", value_name="price_idx")
    )

    df = gross_long.merge(price_long, on=["date", "iso2"], how="outer")
    df = df.dropna(subset=["gross_tr", "price_idx"], how="all").sort_values(["date", "iso2"])
    print(f"  {len(df):,} rows, {df['iso2'].nunique()} countries, "
          f"{df['date'].min().date()} → {df['date'].max().date()}")
    return df.reset_index(drop=True)
