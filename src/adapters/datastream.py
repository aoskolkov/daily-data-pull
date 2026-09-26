"""
Adapter for Datastream series via WRDS tr_ds_* libraries.

Caveats baked in:
- WRDS carries only select Datastream modules (equities, economics, commodities, futures).
- Daily series arrive with a lag of a few days (2-3 days in 2026 pulls) — not for
  live/intraday use.
- Mnemonic coverage differs from the Datastream terminal:
    - Equities/indices: tr_ds_equities (wrds_ds2dsf, code column)
    - Commodity spots: tr_ds_comds (wrds_cmdy_info + wrds_cmdy_data, dsmnemonic column)
    - Economics series: tr_ds_econ (wrds_ecoinfo + ecodata, dsmnemonic column)
    - Futures continuous: tr_ds_fut (wrds_cseries_info + wrds_fut_series, dsmnem column)
    Note: NYMEX continuous mnemonics (NCLCS00 etc.) are NOT on WRDS.
          Use source: wrds_fut for nearby-ranked term structures instead.
"""

from __future__ import annotations

import pandas as pd
import wrds
from sqlalchemy import text as sa_text

_ds_libs_cache: list[str] | None = None


def _raw_sql(conn: wrds.Connection, sql: str) -> pd.DataFrame:
    """Execute SQL via SQLAlchemy text(), bypassing wrds.raw_sql pandas 2.x compat issue."""
    with conn.engine.connect() as c:
        return pd.read_sql(sa_text(sql), c)


def _ds_libraries(conn: wrds.Connection) -> list[str]:
    global _ds_libs_cache
    if _ds_libs_cache is None:
        _ds_libs_cache = sorted(lib for lib in conn.list_libraries() if lib.startswith("tr_ds"))
    return _ds_libs_cache


def _pull_commodity(conn: wrds.Connection, mnemonic: str, start: str, watermark) -> pd.DataFrame:
    """Pull a commodity spot series from tr_ds_comds via dsmnemonic lookup."""
    wm_clause = (
        f"AND d.date_ > '{watermark}'"
        if watermark is not None
        else f"AND d.date_ >= '{start}'"
    )
    # DISTINCT: wrds_cmdy_data repeats identical rows (4 per day for gold as of 2026-09).
    sql = f"""
        SELECT DISTINCT i.dsmnemonic AS mnemonic, d.date_, d.close_, d.dsp, d.comcode
        FROM tr_ds_comds.wrds_cmdy_info i
        JOIN tr_ds_comds.wrds_cmdy_data d ON i.comcode = d.comcode
        WHERE UPPER(i.dsmnemonic) = UPPER('{mnemonic}')
        {wm_clause}
        ORDER BY d.date_
    """
    try:
        df = _raw_sql(conn, sql)
        if not df.empty:
            print(f"    {len(df):,} rows from tr_ds_comds (commodity)")
        return df
    except Exception as exc:
        print(f"    WARNING: tr_ds_comds lookup failed: {exc}")
        return pd.DataFrame()


def _pull_continuous_future(conn: wrds.Connection, mnemonic: str, start: str, watermark) -> pd.DataFrame:
    """Pull a Datastream continuous futures series from tr_ds_fut via dsmnem lookup."""
    wm_clause = (
        f"AND s.date_ > '{watermark}'"
        if watermark is not None
        else f"AND s.date_ >= '{start}'"
    )
    sql = f"""
        SELECT i.dsmnem AS mnemonic, s.date_, s.settlement, s.p
        FROM tr_ds_fut.wrds_cseries_info i
        JOIN tr_ds_fut.wrds_fut_series s ON i.calcseriescode = s.calcseriescode
        WHERE UPPER(i.dsmnem) = UPPER('{mnemonic}')
        {wm_clause}
        ORDER BY s.date_
    """
    try:
        df = _raw_sql(conn, sql)
        if not df.empty:
            print(f"    {len(df):,} rows from tr_ds_fut (continuous)")
        return df
    except Exception as exc:
        print(f"    WARNING: tr_ds_fut lookup failed: {exc}")
        return pd.DataFrame()


def _pull_equities(conn: wrds.Connection, mnemonic: str, start: str, watermark) -> pd.DataFrame:
    """Pull an equities/index series from tr_ds_equities (wrds_ds2dsf)."""
    wm_clause = (
        f"AND date_ > '{watermark}'"
        if watermark is not None
        else f"AND date_ >= '{start}'"
    )
    sql = f"""
        SELECT *
        FROM tr_ds_equities.wrds_ds2dsf
        WHERE UPPER(code) = UPPER('{mnemonic}')
        {wm_clause}
        ORDER BY date_
    """
    try:
        df = _raw_sql(conn, sql)
        if not df.empty:
            print(f"    {len(df):,} rows from tr_ds_equities.wrds_ds2dsf")
        return df
    except Exception as exc:
        print(f"    WARNING: tr_ds_equities lookup failed: {exc}")
        return pd.DataFrame()


def _pull_single(conn: wrds.Connection, mnemonic: str, start: str, watermark) -> pd.DataFrame:
    """Pull one Datastream series, trying commodity → futures continuous → equities."""
    libs = _ds_libraries(conn)
    print(f"  [{mnemonic}] searching {libs}")

    # 1. commodity spots
    if "tr_ds_comds" in libs:
        df = _pull_commodity(conn, mnemonic, start, watermark)
        if not df.empty:
            return df

    # 2. futures continuous series (wrds_cseries_info + wrds_fut_series)
    if "tr_ds_fut" in libs:
        df = _pull_continuous_future(conn, mnemonic, start, watermark)
        if not df.empty:
            return df

    # 3. equities / indices (wrds_ds2dsf)
    if "tr_ds_equities" in libs:
        df = _pull_equities(conn, mnemonic, start, watermark)
        if not df.empty:
            return df

    print(
        f"  WARNING: could not pull '{mnemonic}'.\n"
        f"  Run 'python wrdsdl.py discover tr_ds_comds' (or _fut / _equities) "
        f"to inspect available series."
    )
    return pd.DataFrame()


def pull(conn: wrds.Connection, config: dict, watermark=None) -> pd.DataFrame:
    """
    Pull one or more Datastream series by mnemonic.

    Config supports either form:
      mnemonic: CRUDOIL          -- single series
      mnemonics: [CRUDOIL, ...]  -- multiple series, returned stacked long

    If 'mnemonics' key is present but the list is empty (e.g. mnemonics not yet
    verified), the pull is skipped with a warning.

    Lookup order: tr_ds_comds (commodity spots) -> tr_ds_fut (continuous futures)
                  -> tr_ds_equities (equities/indices).
    """
    start: str = config.get("start", "1990-01-01")

    if "mnemonics" in config:
        mnemonics_list: list[str] = config.get("mnemonics") or []
        if not mnemonics_list:
            print("  WARNING: 'mnemonics' list is empty — "
                  "verify mnemonics in Datastream Navigator and populate config/datasets.yaml")
            return pd.DataFrame()

        frames: list[pd.DataFrame] = []
        for mn in mnemonics_list:
            df = _pull_single(conn, mn, start, watermark)
            if not df.empty:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    mnemonic: str = config.get("mnemonic", "")
    if not mnemonic:
        raise ValueError("Datastream config requires 'mnemonic' or 'mnemonics'")

    return _pull_single(conn, mnemonic, start, watermark)
