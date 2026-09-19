"""
Adapter for US Treasury TIC (Treasury International Capital) data.

Fetches the "Major Foreign Holders of Treasury Securities" monthly table
directly from the US Treasury website.

Two source files are used:
  mfhhis01.txt    — historical archive, 2000 to the last full calendar year,
                    one tab-delimited block per year
                    URL: https://treasury.gov/resource-center/data-chart-center/tic/Documents/mfhhis01.txt
  slt_table5.txt  — SLT Table 5, rolling 13-month window (most recent data)
                    URL: https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/slt_table5.txt

The adapter fetches both and merges on (date, country); where they overlap the
SLT table wins, since it carries the latest revisions.

The old rolling file mfh.txt (same directory) was frozen at Jan 2023 when
Treasury moved the table onto Form SLT data; it is no longer used.

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
import re
from datetime import date

import pandas as pd

_MFH_HISTORICAL_URL = (
    "https://treasury.gov/resource-center/data-chart-center/tic/Documents/mfhhis01.txt"
)
_SLT_TABLE5_URL = (
    "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/slt_table5.txt"
)

_MONTHS = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"}

_SKIP_COUNTRIES = {
    "grand total", "of which:", "for. official",
    "treasury bills", "t-bonds & notes", "all other",
    "memo:", "total foreign",
}


def _clean_country(raw: str) -> str:
    """Strip quotes, whitespace and trailing footnote markers ('Belgium  5/' -> 'Belgium')."""
    return re.sub(r"\s+\d+/$", "", raw.strip().strip('"')).strip()


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
        country = _clean_country(parts[0])
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


def _parse_slt(text: str) -> pd.DataFrame:
    """Parse slt_table5.txt: tab-delimited, header 'Country<TAB>2026-07<TAB>2026-06...'."""
    lines = text.splitlines()
    header = next((i for i, l in enumerate(lines) if l.split("\t")[0].strip() == "Country"), None)
    if header is None:
        raise ValueError("slt_table5.txt: 'Country' header row not found; format changed?")
    dates = [pd.to_datetime(t.strip(), format="%Y-%m", errors="coerce")
             for t in lines[header].split("\t")[1:]]

    records: list[dict] = []
    for line in lines[header + 1:]:
        parts = line.split("\t")
        country = _clean_country(parts[0])
        if not country:
            break  # blank row separates the data from the notes
        if country.lower() in _SKIP_COUNTRIES or country.lower().startswith("of which"):
            continue
        for dt, val in zip(dates, parts[1:]):
            if pd.isna(dt) or not val.strip():
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

    # Fetch the rolling SLT table for months not yet in the archive
    print("  Fetching TIC current window (slt_table5.txt)...")
    df_curr = _parse_slt(_fetch(_SLT_TABLE5_URL))

    df = pd.concat([df_hist, df_curr], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])

    # SLT rows come last, so keep="last" lets its revisions win over the archive
    df = df.drop_duplicates(subset=["date", "country"], keep="last")

    if watermark is not None:
        df = df[df["date"] > pd.to_datetime(str(watermark))]
    else:
        df = df[df["date"] >= pd.to_datetime(start)]

    df = df.sort_values(["date", "country"]).reset_index(drop=True)
    print(f"  {len(df):,} rows, {df['country'].nunique()} countries, "
          f"{df['date'].min().date()} – {df['date'].max().date()}")
    return df
