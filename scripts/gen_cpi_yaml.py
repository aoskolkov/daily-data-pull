"""Generate the datasets.yaml mnemonic block for monthly CPI series."""
import pandas as pd
from pathlib import Path

cov = pd.read_csv("scripts/cpi_coverage.csv", parse_dates=["date_max", "date_min"])
active = cov[cov["date_max"].dt.year >= 2020].copy()

# Exclude regional/world aggregates (exact matches to avoid hitting SOUTH AFRICA etc.)
SKIP_EXACT = {
    "ADVANCED ECONOMIES", "AFRICA", "ASIA DEVELOPING", "WORLD",
    "INDUSTRIAL COUNTRIES", "DEVELOPING COUNTRIES", "EURO AREA",
    "MIDDLE EAST", "WESTERN HEMISPHERE", "EMERGING AND DEVELOPING ECONOMIES",
    "SUBSAHARA AFRICA (MIF)",
}
# Substrings that only appear in aggregate names
SKIP_CONTAINS = ["DEVELOPING ASIA", "SUBSAHARA"]

def is_aggregate(name):
    name_upper = str(name).upper().strip()
    if name_upper in SKIP_EXACT:
        return True
    return any(kw in name_upper for kw in SKIP_CONTAINS)

active = active[~active["mktdesc"].apply(is_aggregate)].sort_values("mktdesc")

print(f"Individual-country series: {len(active)}")

lines = []
for _, r in active.iterrows():
    dsm = r["dsmnemonic"]
    country = r["mktdesc"]
    dmin = str(r["date_min"])[:7]
    dmax = str(r["date_max"])[:7]
    lines.append(f"      - {dsm}  # {country} ({dmin} to {dmax})")

out = Path("scripts/cpi_yaml_block.txt")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Saved: {out}")

# Also plain list
Path("scripts/cpi_active_mnemonics.txt").write_text(
    "\n".join(active["dsmnemonic"].tolist()), encoding="utf-8"
)
