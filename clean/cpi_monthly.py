"""
Clean monthly CPI data (IMF IFS via Datastream econ) -> macrodata/cpi_monthly/.

Reads:  data/ds_cpi_monthly/  (long: date_, dsmnemonic, close_)
Writes: macrodata/cpi_monthly/cpi_index_wide.{parquet,csv}   -- CPI index levels
        macrodata/cpi_monthly/cpi_yoy_wide.{parquet,csv}     -- YoY % change
        macrodata/cpi_monthly/cpi_meta.csv                   -- mnemonic -> country
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "ds_cpi_monthly"
OUT_DIR = ROOT / "macrodata" / "cpi_monthly"

# Datastream mnemonic -> country name (from wrds_ecoinfo.mktdesc)
_MNEMONIC_TO_COUNTRY: dict[str, str] = {
    "AFI64...F": "Afghanistan",     "ALI64...F": "Albania",
    "AAI64...F": "Algeria",         "AGI64...F": "Argentina",
    "AMI64...F": "Armenia",         "AEI64...F": "Aruba",
    "OEI64...F": "Austria",         "BHI64...F": "Bahamas",
    "BAI64...F": "Bahrain",         "BSI64...F": "Bangladesh",
    "BBI64...F": "Barbados",        "BGI64...F": "Belgium",
    "BZI64...F": "Belize",          "BEI64...F": "Benin",
    "BTI64...F": "Bhutan",          "BVI64...F": "Bolivia",
    "BPI64...F": "Bosnia Herz.",    "BOI64...F": "Botswana",
    "BRI64...F": "Brazil",          "BII64...F": "Brunei",
    "BLI64...F": "Bulgaria",        "UVI64...F": "Burkina Faso",
    "BNI64...F": "Burundi",         "KHI64...F": "Cambodia",
    "CAI64...F": "Cameroon",        "CNI64...F": "Canada",
    "CVI64...F": "Cape Verde",      "CEI64...F": "Central Africa Rep.",
    "CDI64...F": "Chad",            "CLI64...F": "Chile",
    "CBI64...F": "Colombia",        "COI64...F": "Congo",
    "CRI64...F": "Costa Rica",      "IVI64...F": "Cote d'Ivoire",
    "CTI64...F": "Croatia",         "CPI64...F": "Cyprus",
    "CZI64...F": "Czech Republic",  "DKI64...F": "Denmark",
    "DJI64...F": "Djibouti",        "DOI64...F": "Dominica",
    "DRI64...F": "Dominican Rep.",  "EDI64...F": "Ecuador",
    "EYI64...F": "Egypt",           "ELI64...F": "El Salvador",
    "EQI64...F": "Equatorial Guinea","EOI64...F": "Estonia",
    "ETI64...F": "Ethiopia",        "FJI64...F": "Fiji",
    "FNI64...F": "Finland",         "FRI64...F": "France",
    "GAI64...F": "Gabon",           "GMI64...F": "Gambia",
    "GGI64...F": "Georgia",         "BDI64...F": "Germany",
    "GHI64...F": "Ghana",           "GRI64...F": "Greece",
    "GNI64...F": "Grenada",         "GWI64...F": "Guatemala",
    "GEI64...F": "Guinea",          "GII64...F": "Guinea-Bissau",
    "GYI64...F": "Guyana",          "HAI64...F": "Haiti",
    "HOI64...F": "Honduras",        "HKI64...F": "Hong Kong",
    "HNI64...F": "Hungary",         "ICI64...F": "Iceland",
    "INI64...F": "India",           "IDI64...F": "Indonesia",
    "IAI64...F": "Iran",            "IQI64...F": "Iraq",
    "IRI64...F": "Ireland",         "ISI64...F": "Israel",
    "ITI64...F": "Italy",           "JMI64...F": "Jamaica",
    "JPI64...F": "Japan",           "JOI64...F": "Jordan",
    "KZI64...F": "Kazakhstan",      "KNI64...F": "Kenya",
    "KVI64...F": "Kosovo",          "KWI64...F": "Kuwait",
    "KYI64...F": "Kyrgyz Republic", "LAI64...F": "Laos",
    "LVI64...F": "Latvia",          "LBI64...F": "Lebanon",
    "LSI64...F": "Lesotho",         "LYI64...F": "Libya",
    "LNI64...F": "Lithuania",       "LXI64...F": "Luxembourg",
    "MOI64...F": "Macau",           "MKI64...F": "Macedonia",
    "MDI64...F": "Madagascar",      "MII64...F": "Malawi",
    "MYI64...F": "Malaysia",        "MVI64...F": "Maldives",
    "MLI64...F": "Mali",            "MAI64...F": "Malta",
    "MRI64...F": "Mauritania",      "MUI64...F": "Mauritius",
    "MXI64...F": "Mexico",          "MFI64...F": "Moldova",
    "MGI64...F": "Mongolia",        "MNI64...F": "Montenegro",
    "MCI64...F": "Morocco",         "MZI64...F": "Mozambique",
    "BUI64...F": "Myanmar",         "WAI64...F": "Namibia",
    "NPI64...F": "Nepal",           "NLI64...F": "Netherlands",
    "NII64...F": "Nicaragua",       "NRI64...F": "Niger",
    "NGI64...F": "Nigeria",         "NWI64...F": "Norway",
    "OMI64...F": "Oman",            "PKI64...F": "Pakistan",
    "PAI64...F": "Panama",          "PYI64...F": "Paraguay",
    "PEI64...F": "Peru",            "PHI64...F": "Philippines",
    "POI64...F": "Poland",          "PTI64...F": "Portugal",
    "QAI64...F": "Qatar",           "RMI64...F": "Romania",
    "RSI64...F": "Russia",          "RWI64...F": "Rwanda",
    "SKI64...F": "Saint Kitts & Nevis","LCI64...F": "Saint Lucia",
    "SVI64...F": "Saint Vincent",   "WSI64...F": "Samoa",
    "SFI64...F": "San Marino",      "STI64...F": "Sao Tome",
    "SII64...F": "Saudi Arabia",    "SGI64...F": "Senegal",
    "SBI64...F": "Serbia",          "SEI64...F": "Seychelles",
    "SRI64...F": "Sierra Leone",    "SPI64...F": "Singapore",
    "SXI64...F": "Slovakia",        "SJI64...F": "Slovenia",
    "SLI64...F": "Solomon Islands", "SAI64...F": "South Africa",
    "KOI64...F": "South Korea",     "ESI64...F": "Spain",
    "LKI64...F": "Sri Lanka",       "SNI64...F": "Sudan",
    "SUI64...F": "Suriname",        "SZI64...F": "Eswatini",
    "SDI64...F": "Sweden",          "SWI64...F": "Switzerland",
    "TNI64...F": "Tanzania",        "THI64...F": "Thailand",
    "TII64...F": "Timor-Leste",     "TOI64...F": "Togo",
    "TGI64...F": "Tonga",           "TTI64...F": "Trinidad & Tobago",
    "TUI64...F": "Tunisia",         "TKI64...F": "Turkey",
    "UGI64...F": "Uganda",          "URI64...F": "Ukraine",
    "UKI64...F": "United Kingdom",  "USI64...F": "United States",
    "UYI64...F": "Uruguay",         "VII64...F": "Vietnam",
    "ZMI64...F": "Zambia",          "ZII64...F": "Zimbabwe",
}


def main(no_csv: bool = False) -> None:
    if not DATA_DIR.exists() or not any(DATA_DIR.iterdir()):
        print("cpi_monthly: no data in data/ds_cpi_monthly/ -- run: python wrdsdl.py pull ds_cpi_monthly")
        return

    df = pd.read_parquet(DATA_DIR)
    df["date"] = pd.to_datetime(df["date_"]).dt.normalize()
    df = df.rename(columns={"dsmnemonic": "mnemonic", "close_": "cpi"})
    df = df[["date", "mnemonic", "cpi"]].dropna(subset=["cpi"])

    # Deduplicate across partition boundaries
    df = df.groupby(["date", "mnemonic"])["cpi"].last().reset_index()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Index level (wide) ---
    index_wide = df.pivot(index="date", columns="mnemonic", values="cpi").sort_index()
    index_wide.columns.name = None
    index_wide.index.name = "date"
    index_wide.to_parquet(OUT_DIR / "cpi_index_wide.parquet")
    if not no_csv:
        index_wide.to_csv(OUT_DIR / "cpi_index_wide.csv")
    print(f"  cpi_index_wide: {index_wide.shape[0]} months x {index_wide.shape[1]} countries"
          f" ({index_wide.index[0].year}-{index_wide.index[-1].year})")

    # --- YoY % change (wide) ---
    yoy = index_wide.pct_change(12, fill_method=None) * 100
    yoy.to_parquet(OUT_DIR / "cpi_yoy_wide.parquet")
    if not no_csv:
        yoy.to_csv(OUT_DIR / "cpi_yoy_wide.csv")
    print(f"  cpi_yoy_wide:   {yoy.shape[0]} months x {yoy.shape[1]} countries")

    # --- Metadata ---
    meta = pd.DataFrame([
        {"mnemonic": m, "country": _MNEMONIC_TO_COUNTRY.get(m, m)}
        for m in sorted(df["mnemonic"].unique())
    ])
    meta.to_csv(OUT_DIR / "cpi_meta.csv", index=False)
    print(f"  cpi_meta:       {len(meta)} series")


if __name__ == "__main__":
    main(no_csv="--no-csv" in sys.argv)
