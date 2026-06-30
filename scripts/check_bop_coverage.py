"""
Check date coverage for key BOP quarterly series in tr_ds_econ.
Samples current account + financial account mnemonics.
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


# BOP series suffixes: description -> mnemonic suffix
SERIES = {
    "current_account":        ("I109BXF", "BOP: CURRENT ACCOUNT"),
    "goods_balance":          ("I1A9BXF", "BOP: CURRENT ACCOUNT - BALANCE ON GOODS"),
    "capital_account":        ("I209BAA", "BOP: CAPITAL ACCOUNT"),
    "financial_account":      ("I309NAA", "BOP: FINANCIAL ACCOUNT"),
    "fdi_assets":             ("I3A9AAA", "BOP: FINANCIAL ACCOUNT - DIRECT INVESTMENT, ASSETS"),
    "fdi_liabs":              ("I3A9LAA", "BOP: FINANCIAL ACCOUNT - DIRECT INVESTMENT, LIABILITIES"),
    "portfolio_assets":       ("I3B9AAA", "BOP: FINANCIAL ACCOUNT - PORTFOLIO INVESTMENT, ASSETS"),
    "portfolio_liabs":        ("I3B9LAA", "BOP: FINANCIAL ACCOUNT - PORTFOLIO INVESTMENT, LIABILITIES"),
    "other_inv_assets":       ("I3D9AAA", "BOP: FINANCIAL ACCOUNT - OTHER INVESTMENT, ASSETS"),
    "other_inv_liabs":        ("I3D9LAA", "BOP: FINANCIAL ACCOUNT - OTHER INVESTMENT, LIABILITIES"),
    "reserve_assets":         ("I3E9AAA", "BOP: FINANCIAL ACCOUNT - RESERVE ASSETS"),
}


def main():
    df = pd.read_csv("scripts/bop_mnemonics.csv")
    q_df = df[df["freqcode"] == "QUAR"].copy()
    q_df["desc_upper"] = q_df["desc_english"].str.upper().str.strip()

    # Collect all mnemonics for all series
    all_mnemonics = []
    for key, (suffix, desc) in SERIES.items():
        sub = q_df[q_df["desc_upper"] == desc.upper()]
        all_mnemonics.extend(sub["dsmnemonic"].tolist())

    print(f"Total mnemonics across {len(SERIES)} series: {len(all_mnemonics)}")
    mn_sql = ", ".join(f"'{m}'" for m in all_mnemonics)

    with wrds_connection() as conn:
        coverage = q(conn, f"""
            SELECT ei.dsmnemonic, ei.desc_english,
                   MIN(e.perioddate) as date_min,
                   MAX(e.perioddate) as date_max,
                   COUNT(*) as n_obs
            FROM tr_ds_econ.ecodata e
            JOIN tr_ds_econ.wrds_ecoinfo ei ON e.ecoseriesid = ei.ecoseriesid
            WHERE ei.dsmnemonic IN ({mn_sql})
            GROUP BY ei.dsmnemonic, ei.desc_english
        """)

    coverage["date_min"] = pd.to_datetime(coverage["date_min"])
    coverage["date_max"] = pd.to_datetime(coverage["date_max"])
    coverage["series_key"] = coverage["dsmnemonic"].str[2:]  # strip 2-char country prefix

    out = Path("scripts/bop_coverage.csv")
    coverage.to_csv(out, index=False)
    print(f"Saved: {out}")

    print("\nCoverage by series type:")
    for key, (suffix, desc) in SERIES.items():
        sub = coverage[coverage["series_key"] == suffix]
        active = sub[sub["date_max"].dt.year >= 2020]
        if not sub.empty:
            med_start = sub["date_min"].dt.year.median()
            latest = sub["date_max"].max()
            print(f"  {key:30s}: {len(sub):3d} total, {len(active):3d} active  "
                  f"median start {med_start:.0f}  latest {latest.date()}")

    # Sample: US current account
    us_ca = coverage[coverage["dsmnemonic"] == "USI109BXF"]
    if not us_ca.empty:
        r = us_ca.iloc[0]
        print(f"\nSample: US current account ({r['dsmnemonic']}): {r['date_min'].date()} to {r['date_max'].date()}, {r['n_obs']} obs")


if __name__ == "__main__":
    main()
