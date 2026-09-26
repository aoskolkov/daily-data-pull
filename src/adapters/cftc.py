"""
Adapter for CFTC Commitments of Traders (COT) reports.

Positions in exchange-traded futures broken out by trader category, published
weekly by the CFTC. Positions are as of Tuesday; the report is released the
following Friday at 3:30pm ET.

Source: the CFTC Socrata open-data API at publicreporting.cftc.gov. No API key
is required (an app token only raises the anonymous rate limit).

Three report families are supported via the `report` config key:

  tff       Traders in Financial Futures — the report to use for FX, rates and
            equity index futures. Sectors: Dealer/Intermediary, Asset Manager/
            Institutional, Leveraged Funds, Other Reportables, Non-Reportable.
            Weekly from 2006-06-13.

  legacy    The original COT breakdown: Commercial, Non-Commercial and
            Non-Reportable. Much coarser, but history runs back to 1986-01-15 —
            20 extra years for the major FX contracts.

  disagg    Disaggregated report: Producer/Merchant, Swap Dealer, Managed Money,
            Other Reportables. PHYSICAL COMMODITIES ONLY — contains no FX or
            other financial contracts. Weekly from 2006-06-13.

Note that "long"/"short" exclude spreading positions, which are reported
separately. Net positioning for a sector is therefore long - short. Summed
over all categories, longs + spreads = open interest (and likewise shorts +
spreads; exact in every TFF row, ~96% of legacy rows); sector nets sum to zero.

Filter by contract CODE, not name
---------------------------------
`cftc_contract_market_code` is the stable identifier and is unique per
exchange-contract. Both alternatives drift, silently truncating history:

  * Exchange names changed. CME FX futures were reported under INTERNATIONAL
    MONETARY MARKET until 2000-08-22 and CHICAGO MERCANTILE EXCHANGE from
    2000-08-29. Filtering on "CHICAGO MERCANTILE EXCHANGE" drops everything
    before 2000 — 14.5 years for the majors.

  * Contract names change AND are rewritten retroactively. The NZD contract
    (112741) is now called NZ DOLLAR across its whole history in
    contract_market_name, while market_and_exchange_names still shows
    "NEW ZEALAND DOLLAR - ..." on rows before 2022-02-08. Matching on
    "NEW ZEALAND DOLLAR" finds nothing in one field and only pre-2022 rows
    in the other.

Codes span both renames cleanly, so `contract_codes` is the filter to use.
`exchange` and `contracts` remain available for exploration only.

Config keys (datasets.yaml)
----------------------------
  source: cftc
  report: tff                  # tff | legacy | disagg  (default: tff)
  start: "2006-06-13"
  incremental_key: date
  contract_codes:              # preferred filter; omit to pull every contract
    - "099741"                 # quote them — leading zeros matter
    - "097741"
  exchange: CHICAGO MERCANTILE EXCHANGE   # optional, exploratory only
  contracts: [EURO FX]                    # optional, exploratory only
  dataset_id: abcd-1234        # optional override (e.g. futures+options variant)

Output columns
--------------
  date, contract, market, contract_code, open_interest, then one column per
  sector/side. Column names differ by report (see _COLUMN_MAPS below).
"""

from __future__ import annotations

import time

import pandas as pd
import requests

_API_ROOT = "https://publicreporting.cftc.gov/resource"

# Socrata dataset IDs — futures-only variants.
_DATASET_IDS = {
    "tff":    "gpe5-46if",
    "legacy": "6dca-aqww",
    "disagg": "72hh-3qpy",
}

_DATE_FIELD = "report_date_as_yyyy_mm_dd"

# Shared identifier columns, present in every report family.
_ID_MAP = {
    _DATE_FIELD:                 "date",
    "contract_market_name":      "contract",
    "market_and_exchange_names": "market",
    "cftc_contract_market_code": "contract_code",
    "open_interest_all":         "open_interest",
}

# Per-report position columns. Only keys actually returned by the API are kept,
# so a schema change upstream degrades to missing columns rather than a crash.
_COLUMN_MAPS = {
    "tff": {
        "dealer_positions_long_all":    "dealer_long",
        "dealer_positions_short_all":   "dealer_short",
        "dealer_positions_spread_all":  "dealer_spread",
        "asset_mgr_positions_long":     "asset_mgr_long",
        "asset_mgr_positions_short":    "asset_mgr_short",
        "asset_mgr_positions_spread":   "asset_mgr_spread",
        "lev_money_positions_long":     "lev_money_long",
        "lev_money_positions_short":    "lev_money_short",
        "lev_money_positions_spread":   "lev_money_spread",
        "other_rept_positions_long":    "other_rept_long",
        "other_rept_positions_short":   "other_rept_short",
        "other_rept_positions_spread":  "other_rept_spread",
        "nonrept_positions_long_all":   "nonrept_long",
        "nonrept_positions_short_all":  "nonrept_short",
    },
    "legacy": {
        "noncomm_positions_long_all":   "noncomm_long",
        "noncomm_positions_short_all":  "noncomm_short",
        "noncomm_positions_spread":     "noncomm_spread",
        "comm_positions_long_all":      "comm_long",
        "comm_positions_short_all":     "comm_short",
        "nonrept_positions_long_all":   "nonrept_long",
        "nonrept_positions_short_all":  "nonrept_short",
        "tot_rept_positions_long_all":  "tot_rept_long",
        "tot_rept_positions_short":     "tot_rept_short",
    },
    "disagg": {
        "prod_merc_positions_long":     "prod_merc_long",
        "prod_merc_positions_short":    "prod_merc_short",
        "swap_positions_long_all":      "swap_long",
        "swap_positions_short_all":     "swap_short",
        "swap_positions_spread_all":    "swap_spread",
        "m_money_positions_long_all":   "m_money_long",
        "m_money_positions_short_all":  "m_money_short",
        "m_money_positions_spread":     "m_money_spread",
        "other_rept_positions_long":    "other_rept_long",
        "other_rept_positions_short":   "other_rept_short",
        "other_rept_positions_spread":  "other_rept_spread",
        "nonrept_positions_long_all":   "nonrept_long",
        "nonrept_positions_short_all":  "nonrept_short",
    },
}

_PAGE_SIZE = 50_000
_MAX_RETRIES = 4


def _escape(value: str) -> str:
    """Escape a string literal for a SoQL WHERE clause."""
    return value.replace("'", "''")


def _build_where(config: dict, watermark) -> str:
    start: str = str(config.get("start", "2006-06-13"))
    clauses: list[str] = []

    if watermark is not None:
        clauses.append(f"{_DATE_FIELD} > '{_escape(str(watermark))}'")
    else:
        clauses.append(f"{_DATE_FIELD} >= '{_escape(start)}'")

    # Preferred filter: contract codes are stable identifiers. Contract NAMES and
    # exchange names both drift (see module docstring), so they are only offered
    # as a fallback for exploratory pulls.
    codes: list[str] = [str(c) for c in (config.get("contract_codes") or [])]
    if codes:
        joined = ", ".join(f"'{_escape(c)}'" for c in codes)
        clauses.append(f"cftc_contract_market_code in ({joined})")

    exchange = config.get("exchange")
    if exchange:
        clauses.append(f"upper(market_and_exchange_names) like upper('%{_escape(exchange)}%')")

    contracts: list[str] = config.get("contracts") or []
    if contracts:
        joined = ", ".join(f"'{_escape(c)}'" for c in contracts)
        clauses.append(f"contract_market_name in ({joined})")

    return " AND ".join(clauses)


def _get(url: str, params: dict) -> list[dict]:
    """GET with retries; Socrata occasionally 500s or times out under load."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                params=params,
                timeout=120,
                headers={"User-Agent": "daily-data-pull/1.0"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 — retry on any transport/HTTP error
            last_exc = exc
            if attempt < _MAX_RETRIES:
                print(f"  Request failed ({exc}). Retry {attempt}/{_MAX_RETRIES - 1}...")
                time.sleep(2 * attempt)
    raise RuntimeError(f"CFTC request failed after {_MAX_RETRIES} attempts: {last_exc}")


def pull(config: dict, watermark=None) -> pd.DataFrame:
    report: str = str(config.get("report", "tff")).lower()
    if report not in _COLUMN_MAPS:
        raise ValueError(
            f"Unknown CFTC report '{report}'. Expected one of: {sorted(_COLUMN_MAPS)}"
        )

    dataset_id: str = config.get("dataset_id") or _DATASET_IDS[report]
    url = f"{_API_ROOT}/{dataset_id}.json"
    where = _build_where(config, watermark)

    print(f"  Fetching CFTC {report.upper()} ({dataset_id})...")
    print(f"    where: {where}")

    # Paginate. $order is required for stable paging across requests.
    rows: list[dict] = []
    offset = 0
    while True:
        page = _get(url, {
            "$where":  where,
            "$order":  f"{_DATE_FIELD},cftc_contract_market_code",
            "$limit":  _PAGE_SIZE,
            "$offset": offset,
        })
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
        print(f"    {len(rows):,} rows so far...")

    if not rows:
        print("  No rows returned.")
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Keep only the identifier + position columns this report defines, renaming
    # to short names. Missing upstream columns are simply absent from the output.
    rename = {**_ID_MAP, **_COLUMN_MAPS[report]}
    keep = [c for c in rename if c in df.columns]
    df = df[keep].rename(columns=rename)

    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    # Socrata returns every numeric as a string.
    for col in df.columns:
        if col not in ("date", "contract", "market", "contract_code"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.sort_values(["date", "contract"])
          .drop_duplicates(subset=["date", "contract_code"], keep="last")
          .reset_index(drop=True)
    )

    print(f"  {len(df):,} rows, {df['contract'].nunique()} contracts, "
          f"{df['date'].min().date()} – {df['date'].max().date()}")
    return df
