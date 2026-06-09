"""
Download daily FX spot rates from WRDS (Compustat comp.exrt_dly).

Output: wide CSV with one row per date and one column per currency.
Units:  local currency per 1 USD.
Note: comp.exrt_dly can be anchored on a non-USD base (often GBP),
      so this script converts base-quoted rates to USD cross-rates.

Usage
-----
  python download_fx.py                     # 2000-01-01 to today → fx_daily.csv
  python download_fx.py --start 2010-01-01  # custom start date
  python download_fx.py --end 2023-12-31    # custom end date
  python download_fx.py --output my_fx.csv  # custom output path
  python download_fx.py --inspect           # print table columns + sample rows and exit
    python download_fx.py --diagnose          # print currency coverage summary from SQL
    python download_fx.py --pairs             # print all available currency pairs and exit
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

if os.name == "nt":
    import winreg

import pandas as pd
import wrds


DEFAULT_START = "2000-01-01"
DEFAULT_OUTPUT = "fx_daily.csv"


def get_env_credential(name: str) -> str | None:
    """Return credential from process env, then Windows user env registry as fallback."""
    value = os.getenv(name)
    if value:
        return value

    if os.name != "nt":
        return None

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            reg_value, _ = winreg.QueryValueEx(key, name)
            if isinstance(reg_value, str) and reg_value.strip():
                return reg_value.strip()
    except OSError:
        return None

    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download wide daily FX data (local/USD) from WRDS Compustat.")
    parser.add_argument(
        "--username",
        default=get_env_credential("WRDS_USERNAME"),
        help="WRDS username (defaults to WRDS_USERNAME env var; prompted if omitted)",
    )
    parser.add_argument(
        "--password",
        default=get_env_credential("WRDS_PASSWORD"),
        help="WRDS password (defaults to WRDS_PASSWORD env var)",
    )
    parser.add_argument("--start", default=DEFAULT_START, help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})")
    parser.add_argument("--end", default=str(date.today()), help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Output CSV path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--inspect", action="store_true",
                        help="Print comp.exrt_dly column names and 5 sample rows, then exit")
    parser.add_argument("--diagnose", action="store_true",
                        help="Print SQL-level currency coverage diagnostics before writing CSV")
    parser.add_argument("--pairs", action="store_true",
                        help="Print all distinct fromcurd/tocurd pairs in date range and exit")
    return parser.parse_args()


def connect(username: str | None, password: str | None) -> wrds.Connection:
    print("Connecting to WRDS...")
    try:
        kwargs = {}
        if username:
            kwargs["wrds_username"] = username
        if password:
            kwargs["wrds_password"] = password
        return wrds.Connection(**kwargs)
    except Exception as exc:
        print(f"ERROR: Could not connect to WRDS: {exc}", file=sys.stderr)
        sys.exit(1)


def inspect_table(conn: wrds.Connection) -> None:
    print("Columns in comp.exrt_dly:")
    cols = conn.raw_sql("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'comp' AND table_name = 'exrt_dly'
        ORDER BY ordinal_position
    """)
    print(cols.to_string(index=False))
    print("\nSample rows (5):")
    sample = conn.raw_sql("SELECT * FROM comp.exrt_dly LIMIT 5")
    print(sample.to_string(index=False))


def detect_anchor_base(conn: wrds.Connection, start: str, end: str) -> str | None:
    """Detect dominant base currency in comp.exrt_dly for the requested range."""
    query = f"""
        SELECT fromcurd, COUNT(*) AS n_rows
        FROM comp.exrt_dly
        WHERE datadate BETWEEN '{start}' AND '{end}'
          AND exratd IS NOT NULL
        GROUP BY fromcurd
        ORDER BY n_rows DESC
    """
    df = conn.raw_sql(query)
    if df.empty:
        return None
    return str(df.iloc[0]["fromcurd"])


def fetch_long(conn: wrds.Connection, start: str, end: str, base_currency: str) -> pd.DataFrame:
    """Return long-form data: datadate, currency, exratd (local per 1 USD)."""
    query = f"""
        SELECT datadate, tocurd AS currency, exratd
        FROM comp.exrt_dly
        WHERE datadate BETWEEN '{start}' AND '{end}'
          AND fromcurd = '{base_currency}'
          AND exratd IS NOT NULL
        ORDER BY datadate, tocurd
    """
    df_base = conn.raw_sql(query, date_cols=["datadate"])
    if df_base.empty:
        return pd.DataFrame(columns=["datadate", "currency", "exratd"])

    usd_series = (
        df_base[df_base["currency"] == "USD"]
        [["datadate", "exratd"]]
        .rename(columns={"exratd": "usd_per_base"})
    )

    if usd_series.empty:
        return pd.DataFrame(columns=["datadate", "currency", "exratd"])

    df = df_base.merge(usd_series, on="datadate", how="inner")
    df = df[df["usd_per_base"] != 0].copy()
    df["exratd"] = df["exratd"] / df["usd_per_base"]
    return df[["datadate", "currency", "exratd"]]


def fetch_coverage(conn: wrds.Connection, start: str, end: str, base_currency: str) -> pd.DataFrame:
        """Return SQL-level currency coverage summary for detected anchor base."""
        query = f"""
                SELECT tocurd AS currency, COUNT(*) AS n_rows,
                             MIN(datadate) AS first_date, MAX(datadate) AS last_date
                FROM comp.exrt_dly
                WHERE datadate BETWEEN '{start}' AND '{end}'
                    AND fromcurd = '{base_currency}'
                    AND exratd IS NOT NULL
                GROUP BY tocurd
                ORDER BY n_rows DESC, tocurd
        """
        return conn.raw_sql(query, date_cols=["first_date", "last_date"])


def fetch_pairs(conn: wrds.Connection, start: str, end: str) -> pd.DataFrame:
        """Return distinct currency pairs with row counts and date coverage."""
        query = f"""
                SELECT fromcurd, tocurd, COUNT(*) AS n_rows,
                             MIN(datadate) AS first_date, MAX(datadate) AS last_date
                FROM comp.exrt_dly
                WHERE datadate BETWEEN '{start}' AND '{end}'
                    AND exratd IS NOT NULL
                GROUP BY fromcurd, tocurd
                ORDER BY fromcurd, tocurd
        """
        return conn.raw_sql(query, date_cols=["first_date", "last_date"])


def to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot to wide format: rows = date, columns = currency code."""
    wide = (
        df.pivot_table(index="datadate", columns="currency", values="exratd", aggfunc="last")
        .rename_axis(None, axis="columns")
        .reset_index()
        .rename(columns={"datadate": "date"})
        .sort_values("date")
    )
    return wide


def main() -> None:
    args = parse_args()
    conn = connect(args.username, args.password)

    try:
        if args.inspect:
            inspect_table(conn)
            return

        if args.pairs:
            print(f"Listing currency pairs in comp.exrt_dly, {args.start} to {args.end}...")
            pairs = fetch_pairs(conn, args.start, args.end)
            if pairs.empty:
                print("No currency pairs found for requested date range.")
            else:
                print(f"Found {len(pairs)} distinct pairs.")
                print(pairs.to_string(index=False))
            return

        base_currency = detect_anchor_base(conn, args.start, args.end)
        if not base_currency:
            print("WARNING: No rows found in comp.exrt_dly for requested date range.")
            sys.exit(0)

        print(f"Detected anchor base currency in WRDS table: {base_currency}")
        print("Converting anchor-based quotes to local currency per 1 USD using cross rates.")

        coverage = None
        if args.diagnose:
            coverage = fetch_coverage(conn, args.start, args.end, base_currency)

        print(f"Querying all currencies vs USD, {args.start} to {args.end}...")
        df_long = fetch_long(conn, args.start, args.end, base_currency)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

    if df_long.empty:
        print("WARNING: No rows returned. Run with --inspect to verify column names.")
        sys.exit(0)

    # If a currency appears from both sides on the same day, keep the last observed quote.
    df_long = (
        df_long.sort_values(["datadate", "currency"])
        .groupby(["datadate", "currency"], as_index=False)["exratd"]
        .last()
    )

    if args.diagnose and coverage is not None:
        print("\nSQL diagnostic summary (exratd IS NOT NULL):")
        print(f"Distinct currencies: {len(coverage)}")
        if coverage.empty:
            print("No currency rows found for requested date range.")
        else:
            print(coverage.head(20).to_string(index=False))
            if len(coverage) > 20:
                print(f"... ({len(coverage) - 20} more currencies not shown)")

    n_currencies = df_long["currency"].nunique()
    date_range = f"{df_long['datadate'].min().date()} to {df_long['datadate'].max().date()}"
    print(f"Downloaded {len(df_long):,} rows — {n_currencies} currencies, {date_range}.")

    wide = to_wide(df_long)
    print(f"Wide shape: {len(wide):,} dates × {wide.shape[1] - 1} currencies.")

    out_path = Path(args.output)
    wide.to_csv(out_path, index=False)
    print(f"Saved to {out_path.resolve()}")


if __name__ == "__main__":
    main()
