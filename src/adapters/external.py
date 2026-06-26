"""
Adapter for external data sources: FRED, World Bank, OECD.

Requires pandas-datareader:  pip install pandas-datareader
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def _require_datareader():
    try:
        import pandas_datareader
        import pandas_datareader.wb     # submodule not auto-imported
        import pandas_datareader.data
        return pandas_datareader
    except ImportError:
        raise RuntimeError("pandas-datareader is required.  pip install pandas-datareader")


# ── FRED ──────────────────────────────────────────────────────────────────────

def _pull_fred(config: dict, watermark=None) -> pd.DataFrame:
    pdr = _require_datareader()
    series_id: str = config["series_id"]
    start = str(watermark) if watermark is not None else config.get("start", "1970-01-01")

    df = pdr.data.DataReader(series_id, "fred", start, str(date.today()))
    return (
        df.reset_index()
        .rename(columns={"DATE": "date", series_id: "value"})
        .assign(series=series_id, source="fred")[["date", "series", "value", "source"]]
    )


# ── World Bank ────────────────────────────────────────────────────────────────

def _pull_worldbank(config: dict, watermark=None) -> pd.DataFrame:
    """
    Download a World Bank indicator for all countries.

    Output schema: date, country_name, iso2c, iso3c, indicator, value, source
    Date is set to Jan 1 of the year (World Bank data is annual).
    Regional aggregates are excluded — only sovereign countries are kept.

    Indicators useful for inflation:
      FP.CPI.TOTL     CPI index (2010 = 100)
      FP.CPI.TOTL.ZG  CPI annual inflation rate (%)
    """
    pdr = _require_datareader()
    wb = pdr.wb

    indicator: str = config["indicator"]
    start_str = str(watermark)[:4] if watermark is not None else config.get("start", "1960")
    start_year = int(start_str[:4])
    end_year = date.today().year

    print(f"  World Bank {indicator}: downloading {start_year}-{end_year}...")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        df = wb.download(indicator=indicator, country="all", start=start_year, end=end_year)
    if df.empty:
        return pd.DataFrame()

    df = (
        df.reset_index()
        .rename(columns={indicator: "value", "country": "country_name", "year": "_year"})
    )
    df["date"] = pd.to_datetime(df["_year"].astype(str) + "-01-01")
    df["indicator"] = indicator
    df["source"] = "worldbank"

    # Attach ISO codes; drop regional aggregates (region == 'Aggregates')
    try:
        meta = (
            wb.get_countries()[["name", "iso2c", "iso3c", "region"]]
            .rename(columns={"name": "country_name"})
        )
        actual = meta[meta["region"] != "Aggregates"][["country_name", "iso2c", "iso3c"]]
        df = df.merge(actual, on="country_name", how="inner")
    except Exception as exc:
        print(f"  WARNING: country metadata unavailable ({exc}); including all rows")
        df["iso2c"] = None
        df["iso3c"] = None

    result = (
        df[["date", "country_name", "iso2c", "iso3c", "indicator", "value", "source"]]
        .dropna(subset=["value"])
        .sort_values(["date", "country_name"])
        .reset_index(drop=True)
    )
    print(f"  {len(result):,} obs, {result['country_name'].nunique()} countries")
    return result


# ── OECD ─────────────────────────────────────────────────────────────────────

def _pull_oecd(config: dict, watermark=None) -> pd.DataFrame:
    """
    Download an OECD dataset via pandas_datareader.

    Output schema: date, country_iso3, indicator, value, source
    Monthly frequency for CPI.

    Dataset identifiers:
      CPI   Consumer Price Indices (monthly)

    The OECD reader returns a wide DataFrame (columns = countries).
    This adapter melts it to long format.
    """
    pdr = _require_datareader()

    dataset: str = config["dataset"]
    start = str(watermark) if watermark is not None else config.get("start", "1970-01-01")

    print(f"  OECD {dataset}: downloading from {start}...")
    try:
        df_wide = pdr.data.DataReader(dataset, "oecd", start, str(date.today()))
    except Exception as exc:
        raise RuntimeError(
            f"OECD DataReader failed for dataset '{dataset}': {exc}\n"
            "Check dataset name at https://stats.oecd.org/"
        )

    if df_wide.empty:
        return pd.DataFrame()

    # The OECD reader returns columns that may be a MultiIndex or flat country codes.
    # Flatten to a single level if needed.
    if isinstance(df_wide.columns, pd.MultiIndex):
        # Take the innermost level which typically holds country codes
        df_wide.columns = df_wide.columns.get_level_values(-1)

    df_long = (
        df_wide.reset_index()
        .rename(columns={df_wide.index.name or "index": "date"})
        .melt(id_vars=["date"], var_name="country_iso3", value_name="value")
    )
    df_long["date"] = pd.to_datetime(df_long["date"], errors="coerce")
    df_long["indicator"] = dataset
    df_long["source"] = "oecd"

    result = (
        df_long.dropna(subset=["value"])
        .sort_values(["date", "country_iso3"])
        .reset_index(drop=True)
    )
    print(f"  {len(result):,} obs, {result['country_iso3'].nunique()} countries")
    return result


# ── File (manual downloads) ───────────────────────────────────────────────────

def _pull_file(config: dict, watermark=None) -> pd.DataFrame:
    """
    Read a manually downloaded file (CSV, Excel, Parquet, Stata).

    Required config key:
      path       path to the file, relative to repo root

    Optional config keys:
      date_col   name of the date column (default: auto-detect)
      sheet      Excel sheet name or index (default: 0)
      skiprows   rows to skip at the top of CSV/Excel (default: 0)
      encoding   file encoding for CSV (default: utf-8)

    Use this for datasets distributed as file downloads rather than APIs
    (e.g. Martin 2017 SVIX, BIS locational banking statistics, etc.).
    """
    from pathlib import Path as _Path

    path = _Path(config["path"])
    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {path.resolve()}\n"
            f"Download the file and place it at that path, then re-run."
        )

    suffix = path.suffix.lower()
    skiprows = config.get("skiprows", 0)
    encoding = config.get("encoding", "utf-8")

    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, sheet_name=config.get("sheet", 0), skiprows=skiprows)
    elif suffix == ".parquet":
        df = pd.read_parquet(path)
    elif suffix in (".dta",):
        df = pd.read_stata(path)
    else:
        df = pd.read_csv(path, skiprows=skiprows, encoding=encoding)

    # Auto-detect or normalise the date column
    date_col = config.get("date_col")
    if date_col and date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        if watermark is not None:
            df = df[df[date_col] > pd.to_datetime(str(watermark))]
        df = df.rename(columns={date_col: "date"})
    else:
        # Try to find a date-like column automatically
        for col in df.columns:
            if "date" in col.lower() or "time" in col.lower():
                df[col] = pd.to_datetime(df[col], errors="coerce")
                if df[col].notna().mean() > 0.8:
                    df = df.dropna(subset=[col]).rename(columns={col: "date"})
                    break

    df["source"] = "file"
    return df.reset_index(drop=True)


# ── Dispatch ──────────────────────────────────────────────────────────────────

def pull(config: dict, watermark=None) -> pd.DataFrame:
    """Pull from an external provider. conn argument intentionally absent."""
    provider = config.get("provider", "fred")
    if provider == "fred":
        return _pull_fred(config, watermark)
    if provider == "worldbank":
        return _pull_worldbank(config, watermark)
    if provider == "oecd":
        return _pull_oecd(config, watermark)
    if provider == "file":
        return _pull_file(config, watermark)
    raise ValueError(f"Unknown external provider '{provider}'. Supported: fred, worldbank, oecd, file")
