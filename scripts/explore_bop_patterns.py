"""Explore mnemonic patterns for key quarterly BOP aggregates in tr_ds_econ."""
import pandas as pd

df = pd.read_csv("scripts/bop_mnemonics.csv")
q = df[df["freqcode"] == "QUAR"].copy()
q["desc_upper"] = q["desc_english"].str.upper().str.strip()

targets = [
    "BOP: CURRENT ACCOUNT",
    "BOP: FINANCIAL ACCOUNT",
    "BOP: CAPITAL ACCOUNT",
    "BOP: CURRENT ACCOUNT - BALANCE ON GOODS",
    "BOP: CURRENT ACCOUNT - BALANCE ON GOODS & SERVICES",
    "BOP: FINANCIAL ACCOUNT - DIRECT INVESTMENT, NET",
    "BOP: FINANCIAL ACCOUNT - PORTFOLIO INVESTMENT, NET",
    "BOP: FINANCIAL ACCOUNT - OTHER INVESTMENT, NET",
    "BOP: FINANCIAL ACCOUNT - RESERVE ASSETS",
    "BOP: FINANCIAL ACCOUNT - DIRECT INVESTMENT, ASSETS",
    "BOP: FINANCIAL ACCOUNT - DIRECT INVESTMENT, LIABILITIES",
]

for target in targets:
    t_upper = target.upper()
    sub = q[q["desc_upper"] == t_upper]
    if sub.empty:
        sub = q[q["desc_upper"].str.startswith(t_upper)]
    if not sub.empty:
        examples = list(sub["dsmnemonic"].head(5))
        print(f"n={len(sub):3d}  {target[:60]:60s}  eg: {examples}")
    else:
        print(f"n=  0  {target[:60]:60s}  NOT FOUND")

# Also show what the mnemonic suffix looks like for current account
print()
print("Current account mnemonics (first 20):")
ca = q[q["desc_upper"] == "BOP: CURRENT ACCOUNT"]
print(ca[["dsmnemonic", "mktdesc", "mktcode"]].head(20).to_string(index=False))
