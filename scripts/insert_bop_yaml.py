"""Insert ds_bop_quarterly entry into config/datasets.yaml after ds_cpi_monthly."""
from pathlib import Path

anchor = "  # ── Precious & base metals (Datastream commodities) ───────────────────────────"

mnemonic_block = Path("scripts/bop_yaml_block.txt").read_text(encoding="utf-8")

header = """\
  # ── Quarterly BOP / capital flows (IMF IFS via Datastream economic series) ──
  # Source: tr_ds_econ (same as ds_cpi_monthly and ds_bond_yields_10y).
  # Mnemonic pattern: {CC}I{suffix} — 11 BOP aggregates, ~110-121 countries each.
  # Quarterly, mostly 1994-present (some series from 1970s).
  # Units vary by country (typically USD millions, check bop_meta.csv).
  # Key series suffixes:
  #   I109BXF = current account total
  #   I1A9BXF = goods balance (trade balance)
  #   I209BAA = capital account
  #   I309NAA = financial account total
  #   I3A9AAA / I3A9LAA = FDI assets (outflows) / liabilities (inflows)
  #   I3B9AAA / I3B9LAA = portfolio assets / liabilities
  #   I3D9AAA / I3D9LAA = other investment assets / liabilities
  #   I3E9AAA = reserve assets
  - name: ds_bop_quarterly
    source: wrds_ds_econ
    start: "1970-01-01"
    incremental_key: date_
    mnemonics:
"""

entry = header + mnemonic_block + """\
    note: >
      Quarterly BOP aggregates from IMF IFS via LSEG Datastream (WRDS tr_ds_econ).
      11 series x ~110-121 active countries. Euro Area aggregate (EM prefix) excluded
      in clean script. Units typically USD millions but vary — check bop_meta.csv.
      wrds_ds_econ adapter normalises output to date_, dsmnemonic, close_.
      clean/bop_quarterly.py pivots each series to a separate wide file.

"""

yaml_path = Path("config/datasets.yaml")
content = yaml_path.read_text(encoding="utf-8")

if "ds_bop_quarterly" in content:
    print("Already present — skipping.")
else:
    new_content = content.replace(anchor, entry + anchor)
    yaml_path.write_text(new_content, encoding="utf-8")
    print("Inserted ds_bop_quarterly into config/datasets.yaml")
