"""Generic normalization: dates, types, shape."""

from __future__ import annotations

import pandas as pd


def normalize_dates(df: pd.DataFrame, date_col: str = "datadate") -> pd.DataFrame:
    """Parse date column to date objects; drop rows that can't be parsed."""
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    return df.dropna(subset=[date_col])


def to_tidy_long(
    df: pd.DataFrame,
    id_vars: list[str],
    var_name: str = "series",
    value_name: str = "value",
) -> pd.DataFrame:
    """Melt wide DataFrame to tidy long format."""
    return df.melt(id_vars=id_vars, var_name=var_name, value_name=value_name)
