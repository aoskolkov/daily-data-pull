"""Check date coverage for IMF IFS monthly CPI mnemonics (I64...F pattern)."""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.connection import wrds_connection
from sqlalchemy import text as sa_text


def q(conn, sql):
    with conn.engine.connect() as c:
        return pd.read_sql(sa_text(sql), c)


def main():
    df = pd.read_csv("scripts/cpi_mnemonics.csv")
    ifs = df[df["dsmnemonic"].str.contains(r"I64\.\.\.F", na=False, regex=True)]
    mnemonics = ifs["dsmnemonic"].tolist()
    print(f"Checking coverage for {len(mnemonics)} I64...F series...")

    mn_sql = ", ".join(f"'{m}'" for m in mnemonics)

    with wrds_connection() as conn:
        coverage = q(conn, f"""
            SELECT ei.dsmnemonic, ei.mktdesc,
                   MIN(e.perioddate) as date_min,
                   MAX(e.perioddate) as date_max,
                   COUNT(*) as n_obs
            FROM tr_ds_econ.ecodata e
            JOIN tr_ds_econ.wrds_ecoinfo ei ON e.ecoseriesid = ei.ecoseriesid
            WHERE ei.dsmnemonic IN ({mn_sql})
            GROUP BY ei.dsmnemonic, ei.mktdesc
            ORDER BY ei.mktdesc
        """)

    coverage["date_min"] = pd.to_datetime(coverage["date_min"])
    coverage["date_max"] = pd.to_datetime(coverage["date_max"])

    out = Path("scripts/cpi_coverage.csv")
    coverage.to_csv(out, index=False)
    print(f"Saved: {out}")

    # Summary
    print(f"\n{len(coverage)} series with data")
    print(f"Median start: {coverage['date_min'].dt.year.median():.0f}")
    print(f"Latest end:   {coverage['date_max'].max().date()}")
    recent = coverage[coverage["date_max"].dt.year >= 2020]
    print(f"Still active (last obs >= 2020): {len(recent)}")
    print()
    print("First 30 rows:")
    print(coverage.head(30)[["dsmnemonic", "mktdesc", "date_min", "date_max", "n_obs"]].to_string(index=False))


if __name__ == "__main__":
    main()
