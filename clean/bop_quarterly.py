"""
Clean quarterly BOP data (IMF IFS via Datastream econ) -> macrodata/bop_quarterly/.

Reads:  data/ds_bop_quarterly/  (long: date_, dsmnemonic, close_)
Writes: one wide parquet per series + meta CSV.

Series:
  ca_wide.parquet               -- current account
  goods_balance_wide.parquet    -- goods balance (trade balance)
  capital_account_wide.parquet  -- capital account
  financial_account_wide.parquet
  fdi_assets_wide.parquet       -- FDI assets (outflows, sign: negative = outflow)
  fdi_liabs_wide.parquet        -- FDI liabilities (inflows)
  portfolio_assets_wide.parquet
  portfolio_liabs_wide.parquet
  other_inv_assets_wide.parquet
  other_inv_liabs_wide.parquet
  reserve_assets_wide.parquet
  bop_meta.csv                  -- mnemonic -> country, series, units

Units vary by country (typically USD millions, some in local currency).
Check bop_meta.csv for per-series unit codes from wrds_ecoinfo.
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "ds_bop_quarterly"
OUT_DIR = ROOT / "macrodata" / "bop_quarterly"

# Mnemonic suffix -> output file label
SUFFIX_TO_LABEL = {
    "I109BXF": "ca",
    "I1A9BXF": "goods_balance",
    "I209BAA": "capital_account",
    "I309NAA": "financial_account",
    "I3A9AAA": "fdi_assets",
    "I3A9LAA": "fdi_liabs",
    "I3B9AAA": "portfolio_assets",
    "I3B9LAA": "portfolio_liabs",
    "I3D9AAA": "other_inv_assets",
    "I3D9LAA": "other_inv_liabs",
    "I3E9AAA": "reserve_assets",
}

# Datastream 2-char country prefix -> country name
PREFIX_TO_COUNTRY = {
    "AE": "Aruba",           "AF": "Afghanistan",    "AG": "Argentina",
    "AL": "Albania",         "AM": "Armenia",        "AU": "Australia",
    "BA": "Bahrain",         "BD": "Germany",        "BG": "Belgium",
    "BH": "Bahamas",         "BI": "Brunei",         "BL": "Bulgaria",
    "BP": "Bosnia Herz.",    "BR": "Brazil",         "BS": "Bangladesh",
    "BU": "Myanmar",         "BV": "Bolivia",        "BY": "Belarus",
    "BZ": "Belize",          "CB": "Colombia",       "CH": "China",
    "CL": "Chile",           "CN": "Canada",         "CP": "Cyprus",
    "CR": "Costa Rica",      "CT": "Croatia",        "CV": "Cape Verde",
    "CZ": "Czech Republic",  "DK": "Denmark",        "ED": "Ecuador",
    "EL": "El Salvador",     "EO": "Estonia",        "ES": "Spain",
    "ET": "Ethiopia",        "EY": "Egypt",          "FJ": "Fiji",
    "FN": "Finland",         "FR": "France",         "GE": "French Guiana",
    "GG": "Georgia",         "GM": "Gambia",         "GR": "Greece",
    "GW": "Guatemala",       "HA": "Haiti",          "HK": "Hong Kong",
    "HN": "Hungary",         "HO": "Honduras",       "IC": "Iceland",
    "ID": "Indonesia",       "IN": "India",          "IR": "Ireland",
    "IS": "Israel",          "IT": "Italy",          "JM": "Jamaica",
    "JO": "Jordan",          "JP": "Japan",          "KH": "Cambodia",
    "KO": "South Korea",     "KV": "Kosovo",         "KY": "Kyrgyz Rep.",
    "KZ": "Kazakhstan",      "LA": "Laos",           "LB": "Lebanon",
    "LK": "Sri Lanka",       "LN": "Lithuania",      "LS": "Lesotho",
    "LV": "Latvia",          "LX": "Luxembourg",     "MA": "Malta",
    "MC": "Morocco",         "MD": "Madagascar",     "MF": "Moldova",
    "MG": "Mongolia",        "MK": "Macedonia",      "MU": "Mauritius",
    "MX": "Mexico",          "MY": "Malaysia",       "MZ": "Mozambique",
    "NI": "Nicaragua",       "NL": "Netherlands",    "NP": "Nepal",
    "NW": "Norway",          "NZ": "New Zealand",    "OE": "Austria",
    "PA": "Panama",          "PE": "Peru",           "PH": "Philippines",
    "PK": "Pakistan",        "PO": "Poland",         "PT": "Portugal",
    "PY": "Paraguay",        "QA": "Qatar",          "RM": "Romania",
    "RS": "Russia",          "SA": "South Africa",   "SB": "Serbia",
    "SD": "Sweden",          "SE": "Seychelles",     "SI": "Saudi Arabia",
    "SJ": "Slovenia",        "SL": "Solomon Islands","SN": "Sudan",
    "SP": "Singapore",       "ST": "Sao Tome",       "SU": "Suriname",
    "SW": "Switzerland",     "SX": "Slovakia",       "TG": "Tonga",
    "TH": "Thailand",        "TJ": "Tajikistan",     "TK": "Turkey",
    "UG": "Uganda",          "UK": "United Kingdom", "UR": "Ukraine",
    "US": "United States",   "UY": "Uruguay",        "VI": "Vietnam",
    "VU": "Vanuatu",         "WA": "Namibia",        "WS": "Samoa",
}

# Exclude regional aggregates
EXCLUDE_PREFIXES = {"EM"}  # Euro Area aggregate


def main(no_csv: bool = False) -> None:
    if not DATA_DIR.exists() or not any(DATA_DIR.iterdir()):
        print("bop_quarterly: no data in data/ds_bop_quarterly/ -- run: python wrdsdl.py pull ds_bop_quarterly")
        return

    df = pd.read_parquet(DATA_DIR)
    df["date"] = pd.to_datetime(df["date_"]).dt.normalize()
    df = df.rename(columns={"dsmnemonic": "mnemonic", "close_": "value"})
    df = df[["date", "mnemonic", "value"]].dropna(subset=["value"])

    # Extract prefix (country) and suffix (series)
    df["prefix"] = df["mnemonic"].str[:2]
    df["suffix"] = df["mnemonic"].str[2:]

    # Drop regional aggregates
    df = df[~df["prefix"].isin(EXCLUDE_PREFIXES)]

    # Map to country name and series label
    df["country"] = df["prefix"].map(PREFIX_TO_COUNTRY).fillna(df["prefix"])
    df["series"]  = df["suffix"].map(SUFFIX_TO_LABEL)

    # Drop rows whose suffix we don't recognise
    df = df.dropna(subset=["series"])

    # Deduplicate (date, mnemonic) across partition boundaries
    df = df.groupby(["date", "mnemonic", "prefix", "suffix", "country", "series"])["value"].last().reset_index()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Output one wide file per series
    for suffix, label in SUFFIX_TO_LABEL.items():
        sub = df[df["suffix"] == suffix].copy()
        if sub.empty:
            continue
        # Deduplicate (date, country) — take last
        sub = sub.groupby(["date", "country"])["value"].last().reset_index()
        wide = sub.pivot(index="date", columns="country", values="value").sort_index()
        wide.columns.name = None
        wide.index.name = "date"
        out = OUT_DIR / f"{label}_wide"
        wide.to_parquet(str(out) + ".parquet")
        if not no_csv:
            wide.to_csv(str(out) + ".csv")
        yr0 = wide.index[0].year
        yr1 = wide.index[-1].year
        print(f"  {label}_wide: {wide.shape[0]} quarters x {wide.shape[1]} countries ({yr0}-{yr1})")

    # Meta
    meta = (
        df[["mnemonic", "prefix", "suffix", "country", "series"]]
        .drop_duplicates("mnemonic")
        .sort_values(["series", "country"])
        .reset_index(drop=True)
    )
    meta.to_csv(OUT_DIR / "bop_meta.csv", index=False)
    print(f"  bop_meta: {len(meta)} series")


if __name__ == "__main__":
    main(no_csv="--no-csv" in sys.argv)
