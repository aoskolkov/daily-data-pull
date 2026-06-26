"""
Adapter for WRDS Datastream futures term structures (tr_ds_fut library).

Builds a nearby-ranked term structure from individual contracts:
  - Nearby 1 = front month (soonest to expire contract that has not yet expired)
  - Nearby 2 = next-to-expire, etc.
  - Up to max_nearby contracts per day

Uses tr_ds_fut.wrds_contract_info (contract metadata) +
     tr_ds_fut.wrds_fut_contract (daily settlement prices).

Supports contract mnemonic prefix filtering (e.g. 'NWS' for NYMEX WTI).
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
    Build a futures term structure from individual dated contracts.

    Config keys:
      dsmnem_prefix: NWS        # contract mnemonic prefix (required)
      currency:      USD        # ISO currency filter (default USD)
      max_nearby:    12         # how many tenors to keep per day (default 12)
      start:         "1990-01-01"
      price_col:     settlement # column to use as price (default: settlement)

    Returns a long DataFrame with columns:
      date_, nearby (1..max_nearby), price, contrdate (MMYY), lasttrddate

    The clean script converts nearby integer to tenor label (M1, M2, ...) and
    pivots to wide.
    """
    prefix   = config.get("dsmnem_prefix", "")
    currency = config.get("currency", "USD")
    max_n    = int(config.get("max_nearby", 12))
    start    = config.get("start", "1990-01-01")
    pcol     = config.get("price_col", "settlement")

    if not prefix:
        raise ValueError("wrds_fut config requires 'dsmnem_prefix'")

    wm_clause = (
        f"AND fc.date_ > '{watermark}'"
        if watermark is not None
        else f"AND fc.date_ >= '{start}'"
    )

    sql = f"""
        WITH contracts AS (
            SELECT futcode, contrdate, lasttrddate
            FROM tr_ds_fut.wrds_contract_info
            WHERE UPPER(dsmnem) LIKE UPPER('{prefix}%%')
              AND isocurrcode = '{currency}'
        ),
        raw AS (
            SELECT
                fc.date_,
                c.contrdate,
                c.lasttrddate,
                fc.{pcol} AS price
            FROM tr_ds_fut.wrds_fut_contract fc
            JOIN contracts c ON fc.futcode = c.futcode
            WHERE fc.{pcol} IS NOT NULL
              {wm_clause}
        ),
        ranked AS (
            SELECT
                date_,
                contrdate,
                lasttrddate,
                price,
                ROW_NUMBER() OVER (
                    PARTITION BY date_
                    ORDER BY lasttrddate
                ) AS nearby
            FROM raw
            WHERE lasttrddate >= date_   -- contract not yet expired
        )
        SELECT date_, nearby, price, contrdate, lasttrddate
        FROM ranked
        WHERE nearby <= {max_n}
        ORDER BY date_, nearby
    """

    print(f"  Fetching {prefix}* term structure (nearby 1-{max_n}) from {start} ...")
    df = _raw_sql(conn, sql)
    print(f"  {len(df):,} rows fetched.")
    return df
