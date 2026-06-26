"""
Adapter for WRDS Datastream economic series (tr_ds_econ library).

Source tables:
  tr_ds_econ.wrds_ecoinfo  — series metadata: ecoseriesid, dsmnemonic, desc_english,
                              freqcode, mktcode, mktdesc, currcode, unitcodedesc
  tr_ds_econ.ecodata       — observations: ecoseriesid, perioddate, series_value

Note: ecodata uses ecoseriesid (not dsmnemonic) as its key, so we always join
      through wrds_ecoinfo. The column names differ from CLAUDE.md docs which
      referred to the raw ecoinfo/ecodata tables (not the wrds_* views).

Config keys (datasets.yaml)
----------------------------
  source:          wrds_ds_econ
  mnemonics:       [USTRCN10, BDGBOND., JPGBOND., ...]
  start:           "1950-01-01"
  incremental_key: date_

Output columns
--------------
  date_, dsmnemonic, close_  (percentage or level, as per unitcodedesc)

The wrds_ds_comds adapter uses the same output schema (date_, dsmnemonic, close_)
so the same clean scripts can handle both.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text as sa_text


def _raw_sql(conn, sql: str) -> pd.DataFrame:
    with conn.engine.connect() as c:
        return pd.read_sql(sa_text(sql), c)


def pull(conn, config: dict, watermark=None) -> pd.DataFrame:
    mnemonics: list[str] = config["mnemonics"]
    start: str = config.get("start", "1950-01-01")

    if not mnemonics:
        raise ValueError("wrds_ds_econ: 'mnemonics' list must not be empty")

    mnem_csv = ", ".join(f"'{m}'" for m in mnemonics)
    wm_clause = (
        f"AND e.perioddate > '{watermark}'" if watermark
        else f"AND e.perioddate >= '{start}'"
    )

    sql = f"""
        SELECT
            i.dsmnemonic,
            e.perioddate  AS date_,
            e.series_value AS close_
        FROM tr_ds_econ.wrds_ecoinfo i
        JOIN tr_ds_econ.ecodata e ON i.ecoseriesid = e.ecoseriesid
        WHERE i.dsmnemonic IN ({mnem_csv})
          {wm_clause}
        ORDER BY i.dsmnemonic, e.perioddate
    """

    print(f"  Querying tr_ds_econ ({len(mnemonics)} mnemonics) from {watermark or start}...")
    df = _raw_sql(conn, sql)

    if df.empty:
        print("  WARNING: no rows returned")
        return df

    df["date_"] = pd.to_datetime(df["date_"])
    df = df.dropna(subset=["date_", "close_"])

    print(f"  {len(df):,} rows | {df['dsmnemonic'].nunique()} series | "
          f"{df['date_'].min().date()} – {df['date_'].max().date()}")
    return df
