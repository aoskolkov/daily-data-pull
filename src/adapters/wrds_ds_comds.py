"""
Adapter for WRDS Datastream commodity spot prices and indices.
Source tables: tr_ds_comds.wrds_cmdy_info + tr_ds_comds.wrds_cmdy_data

Schema
------
wrds_cmdy_info : metadata
  comcode, dsmnemonic, name, comdesc, unitdesc, isocur, seriestype (S=spot, I=index)

wrds_cmdy_data : daily prices
  comcode, date_, close_, dsp

Config keys (datasets.yaml)
----------------------------
  source: wrds_ds_comds
  mnemonics: [OILBREN, LCPCASH, ...]   # dsmnemonic values; empty = pull all
  start:     "1980-01-01"
  incremental_key: date_

Output columns
--------------
  date_, dsmnemonic, name, comdesc, unitdesc, isocur, close_, dsp
"""

from __future__ import annotations

import pandas as pd
import wrds
from sqlalchemy import text as sa_text


def _raw_sql(conn: wrds.Connection, sql: str) -> pd.DataFrame:
    with conn.engine.connect() as c:
        return pd.read_sql(sa_text(sql), c)


def pull(conn: wrds.Connection, config: dict, watermark=None) -> pd.DataFrame:
    mnemonics: list[str] = config.get("mnemonics", [])
    start: str = config.get("start", "1980-01-01")

    wm_clause = (
        f"AND d.date_ > '{watermark}'"
        if watermark is not None
        else f"AND d.date_ >= '{start}'"
    )

    mnem_filter = ""
    if mnemonics:
        mnem_list = ", ".join(f"'{m.upper()}'" for m in mnemonics)
        mnem_filter = f"AND i.dsmnemonic IN ({mnem_list})"

    sql = f"""
        SELECT
            d.date_,
            i.dsmnemonic,
            i.name,
            i.comdesc,
            i.unitdesc,
            i.isocur,
            d.close_,
            d.dsp
        FROM tr_ds_comds.wrds_cmdy_info i
        JOIN tr_ds_comds.wrds_cmdy_data d ON i.comcode = d.comcode
        WHERE (d.close_ IS NOT NULL OR d.dsp IS NOT NULL)
          {mnem_filter}
          {wm_clause}
        ORDER BY d.date_, i.dsmnemonic
    """

    return _raw_sql(conn, sql)
