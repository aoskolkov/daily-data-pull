"""
Adapter for WRDS Datastream equity indices.
Source tables: tr_ds_equities.ds2equityindex + tr_ds_equities.ds2indexdata

Schema
------
ds2equityindex : metadata (141,240 indices)
  dsindexcode, dsindexmnem, region, indexdesc, isocurrcode, indexstatuscode

ds2indexdata : daily prices (421M rows)
  dsindexcode, valuedate, pi_ (price index), ri (return index), mv (market cap)

Config keys (datasets.yaml)
----------------------------
  source: wrds_ds_index
  mnemonics: [TOTMKUS, TOTMKGB, ...]  # dsindexmnem values; empty = pull all (no status filter)
  fields:    [pi_, ri, mv]            # value columns to pull (default: pi_ and ri)
  start:     "1980-01-01"
  incremental_key: valuedate

Output columns
--------------
  valuedate, dsindexmnem, indexdesc, region, isocurrcode, pi_, ri[, mv]
"""

from __future__ import annotations

import pandas as pd
import wrds
from sqlalchemy import text as sa_text

_DEFAULT_FIELDS = ["pi_", "ri"]


def _raw_sql(conn: wrds.Connection, sql: str) -> pd.DataFrame:
    with conn.engine.connect() as c:
        return pd.read_sql(sa_text(sql), c)


def pull(conn: wrds.Connection, config: dict, watermark=None) -> pd.DataFrame:
    mnemonics: list[str] = config.get("mnemonics", [])
    fields: list[str] = config.get("fields", _DEFAULT_FIELDS)
    start: str = config.get("start", "1980-01-01")

    wm_clause = (
        f"AND d.valuedate > '{watermark}'"
        if watermark is not None
        else f"AND d.valuedate >= '{start}'"
    )

    mnem_filter = ""
    if mnemonics:
        mnem_list = ", ".join(f"'{m.upper()}'" for m in mnemonics)
        mnem_filter = f"AND i.dsindexmnem IN ({mnem_list})"

    field_cols = ", ".join(f"d.{f}" for f in fields)

    sql = f"""
        SELECT
            d.valuedate,
            i.dsindexmnem,
            i.indexdesc,
            i.region,
            i.isocurrcode,
            {field_cols}
        FROM tr_ds_equities.ds2equityindex i
        JOIN tr_ds_equities.ds2indexdata d ON i.dsindexcode = d.dsindexcode
        WHERE d.pi_ IS NOT NULL
          {mnem_filter}
          {wm_clause}
        ORDER BY d.valuedate, i.dsindexmnem
    """

    return _raw_sql(conn, sql)
