"""WRDS library and table discovery utilities."""

from __future__ import annotations

import pandas as pd
import wrds


def list_libraries(conn: wrds.Connection) -> list[str]:
    return sorted(conn.list_libraries())


def describe_table(conn: wrds.Connection, library: str, table: str) -> pd.DataFrame:
    return conn.describe_table(library=library, table=table)


def sample_table(conn: wrds.Connection, library: str, table: str, n: int = 5) -> pd.DataFrame:
    return conn.get_table(library=library, table=table, obs=n)


def fetch_pairs(
    conn: wrds.Connection,
    library: str,
    table: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Distinct (fromcurd, tocurd) pairs with row counts and date coverage."""
    sql = f"""
        SELECT fromcurd, tocurd, COUNT(*) AS n_rows,
               MIN(datadate) AS first_date, MAX(datadate) AS last_date
        FROM {library}.{table}
        WHERE datadate BETWEEN '{start}' AND '{end}'
          AND exratd IS NOT NULL
        GROUP BY fromcurd, tocurd
        ORDER BY fromcurd, tocurd
    """
    return conn.raw_sql(sql, date_cols=["first_date", "last_date"])


def fetch_coverage(
    conn: wrds.Connection,
    library: str,
    table: str,
    base_ccy: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """tocurd coverage for a given fromcurd anchor."""
    sql = f"""
        SELECT tocurd AS currency, COUNT(*) AS n_rows,
               MIN(datadate) AS first_date, MAX(datadate) AS last_date
        FROM {library}.{table}
        WHERE datadate BETWEEN '{start}' AND '{end}'
          AND fromcurd = '{base_ccy}'
          AND exratd IS NOT NULL
        GROUP BY tocurd
        ORDER BY n_rows DESC, tocurd
    """
    return conn.raw_sql(sql, date_cols=["first_date", "last_date"])
