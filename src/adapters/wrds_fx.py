"""
Adapter for WRDS Datastream FX rates (tr_ds_equities.ds2fxcode + ds2fxrate).

Pulls spot and/or forward exchange rates for a configurable set of currency
pairs and tenors.  Data source: LSEG Datastream via WRDS.

Schema
------
ds2fxcode : rate catalog (1578 codes)
  exrateintcode, exratecode, fromcurrcode, tocurrcode, sourcecode,
  ratetypecode, exratedesc

ds2fxrate : daily observations
  exrateintcode, exratedate, midrate, bidrate, offerrate, licflag

ratetypecodes (selection)
  SPOT  = spot rate
  ONFD  = overnight forward
  TNFD  = tomorrow-next forward
  SNFD  = spot-next forward
  1WFD  = 1-week forward
  1MFD  = 1-month forward
  3MFD  = 3-month forward
  6MFD  = 6-month forward
  9MFD  = 9-month forward
  1YFD  = 1-year (12-month) forward
  2YFD  = 2-year forward
  (full set runs to 20YF)

Config keys (datasets.yaml)
-----------------------------
  source: wrds_fx
  currencies:   [EUR, GBP, JPY, CHF, CAD, AUD, NZD]  # non-USD currencies
  tenors:       [SPOT, 1MFD, 3MFD, 6MFD, 1YFD]        # ratetypecodes to pull
  start:        "1990-01-01"
  incremental_key: exratedate

Output columns
--------------
  exratedate, fromcurrcode, tocurrcode, ratetypecode, midrate, bidrate, offerrate
"""

from __future__ import annotations

import pandas as pd
import wrds
from sqlalchemy import text as sa_text


def _raw_sql(conn: wrds.Connection, sql: str) -> pd.DataFrame:
    """Execute SQL via SQLAlchemy text(), bypassing wrds.raw_sql pandas 2.x compat issue."""
    with conn.engine.connect() as c:
        return pd.read_sql(sa_text(sql), c)


def pull(conn: wrds.Connection, config: dict, watermark=None) -> pd.DataFrame:
    """
    Pull FX spot and/or forward rates from WRDS Datastream.

    Config keys:
      currencies:  [EUR, GBP, JPY, ...]   # non-USD ISO codes (matched vs USD in either direction)
      tenors:      [SPOT, 1MFD, 3MFD, ...] # ratetypecodes (default: SPOT, 1MFD, 3MFD, 6MFD, 1YFD)
      start:       "1990-01-01"
      rate_field:  midrate                 # column to pull (default: midrate)

    Returns long DataFrame: exratedate, fromcurrcode, tocurrcode, ratetypecode,
                             midrate, bidrate, offerrate
    """
    currencies: list[str] = config.get("currencies", [])
    tenors: list[str] = config.get("tenors", [])
    start: str = config.get("start", "1990-01-01")

    wm_clause = (
        f"AND r.exratedate > '{watermark}'"
        if watermark is not None
        else f"AND r.exratedate >= '{start}'"
    )

    # Build optional WHERE clauses — omit filter entirely when list is empty (= pull all)
    tenor_filter = ""
    if tenors:
        tenor_list = ", ".join(f"'{t.upper()}'" for t in tenors)
        tenor_filter = f"AND c.ratetypecode IN ({tenor_list})"

    curr_filter = ""
    if currencies:
        curr_list = ", ".join(f"'{c.upper()}'" for c in currencies)
        curr_filter = f"""
          AND (
              (c.fromcurrcode IN ({curr_list}) AND c.tocurrcode = 'USD')
              OR (c.fromcurrcode = 'USD' AND c.tocurrcode IN ({curr_list}))
          )"""

    sql = f"""
        SELECT
            c.fromcurrcode,
            c.tocurrcode,
            c.ratetypecode,
            c.exratedesc,
            r.exratedate,
            r.midrate,
            r.bidrate,
            r.offerrate
        FROM tr_ds_equities.ds2fxcode c
        JOIN tr_ds_equities.ds2fxrate r ON c.exrateintcode = r.exrateintcode
        WHERE r.midrate IS NOT NULL
          {tenor_filter}
          {curr_filter}
          {wm_clause}
        ORDER BY r.exratedate, c.fromcurrcode, c.tocurrcode, c.ratetypecode
    """

    return _raw_sql(conn, sql)
