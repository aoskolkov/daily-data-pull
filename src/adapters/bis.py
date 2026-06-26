"""
Adapter for BIS (Bank for International Settlements) statistical data.

Uses the BIS Statistics REST API (SDMX-JSON / CSV format).
Documentation: https://stats.bis.org/api/v1/

Available dataflows (most useful for macro/finance research)
-------------------------------------------------------------
  WS_DEBT_SEC2   International debt securities outstanding (quarterly)
                 Dimensions: FREQ · MEASURE · ISSUE_TYPE · SECTOR ·
                             ORG_COUNTRY · CURR_TYPE_BOOK · CURR_TYPE_ISSUE ·
                             MATURITY · RATE · SECTOR_COUNT · OBS_TYPE
  WS_LBS_D_PUB   BIS locational banking statistics (quarterly)
  WS_CBS_PUB     BIS consolidated banking statistics (quarterly)
  WS_EER         Effective exchange rates (monthly)
  WS_TC          Total credit to private non-financial sector (quarterly)
  WS_CREDIT_GAP  Credit-to-GDP gap (quarterly)
  WS_CBPOL_D     Central bank policy rates (daily)

Config keys (datasets.yaml)
----------------------------
  source:    bis
  dataflow:  WS_DEBT_SEC2   # BIS dataset identifier
  key:       Q.N.A.A.M.B.USD.O.G.S.A.A
             # dot-separated dimension values; use 'A' (=all) for a dimension
             # to avoid filtering. Order must match the dataflow's dimension list.
  start:     "1993-01-01"
  incremental_key: date

Key presets for common use cases
---------------------------------
  # International debt securities, all sectors, USD amounts, all countries
  key: Q.N.A.A.M.B.USD.O.G.S.A.A

  # Government sector only
  # Set SECTOR dimension (position 4) to a government code.
  # Use discover mode to list codes: python wrdsdl.py discover bis --dataflow WS_DEBT_SEC2

Output columns
--------------
  date, <dimension_cols...>, obs_value
  (dimension columns depend on the dataflow and key)

Discover mode
-------------
  python wrdsdl.py discover bis --dataflow WS_DEBT_SEC2
  Returns dimension names and code lists for any BIS dataflow.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd

_BIS_API = "https://stats.bis.org/api/v1"


def _get(url: str, params: dict | None = None) -> dict:
    import requests
    resp = requests.get(url, params=params, timeout=120,
                        headers={"Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


def _get_csv(url: str, params: dict | None = None) -> str:
    import requests
    resp = requests.get(url, params=params, timeout=120,
                        headers={"Accept": "text/csv"})
    resp.raise_for_status()
    return resp.text


def discover(dataflow: str) -> dict[str, dict[str, str]]:
    """
    Return dimension names and code lists for a BIS dataflow.
    Used by: python wrdsdl.py discover bis --dataflow <DATAFLOW>
    """
    # Fetch dataflow structure
    url = f"{_BIS_API}/datastructure/BIS/{dataflow}"
    data = _get(url)

    result: dict[str, dict[str, str]] = {}

    try:
        structure = data["data"]["dataStructures"][0]
        dimensions = structure["dataStructure"]["dataStructureComponents"]["dimensionList"]["dimensions"]
        for dim in dimensions:
            dim_id = dim["id"]
            codes: dict[str, str] = {}
            # Code list may be inline or referenced
            codelist = dim.get("localRepresentation", {}).get("enumeration", {})
            if codelist:
                for item in codelist.get("items", []):
                    codes[item["id"]] = item.get("name", {}).get("en", item["id"])
            result[dim_id] = codes
    except (KeyError, IndexError, TypeError):
        # Try v2 format
        try:
            structure = data["data"]["dataStructures"][0]
            dims = structure["dataStructureComponents"]["dimensionList"]["dimensions"]
            for dim in dims:
                result[dim["id"]] = {}
        except Exception:
            pass

    return result


def pull(conn, config: dict, watermark=None) -> pd.DataFrame:
    dataflow: str = config["dataflow"]
    key: str = config.get("key", "all")
    start: str = config.get("start", "1993-01-01")

    # BIS API uses period notation: startPeriod=1993-Q1 or 1993-01
    period_fmt: str = config.get("period_format", "quarterly")

    if watermark is not None:
        start_period = _date_to_period(str(watermark), period_fmt)
    else:
        start_period = _date_to_period(start, period_fmt)

    end_period = _date_to_period(str(date.today()), period_fmt)

    url = f"{_BIS_API}/data/{dataflow}/{key}"
    params = {
        "format":      "csv",
        "startPeriod": start_period,
        "endPeriod":   end_period,
    }

    print(f"  Fetching BIS {dataflow} ({key}) from {start_period}...")
    csv_text = _get_csv(url, params)

    df = pd.read_csv(io.StringIO(csv_text), low_memory=False)
    if df.empty:
        return df

    df.columns = df.columns.str.strip().str.lower().str.replace("-", "_")

    # Normalise period / date column
    period_col = next((c for c in df.columns if c in ("time_period", "period", "date")), None)
    if period_col:
        df["date"] = df[period_col].apply(_period_to_date)
        df = df.drop(columns=[period_col])
    else:
        raise ValueError(f"No period/date column found in BIS response. Columns: {list(df.columns)}")

    # Rename value column
    val_col = next((c for c in df.columns if c in ("obs_value", "value", "obs")), None)
    if val_col and val_col != "obs_value":
        df = df.rename(columns={val_col: "obs_value"})

    df["obs_value"] = pd.to_numeric(df.get("obs_value"), errors="coerce")
    df = df.dropna(subset=["date", "obs_value"])
    df = df.sort_values("date").reset_index(drop=True)

    print(f"  {len(df):,} rows, {df['date'].min().date()} – {df['date'].max().date()}")
    return df


def _date_to_period(d: str, fmt: str = "quarterly") -> str:
    """Convert ISO date string to BIS period notation.

    fmt: 'quarterly' → YYYY-Q#  (default, for WS_DEBT_SEC2_PUB etc.)
         'monthly'   → YYYY-MM   (for WS_CBPOL monthly)
         'daily'     → YYYY-MM-DD (for WS_CBPOL daily)
    """
    dt = pd.to_datetime(d)
    if fmt == "daily":
        return dt.strftime("%Y-%m-%d")
    if fmt == "monthly":
        return dt.strftime("%Y-%m")
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def _period_to_date(p: str) -> pd.Timestamp | None:
    """Convert BIS period string (2023-Q3, 2023-03, 2023) to a Timestamp."""
    p = str(p).strip()
    try:
        if "-Q" in p:
            year, q = p.split("-Q")
            month = (int(q) - 1) * 3 + 1
            return pd.Timestamp(int(year), month, 1)
        if len(p) == 4:
            return pd.Timestamp(int(p), 1, 1)
        return pd.to_datetime(p)
    except Exception:
        return None
