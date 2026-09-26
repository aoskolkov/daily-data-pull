"""
Generate the datasets.yaml mnemonic block and clean-script lookup tables
for the ds_bop_quarterly dataset.

Reads scripts/bop_coverage.csv (produced by check_bop_coverage.py).
Outputs:
  scripts/bop_yaml_block.txt    -- paste into datasets.yaml
  scripts/bop_meta.csv          -- mnemonic -> country_prefix, series_key, mktdesc
"""
import pandas as pd
from pathlib import Path

# Series suffix -> (output label, description)
SERIES = {
    "I109BXF": ("ca",                "BOP: CURRENT ACCOUNT"),
    "I1A9BXF": ("goods_balance",     "BOP: CURRENT ACCOUNT - BALANCE ON GOODS"),
    "I209BAA": ("capital_account",   "BOP: CAPITAL ACCOUNT"),
    "I309NAA": ("financial_account", "BOP: FINANCIAL ACCOUNT"),
    "I3A9AAA": ("fdi_assets",        "BOP: FINANCIAL ACCOUNT - DIRECT INVESTMENT, ASSETS"),
    "I3A9LAA": ("fdi_liabs",         "BOP: FINANCIAL ACCOUNT - DIRECT INVESTMENT, LIABILITIES"),
    "I3B9AAA": ("portfolio_assets",  "BOP: FINANCIAL ACCOUNT - PORTFOLIO INVESTMENT, ASSETS"),
    "I3B9LAA": ("portfolio_liabs",   "BOP: FINANCIAL ACCOUNT - PORTFOLIO INVESTMENT, LIABILITIES"),
    "I3D9AAA": ("other_inv_assets",  "BOP: FINANCIAL ACCOUNT - OTHER INVESTMENT, ASSETS"),
    "I3D9LAA": ("other_inv_liabs",   "BOP: FINANCIAL ACCOUNT - OTHER INVESTMENT, LIABILITIES"),
    "I3E9AAA": ("reserve_assets",    "BOP: FINANCIAL ACCOUNT - RESERVE ASSETS"),
}

cov = pd.read_csv("scripts/bop_coverage.csv", parse_dates=["date_max", "date_min"])

# Extract 2-char prefix and series suffix from mnemonic
cov["prefix"]     = cov["dsmnemonic"].str[:2]
cov["series_key"] = cov["dsmnemonic"].str[2:]

# Keep only the 11 series we want, active through 2020+
cov = cov[cov["series_key"].isin(SERIES.keys())]
cov = cov[cov["date_max"].dt.year >= 2020]

# Build prefix -> mktdesc lookup (consistent across series)
prefix_to_country = (
    cov[["prefix", "desc_english"]]
    .drop_duplicates("prefix")
    .set_index("prefix")["desc_english"]
)
# Use the coverage file's mktdesc equivalent — reconstruct from bop_mnemonics
bop_raw = pd.read_csv("scripts/bop_mnemonics.csv")
bop_raw["prefix"] = bop_raw["dsmnemonic"].str[:2]
prefix_map = (
    bop_raw[["prefix", "mktdesc"]]
    .drop_duplicates("prefix")
    .set_index("prefix")["mktdesc"]
    .to_dict()
)

cov["country"] = cov["prefix"].map(prefix_map)

# Save meta
meta = cov[["dsmnemonic", "prefix", "series_key", "country", "date_min", "date_max"]].copy()
meta["series_label"] = meta["series_key"].map({k: v[0] for k, v in SERIES.items()})
meta.to_csv("scripts/bop_meta.csv", index=False)
print(f"Meta saved: {len(meta)} rows")

# Generate YAML mnemonic block grouped by series
lines = []
for suffix, (label, desc) in SERIES.items():
    sub = cov[cov["series_key"] == suffix].sort_values("country")
    lines.append(f"      # --- {label} ({desc}) [{len(sub)} countries] ---")
    for _, r in sub.iterrows():
        country = r["country"] or r["prefix"]
        dmin = str(r["date_min"])[:7]
        dmax = str(r["date_max"])[:7]
        lines.append(f"      - {r['dsmnemonic']}  # {country} ({dmin} to {dmax})")

Path("scripts/bop_yaml_block.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

total = len(cov)
n_countries = cov["prefix"].nunique()
print(f"Total mnemonics: {total} ({n_countries} country prefixes, {len(SERIES)} series)")
print("Saved: scripts/bop_yaml_block.txt")

# Print prefix -> mktdesc for use in clean script
print("\nPrefix -> country mapping (for clean script):")
countries_in_bop = sorted(cov["prefix"].unique())
for pfx in countries_in_bop:
    country = prefix_map.get(pfx, pfx)
    print(f'    "{pfx}": "{country}",')
