"""
Adapter for BIS (Bank for International Settlements) statistical data.

Uses the BIS Statistics REST API (SDMX 2.1): https://stats.bis.org/api/v1/

Dataflows used in config/datasets.yaml (dimension order = key order)
--------------------------------------------------------------------
  WS_DEBT_SEC2_PUB  International debt securities (quarterly). 15 dimensions:
                    FREQ.ISSUER_RES.ISSUER_NAT.ISSUER_BUS_IMM.ISSUER_BUS_ULT.MARKET.
                    ISSUE_TYPE.ISSUE_CUR_GROUP.ISSUE_CUR.ISSUE_OR_MAT.ISSUE_RE_MAT.
                    ISSUE_RATE.ISSUE_RISK.ISSUE_COL.MEASURE
  WS_LBS_D_PUB      Locational banking statistics (quarterly)
  WS_EER            Effective exchange rates (monthly; FREQ.EER_TYPE.EER_BASKET.REF_AREA)
  WS_CBPOL          Central bank policy rates (key "D." = daily, all countries)
  Others: WS_CBS_PUB (consolidated banking), WS_TC (total credit), WS_CREDIT_GAP.
  The older ID WS_DEBT_SEC2 no longer exists.

Config keys (datasets.yaml)
----------------------------
  source:    bis
  dataflow:  WS_DEBT_SEC2_PUB
  key:       Q.....C.A..TO1.A.A.A.A.A.I
             # dot-separated, one position per dimension in dataflow order.
             # A blank position is the wildcard; "A" is a literal code (often
             # "all"/"total" in BIS codelists), so it filters to that code.
  start:     "1993-01-01"
  period_format: quarterly   # or monthly / daily — must match FREQ for startPeriod
  incremental_key: date

Output columns
--------------
  date, <dimension columns...>, obs_value, plus the CSV's attribute columns
  (e.g. unit_measure, unit_mult, decimals, obs_status, obs_conf, title/title_ts)

Discover mode
-------------
  python wrdsdl.py discover bis --dataset WS_DEBT_SEC2_PUB
  Lists every dimension (in key order) with its codes and labels.
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
    {dimension: {code: label}} for a BIS dataflow, dimensions in key order.
    Used by: python wrdsdl.py discover bis --dataset <DATAFLOW>

    The data structure ID differs from the dataflow ID (WS_DEBT_SEC2_PUB uses
    BIS_DEBT_SEC2), so fetch the dataflow with all its references instead.
    """
    import requests
    import xml.etree.ElementTree as ET

    resp = requests.get(f"{_BIS_API}/dataflow/BIS/{dataflow}/latest",
                        params={"references": "all", "detail": "full"}, timeout=120)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    s = "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure}"
    c = "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common}"

    codelists = {
        cl.get("id"): {code.get("id"): code.findtext(f"{c}Name", "") for code in cl.findall(f"{s}Code")}
        for cl in root.iter(f"{s}Codelist")
    }
    dims = sorted(root.iter(f"{s}Dimension"), key=lambda d: int(d.get("position", 0)))
    result: dict[str, dict[str, str]] = {}
    for dim in dims:
        ref = dim.find(f"{s}LocalRepresentation/{s}Enumeration/Ref")
        result[dim.get("id")] = codelists.get(ref.get("id"), {}) if ref is not None else {}
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
         'monthly'   → YYYY-MM   (for WS_EER monthly)
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
