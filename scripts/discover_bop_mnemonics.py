"""
Discover IFS balance of payments / capital flow mnemonics in tr_ds_econ.

Searches wrds_ecoinfo for BOP-related descriptions (current account, capital
account, financial account, direct investment, portfolio investment, etc.).
Saves results to scripts/bop_mnemonics.csv.

Run from repo root:
    python scripts/discover_bop_mnemonics.py
"""

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
    with wrds_connection() as conn:
        print("Querying tr_ds_econ.wrds_ecoinfo for BOP/capital flow mnemonics...")

        df = q(conn, """
            SELECT dsmnemonic, desc_english, freqcode, mktcode, mktdesc,
                   currcode, unitcodedesc, srccode
            FROM tr_ds_econ.wrds_ecoinfo
            WHERE (
                desc_english ILIKE '%CURRENT ACCOUNT%'
                OR desc_english ILIKE '%CAPITAL ACCOUNT%'
                OR desc_english ILIKE '%FINANCIAL ACCOUNT%'
                OR desc_english ILIKE '%BALANCE OF PAYMENTS%'
                OR desc_english ILIKE '%DIRECT INVESTMENT%'
                OR desc_english ILIKE '%PORTFOLIO INVESTMENT%'
                OR desc_english ILIKE '%FOREIGN DIRECT%'
                OR desc_english ILIKE '%BALANCE ON GOODS%'
                OR desc_english ILIKE '%TRADE BALANCE%'
            )
            ORDER BY freqcode, mktcode, desc_english
        """)

    print(f"Found {len(df)} matching mnemonics")
    print(f"Frequency breakdown:")
    print(df["freqcode"].value_counts().to_string())

    out = Path("scripts/bop_mnemonics.csv")
    df.to_csv(out, index=False)
    print(f"\nSaved: {out}")

    # Summary by frequency and description category
    for freq in ["QUAR", "ANNL", "MONT"]:
        sub = df[df["freqcode"] == freq]
        if sub.empty:
            continue
        print(f"\n=== {freq} ({len(sub)} series) ===")
        # Show distinct descriptions (first 40 chars) with counts
        desc_counts = sub["desc_english"].str[:60].value_counts().head(20)
        for desc, n in desc_counts.items():
            print(f"  {n:4d}x  {desc}")


if __name__ == "__main__":
    main()
