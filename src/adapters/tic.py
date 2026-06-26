"""
Adapter for US Treasury TIC (Treasury International Capital) data.

Fetches the "Major Foreign Holders of Treasury Securities" monthly table
directly from the US Treasury website.

Two source files are used:
  mfhhis01.txt  — full historical archive, 2000–present, multiple year blocks
                  URL: https://treasury.gov/resource-center/data-chart-center/tic/Documents/mfhhis01.txt
  mfh.txt       — rolling current window (~13 months, most recent data)
                  URL: https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/mfh.txt

The adapter fetches both, deduplicates on (date, country), and merges. The
historical file has full coverage back to Jan 2000; the current file fills in
the most recent months not yet in the archive.

Holdings are in billions of USD. Released monthly with roughly a 45-day lag.

Config keys (datasets.yaml)
----------------------------
  source: tic
  start: "2000-01-01"          # filter out data before this date
  incremental_key: date

Output columns
--------------
  date, country, holdings_bln_usd
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd

_MFH_HISTORICAL_URL = (
    "https://treasury.gov/resource-center/data-chart-center/tic/Documents/mfhhis01.txt"
)
_MFH_CURRENT_URL = (
    "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/mfh.txt"
)

_MONTHS = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"}

_SKIP_COUNTRIES = {
    "grand total", "of which:", "for. official",
    "treasury bills", "t-bonds & notes", "all other",
    "memo:", "total foreign",
}


def _fetch(url: str) -> str:
    import requests
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.text


def _parse_block(month_parts: list[str], year: int, data_lines: list[str]) -> list[dict]:
    """Parse one year-block into records."""
    # month_parts: ['', 'Dec', 'Nov', ..., 'Jan', ''] — strip empty tokens
    months = [m.strip() for m in month_parts if m.strip() in _MONTHS]
    if not months:
        return []

    records = []
    for line in data_lines:
        parts = line.split("\t")
        country = parts[0].strip().strip('"')
        if not country or country.lower() in _SKIP_COUNTRIES:
            continue
        if country.startswith(("---", "===", "1/", "2/", "3/", "*")):
            continue
        values = [p.strip() for p in parts[1:] if p.strip()]
        for month, val in zip(months, values):
            if not val or val == "---":
                continue
            try:
                holdings = float(val.replace(",", ""))
            except ValueError:
                continue
            try:
                dt = pd.to_datetime(f"{month} {year}", format="%b %Y")
            except ValueError:
                continue
            records.append({"date": dt, "country": country, "holdings_bln_usd": holdings})

    return records


def _parse_multiyear(text: str) -> pd.DataFrame:
    """
    Parse mfhhis01.txt which contains one tab-delimited block per calendar year.
    Each block: month header row, year row ('Country\t2024\t...'), separator, data rows.
    """
    lines = text.splitlines()
    records: list[dict] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        parts = line.split("\t")
        # Detect year header line: first token '' or 'Country', second token is a 4-digit year
        first = parts[0].strip()
        try:
            year = int(parts[1].strip()) if len(parts) > 1 else 0
        except ValueError:
            year = 0

        if first in ("", "Country") and 1998 <= year <= 2030:
            # The month header is on the line just before (search back)
            month_parts: list[str] = []
            for j in range(i - 1, max(i - 5, -1), -1):
                prev = lines[j]
                prev_tokens = prev.split("\t")
                if any(t.strip() in _MONTHS for t in prev_tokens):
                    month_parts = prev_tokens
                    break

            if not month_parts:
                i += 1
                continue

            # Collect data lines: from i+2 (skip separator) until blank + month/year row or EOF
            data_lines: list[str] = []
            j = i + 2  # skip separator
            while j < len(lines):
                next_line = lines[j]
                next_parts = next_line.split("\t")
                # Stop at the next year-block header
                try:
                    next_year = int(next_parts[1].strip()) if len(next_parts) > 1 else 0
                except ValueError:
                    next_year = 0
                if next_parts[0].strip() in ("", "Country") and 1998 <= next_year <= 2030:
                    break
                data_lines.append(next_line)
                j += 1

            records.extend(_parse_block(month_parts, year, data_lines))
            i = j  # jump to the next block
        else:
            i += 1

    return pd.DataFrame(records)


def _parse_current(text: str) -> pd.DataFrame:
    """Parse the rolling mfh.txt (single block, space-delimited)."""
    lines = text.splitlines()

    header_start = None
    for i, line in enumerate(lines):
        parts = line.split()
        if len(parts) >= 3 and parts[0] in _MONTHS:
            header_start = i
            break

    if header_start is None:
        return pd.DataFrame(columns=["date", "country", "holdings_bln_usd"])

    month_line = lines[header_start].split()
    year_line  = lines[header_start + 1].split()

    # Build (month, year) pairs — skip the first token of year_line (it's "Country")
    month_tokens = month_line          # ['Jan', 'Dec', 'Nov', ...]
    year_tokens  = year_line[1:]       # ['2023', '2022', ...]

    dates: list[pd.Timestamp] = []
    for m, y in zip(month_tokens, year_tokens):
        try:
            dates.append(pd.to_datetime(f"{m} {y}", format="%b %Y"))
        except ValueError:
            dates.append(pd.NaT)

    records: list[dict] = []
    for line in lines[header_start + 2:]:
        raw = line.split("  ")  # two-space delimiter
        parts = [p.strip() for p in raw if p.strip()]
        if not parts:
            continue
        country = parts[0].strip('"')
        if not country or country.lower() in _SKIP_COUNTRIES:
            continue
        if country.startswith(("---", "1/", "2/", "*")):
            continue
        for dt, val in zip(dates, parts[1:]):
            if pd.isna(dt) or not val:
                continue
            try:
                holdings = float(val.replace(",", ""))
            except ValueError:
                continue
            records.append({"date": dt, "country": country, "holdings_bln_usd": holdings})

    return pd.DataFrame(records)


def pull(conn, config: dict, watermark=None) -> pd.DataFrame:
    start: str = config.get("start", "2000-01-01")

    # Fetch historical archive (2000–present)
    print("  Fetching TIC historical archive (mfhhis01.txt)...")
    hist_text = _fetch(_MFH_HISTORICAL_URL)
    df_hist = _parse_multiyear(hist_text)

    # Fetch the current rolling file to pick up months not yet in the archive
    print("  Fetching TIC current window (mfh.txt)...")
    curr_text = _fetch(_MFH_CURRENT_URL)
    df_curr = _parse_current(curr_text)

    df = pd.concat([df_hist, df_curr], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])

    # Deduplicate — prefer historical file (it's more stable), but current fills recent gaps
    df = df.sort_values(["date", "country"]).drop_duplicates(subset=["date", "country"], keep="last")

    if watermark is not None:
        df = df[df["date"] > pd.to_datetime(str(watermark))]
    else:
        df = df[df["date"] >= pd.to_datetime(start)]

    df = df.sort_values(["date", "country"]).reset_index(drop=True)
    print(f"  {len(df):,} rows, {df['country'].nunique()} countries, "
          f"{df['date'].min().date()} – {df['date'].max().date()}")
    return df
