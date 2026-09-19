#!/usr/bin/env python3
"""
Generate config/currency_country.csv — the master country/currency crosswalk.

This script is the single source of truth for country identifiers in this
pipeline. Run it once (or whenever you need to refresh names from the World
Bank API) and commit the resulting CSV.

Output columns:
  iso3c          ISO 3166-1 alpha-3  (primary key for this pipeline)
  iso2c          ISO 3166-1 alpha-2  (World Bank, IMF, OECD merge key)
  wb_code        World Bank 3-letter code (= iso3c except a handful of cases)
  currency_code  ISO 4217 currency code (for the given validity window)
  valid_from     date currency adopted (YYYY-MM-DD); empty = pre-history / unknown
  valid_to       date currency replaced (empty = still current)
  country_name_en  ISO / UN English name
  wb_name        World Bank name (as returned by wb.get_countries())
  common_name    Short display name ("South Korea", not "Korea, Republic of")

Usage:
  python scripts/build_crosswalk.py              # fetches WB names (internet needed)
  python scripts/build_crosswalk.py --offline    # hardcoded names only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

OUT = Path("config/currency_country.csv")

# ---------------------------------------------------------------------------
# Current currency per country (iso2c -> iso_4217)
# ---------------------------------------------------------------------------
CURRENT_CURRENCY: dict[str, str] = {
    # Americas
    "AR": "ARS", "BO": "BOB", "BR": "BRL", "CA": "CAD", "CL": "CLP",
    "CO": "COP", "CR": "CRC", "CU": "CUP", "DO": "DOP", "EC": "USD",
    "SV": "USD", "GT": "GTQ", "HT": "HTG", "HN": "HNL", "JM": "JMD",
    "MX": "MXN", "NI": "NIO", "PA": "USD", "PY": "PYG", "PE": "PEN",
    "PR": "USD", "TT": "TTD", "US": "USD", "UY": "UYU", "VE": "VES",
    "BS": "BSD", "BB": "BBD", "BZ": "BZD", "GY": "GYD", "SR": "SRD",
    "TC": "USD", "KY": "KYD", "BM": "BMD", "VG": "USD", "VI": "USD",
    "AG": "XCD", "DM": "XCD", "GD": "XCD", "KN": "XCD", "LC": "XCD",
    "VC": "XCD", "AI": "XCD", "MS": "XCD",
    # Europe
    "AL": "ALL", "AD": "EUR", "AM": "AMD", "AT": "EUR", "AZ": "AZN",
    "BY": "BYN", "BE": "EUR", "BA": "BAM", "BG": "BGN", "HR": "EUR",
    "CY": "EUR", "CZ": "CZK", "DK": "DKK", "EE": "EUR", "FI": "EUR",
    "FR": "EUR", "GE": "GEL", "DE": "EUR", "GR": "EUR", "HU": "HUF",
    "IS": "ISK", "IE": "EUR", "IT": "EUR", "XK": "EUR", "LV": "EUR",
    "LI": "CHF", "LT": "EUR", "LU": "EUR", "MT": "EUR", "MD": "MDL",
    "MC": "EUR", "ME": "EUR", "NL": "EUR", "MK": "MKD", "NO": "NOK",
    "PL": "PLN", "PT": "EUR", "RO": "RON", "RU": "RUB", "SM": "EUR",
    "RS": "RSD", "SK": "EUR", "SI": "EUR", "ES": "EUR", "SE": "SEK",
    "CH": "CHF", "TR": "TRY", "UA": "UAH", "GB": "GBP", "VA": "EUR",
    # Asia-Pacific
    "AF": "AFN", "AU": "AUD", "BH": "BHD", "BD": "BDT", "BT": "BTN",
    "BN": "BND", "CN": "CNY", "FJ": "FJD", "HK": "HKD", "IN": "INR",
    "ID": "IDR", "IR": "IRR", "IQ": "IQD", "IL": "ILS", "JP": "JPY",
    "JO": "JOD", "KZ": "KZT", "KW": "KWD", "KG": "KGS", "LA": "LAK",
    "LB": "LBP", "MO": "MOP", "MY": "MYR", "MV": "MVR", "MN": "MNT",
    "MM": "MMK", "NP": "NPR", "NZ": "NZD", "KP": "KPW", "OM": "OMR",
    "PK": "PKR", "PH": "PHP", "QA": "QAR", "SA": "SAR", "SG": "SGD",
    "KR": "KRW", "LK": "LKR", "SY": "SYP", "TW": "TWD", "TJ": "TJS",
    "TH": "THB", "TL": "USD", "TM": "TMT", "AE": "AED", "UZ": "UZS",
    "VN": "VND", "YE": "YER", "KI": "AUD", "MH": "USD", "FM": "USD",
    "NR": "AUD", "PW": "USD", "PG": "PGK", "WS": "WST", "SB": "SBD",
    "TO": "TOP", "TV": "AUD", "VU": "VUV",
    # Africa
    "DZ": "DZD", "AO": "AOA", "BJ": "XOF", "BW": "BWP", "BF": "XOF",
    "BI": "BIF", "CV": "CVE", "CM": "XAF", "CF": "XAF", "TD": "XAF",
    "KM": "KMF", "CD": "CDF", "CG": "XAF", "CI": "XOF", "DJ": "DJF",
    "EG": "EGP", "GQ": "XAF", "ER": "ERN", "SZ": "SZL", "ET": "ETB",
    "GA": "XAF", "GM": "GMD", "GH": "GHS", "GN": "GNF", "GW": "XOF",
    "KE": "KES", "LS": "LSL", "LR": "LRD", "LY": "LYD", "MG": "MGA",
    "MW": "MWK", "ML": "XOF", "MR": "MRU", "MU": "MUR", "MA": "MAD",
    "MZ": "MZN", "NA": "NAD", "NE": "XOF", "NG": "NGN", "RW": "RWF",
    "ST": "STN", "SN": "XOF", "SL": "SLL", "SO": "SOS", "ZA": "ZAR",
    "SS": "SSP", "SD": "SDG", "TZ": "TZS", "TG": "XOF", "TN": "TND",
    "UG": "UGX", "ZM": "ZMW", "ZW": "ZWL", "LY": "LYD",
    # Middle East / North Africa (not yet in Europe or Asia lists)
    "EH": "MAD",   # Western Sahara — uses Moroccan dirham
    "PS": "ILS",   # Palestine — uses Israeli shekel
}

# Common/display names where the formal name is unwieldy
COMMON_NAMES: dict[str, str] = {
    "BA": "Bosnia and Herzegovina",
    "BO": "Bolivia",
    "BR": "Brazil",
    "CD": "DR Congo",
    "CG": "Congo",
    "CI": "Ivory Coast",
    "CK": "Cook Islands",
    "CZ": "Czechia",
    "FM": "Micronesia",
    "GB": "United Kingdom",
    "GQ": "Equatorial Guinea",
    "HK": "Hong Kong",
    "IR": "Iran",
    "KP": "North Korea",
    "KR": "South Korea",
    "KG": "Kyrgyzstan",
    "LA": "Laos",
    "MK": "North Macedonia",
    "MM": "Myanmar",
    "MO": "Macao",
    "MP": "Northern Mariana Islands",
    "PS": "Palestine",
    "RU": "Russia",
    "ST": "Sao Tome & Principe",
    "SY": "Syria",
    "TL": "Timor-Leste",
    "TW": "Taiwan",
    "TZ": "Tanzania",
    "US": "United States",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "XK": "Kosovo",
}

# ISO3 for territories the World Bank country list does not cover
NON_WB_ISO3: dict[str, str] = {
    "TW": "TWN",   # Taiwan
    "VA": "VAT",   # Holy See
    "AI": "AIA",   # Anguilla
    "MS": "MSR",   # Montserrat
    "EH": "ESH",   # Western Sahara
}

# Cases where the World Bank 3-letter code differs from ISO 3166-1 alpha-3
WB_TO_ISO3: dict[str, str] = {
    "ROM": "ROU",   # Romania
    "ZAR": "COD",   # Congo, Dem. Rep. (WB used to use ZAR, now COD)
    "KSV": "XKX",   # Kosovo
    "TMP": "TLS",   # Timor-Leste
    "WBG": "PSE",   # West Bank and Gaza
}

# ---------------------------------------------------------------------------
# Historical currency transitions
# Each tuple: (iso2c, old_currency, valid_from, valid_to)
# The "current" entry (valid_to=None) is generated from CURRENT_CURRENCY.
# ---------------------------------------------------------------------------
HISTORICAL: list[tuple[str, str, str, str]] = [
    # ── Eurozone adoptions (legacy currency -> EUR) ──────────────────────────
    ("AT", "ATS", "",           "1998-12-31"),   # Austrian Schilling
    ("BE", "BEF", "",           "1998-12-31"),   # Belgian Franc
    ("FI", "FIM", "",           "1998-12-31"),   # Finnish Markka
    ("FR", "FRF", "",           "1998-12-31"),   # French Franc
    ("DE", "DEM", "",           "1998-12-31"),   # Deutsche Mark
    ("IE", "IEP", "",           "1998-12-31"),   # Irish Pound
    ("IT", "ITL", "",           "1998-12-31"),   # Italian Lira
    ("LU", "LUF", "",           "1998-12-31"),   # Luxembourg Franc
    ("NL", "NLG", "",           "1998-12-31"),   # Dutch Guilder
    ("PT", "PTE", "",           "1998-12-31"),   # Portuguese Escudo
    ("ES", "ESP", "",           "1998-12-31"),   # Spanish Peseta
    ("GR", "GRD", "",           "2000-12-31"),   # Greek Drachma
    ("SI", "SIT", "",           "2006-12-31"),   # Slovenian Tolar
    ("CY", "CYP", "",           "2007-12-31"),   # Cyprus Pound
    ("MT", "MTL", "",           "2007-12-31"),   # Maltese Lira
    ("SK", "SKK", "",           "2008-12-31"),   # Slovak Koruna
    ("EE", "EEK", "",           "2010-12-31"),   # Estonian Kroon
    ("LV", "LVL", "",           "2013-12-31"),   # Latvian Lats
    ("LT", "LTL", "",           "2014-12-31"),   # Lithuanian Litas
    ("HR", "HRK", "",           "2022-12-31"),   # Croatian Kuna
    # ── Dollarization ────────────────────────────────────────────────────────
    ("EC", "ECS", "",           "1999-09-09"),   # Ecuador Sucre
    ("SV", "SVC", "",           "2000-12-31"),   # El Salvador Colon
    ("ZW", "ZWL", "",           "2008-12-31"),   # Zimbabwe Dollar (hyperinflation era)
    # ── Other transitions ────────────────────────────────────────────────────
    ("MK", "YUM", "",           "1992-12-31"),   # N. Macedonia — Yugoslav Dinar
    ("RS", "YUM", "",           "2002-12-31"),   # Serbia
    ("ME", "YUM", "",           "2001-12-31"),   # Montenegro (then DEM, then EUR)
    ("BY", "BYR", "",           "2016-06-30"),   # Belarus — old ruble
    ("RO", "ROL", "",           "2004-12-31"),   # Romania — old leu
    ("TR", "TRL", "",           "2004-12-31"),   # Turkey — old lira
    ("MZ", "MZM", "",           "2005-06-30"),   # Mozambique Metical (redenominated)
    ("GH", "GHC", "",           "2007-06-30"),   # Ghana Cedi (redenominated)
    ("ZM", "ZMK", "",           "2012-12-31"),   # Zambia Kwacha (redenominated)
    ("VE", "VEF", "",           "2018-08-19"),   # Venezuela Bolivar
    ("MR", "MRO", "",           "2017-12-31"),   # Mauritania Ouguiya (redenominated)
]


def fetch_wb_countries() -> pd.DataFrame:
    """Call World Bank API for country names and codes."""
    try:
        import pandas_datareader.wb as wb
        raw = wb.get_countries()
        # The 3-letter code is column "iso3c" in pandas_datareader 0.10 and the
        # "id" column or index in older versions. Resetting a plain RangeIndex
        # would turn row numbers into codes (how iso3c once came out as 0, 2, 5).
        if "iso3c" in raw.columns:
            raw = raw.rename(columns={"iso3c": "id"})
        elif raw.index.name == "id":
            raw = raw.reset_index()
        if "id" not in raw.columns:
            raise ValueError(f"no country-code column in {list(raw.columns)}")
        raw = raw[raw["region"] != "Aggregates"].copy()
        raw = raw.rename(columns={"id": "wb_code", "name": "wb_name"})
        raw = raw[["wb_code", "iso2c", "wb_name"]].dropna(subset=["iso2c"])
        return raw.reset_index(drop=True)
    except Exception as exc:
        print(f"WARNING: Could not fetch WB country list ({exc}). Using offline mode.")
        return pd.DataFrame(columns=["wb_code", "iso2c", "wb_name"])


def build(offline: bool = False) -> pd.DataFrame:
    rows: list[dict] = []

    wb_meta = pd.DataFrame(columns=["wb_code", "iso2c", "wb_name"])
    if not offline:
        print("Fetching World Bank country list...")
        wb_meta = fetch_wb_countries()
        print(f"  {len(wb_meta)} countries from WB API")

    wb_lookup = {
        row["iso2c"]: (row["wb_code"], row["wb_name"])
        for _, row in wb_meta.iterrows()
    }

    # Build one row per (country, currency, validity period)
    processed_iso2 = set()

    # Current currencies
    for iso2c, currency in CURRENT_CURRENCY.items():
        wb_code, wb_name = wb_lookup.get(iso2c, ("", ""))
        # Map WB code to iso3c; use WB_TO_ISO3 overrides where needed
        iso3c = WB_TO_ISO3.get(wb_code, wb_code) if wb_code else NON_WB_ISO3.get(iso2c, "")

        rows.append({
            "iso3c":          iso3c,
            "iso2c":          iso2c,
            "wb_code":        wb_code,
            "currency_code":  currency,
            "valid_from":     "",
            "valid_to":       "",
            "country_name_en": "",          # filled below from WB
            "wb_name":        wb_name,
            "common_name":    COMMON_NAMES.get(iso2c, wb_name),
        })
        processed_iso2.add(iso2c)

    # Historical currencies
    for iso2c, currency, valid_from, valid_to in HISTORICAL:
        wb_code, wb_name = wb_lookup.get(iso2c, ("", ""))
        iso3c = WB_TO_ISO3.get(wb_code, wb_code) if wb_code else NON_WB_ISO3.get(iso2c, "")
        rows.append({
            "iso3c":          iso3c,
            "iso2c":          iso2c,
            "wb_code":        wb_code,
            "currency_code":  currency,
            "valid_from":     valid_from,
            "valid_to":       valid_to,
            "country_name_en": "",
            "wb_name":        wb_name,
            "common_name":    COMMON_NAMES.get(iso2c, wb_name),
        })

    # Add any WB countries not in our currency table (territories, etc.)
    for _, row in wb_meta.iterrows():
        if row["iso2c"] not in processed_iso2:
            wb_code = row["wb_code"]
            iso3c = WB_TO_ISO3.get(wb_code, wb_code)
            rows.append({
                "iso3c":          iso3c,
                "iso2c":          row["iso2c"],
                "wb_code":        wb_code,
                "currency_code":  "",
                "valid_from":     "",
                "valid_to":       "",
                "country_name_en": "",
                "wb_name":        row["wb_name"],
                "common_name":    COMMON_NAMES.get(row["iso2c"], row["wb_name"]),
            })

    df = pd.DataFrame(rows)

    # Fill country_name_en from wb_name where blank (good enough for most)
    df["country_name_en"] = df["country_name_en"].where(
        df["country_name_en"] != "", df["wb_name"]
    )

    # Sort: current entries first (valid_to == ""), then historical
    df["_current"] = (df["valid_to"] == "").astype(int)
    df = (
        df.sort_values(["iso3c", "_current", "valid_from"], ascending=[True, False, True])
        .drop(columns=["_current"])
        .reset_index(drop=True)
    )

    col_order = [
        "iso3c", "iso2c", "wb_code", "currency_code",
        "valid_from", "valid_to",
        "country_name_en", "wb_name", "common_name",
    ]
    return df[col_order]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build config/currency_country.csv")
    parser.add_argument("--offline", action="store_true",
                        help="Skip World Bank API call; use hardcoded names only")
    parser.add_argument("--out", default=str(OUT), help=f"Output path (default: {OUT})")
    args = parser.parse_args()

    df = build(offline=args.offline)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df):,} rows to {out_path.resolve()}")
    n_current = (df["valid_to"] == "").sum()
    n_hist    = (df["valid_to"] != "").sum()
    print(f"  {n_current} current entries, {n_hist} historical entries")
    print(f"  {df['iso3c'].nunique()} unique countries, "
          f"{df['currency_code'].nunique()} unique currencies")


if __name__ == "__main__":
    main()
