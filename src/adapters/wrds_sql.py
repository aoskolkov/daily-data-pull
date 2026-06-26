"""Adapter for any WRDS SQL-queryable library (comp, crsp, optionm, ibes, taq, …)."""

from __future__ import annotations

import pandas as pd
import wrds
from sqlalchemy import text as sa_text


def _raw_sql(conn: wrds.Connection, sql: str, params: dict | None = None) -> pd.DataFrame:
    """Execute SQL via SQLAlchemy text(), bypassing the wrds raw_sql params compat issue.

    wrds.Connection.raw_sql() passes params to pd.read_sql_query which breaks
    with pandas 2.x + newer SQLAlchemy when params is a non-empty dict.
    Using sqlalchemy.text() with bindparams is the portable fix.
    """
    if params:
        stmt = sa_text(sql).bindparams(**params)
    else:
        stmt = sa_text(sql)
    with conn.engine.connect() as c:
        return pd.read_sql(stmt, c)


def pull(conn: wrds.Connection, config: dict, watermark=None) -> pd.DataFrame:
    """
    Build and execute a SELECT against a WRDS table per manifest config.

    Supports:
    - Explicit field list or SELECT *
    - Optional WHERE filters from the manifest
    - Incremental watermark on incremental_key column
    - Year-templated table names (e.g. "vsurfd{year}" with year_range: [1996, 2023])
    """
    library = config["library"]
    table_template = config["table"]
    fields: list[str] = config.get("fields") or []
    filters: str = config.get("filters", "")
    incremental_key: str | None = config.get("incremental_key")
    year_range = config.get("year_range")
    params_extra: dict = config.get("params", {})

    # Expand year-templated table names
    if year_range and "{year}" in table_template:
        tables = [table_template.replace("{year}", str(y)) for y in range(int(year_range[0]), int(year_range[1]) + 1)]
    else:
        tables = [table_template]

    dfs: list[pd.DataFrame] = []
    for table in tables:
        field_str = ", ".join(fields) if fields else "*"
        conditions: list[str] = []
        if filters:
            conditions.append(f"({filters})")
        if incremental_key and watermark is not None:
            conditions.append(f"{incremental_key} > :watermark")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT {field_str} FROM {library}.{table} {where}"

        params: dict = {**params_extra}
        if incremental_key and watermark is not None:
            params["watermark"] = str(watermark)

        try:
            df = _raw_sql(conn, sql, params if params else None)
            if not df.empty:
                dfs.append(df)
        except Exception as exc:
            print(f"WARNING: pull failed for {library}.{table}: {exc}")

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
