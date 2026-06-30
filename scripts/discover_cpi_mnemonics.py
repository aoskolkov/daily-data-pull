"""
Discover monthly CPI mnemonics in tr_ds_econ (Datastream economic series).

Queries wrds_ecoinfo for descriptions matching 'consumer price' or 'CPI',
filtered to monthly frequency (freqcode='MONT'). Saves to scripts/cpi_mnemonics.csv.

Run from repo root:
    python scripts/discover_cpi_mnemonics.py
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.connection import wrds_connection
from sqlalchemy import text as sa_text


def _raw_sql(conn, sql):
    with conn.engine.connect() as c:
        return pd.read_sql(sa_text(sql), c)


def main():
    with wrds_connection() as conn:
        print("Querying tr_ds_econ.wrds_ecoinfo for monthly CPI mnemonics...")

        sql = """
            SELECT
                dsmnemonic,
                desc_english,
                freqcode,
                mktcode,
                mktdesc,
                currcode,
                unitcodedesc,
                srccode
            FROM tr_ds_econ.wrds_ecoinfo
            WHERE freqcode = 'MONT'
              AND (
                desc_english ILIKE '%CONSUMER PRICE%'
                OR desc_english ILIKE '% CPI %'
                OR desc_english ILIKE '%CPI,%'
                OR desc_english ILIKE 'CPI%'
              )
            ORDER BY mktcode, desc_english
        """
        df = _raw_sql(conn, sql)

    print(f"Found {len(df)} matching mnemonics")

    out = Path("scripts/cpi_mnemonics.csv")
    df.to_csv(out, index=False)
    print(f"Saved: {out}")

    print()
    for mkt, grp in df.groupby("mktcode"):
        mktdesc = grp["mktdesc"].iloc[0] if "mktdesc" in grp.columns else ""
        print(f"--- {mkt} ({mktdesc}) ---")
        for _, r in grp.head(6).iterrows():
            print(f"  {r['dsmnemonic']:20s}  {str(r['desc_english'])[:70]}")
        if len(grp) > 6:
            print(f"  ... ({len(grp)-6} more)")
        print()


if __name__ == "__main__":
    main()
