# daily-data-pull

A config-driven pipeline for pulling, storing, and cleaning financial and macroeconomic data from WRDS (Datastream/Compustat), FRED, the World Bank, the IMF, the BIS, the US Treasury, the CFTC and MSCI.

---

## What's in it

| Dataset group | Frequency | Source | Coverage |
|---|---|---|---|
| FX spot rates | Daily | WRDS Compustat | 1982–present, ~200 pairs |
| FX forward rates | Daily | WRDS Datastream | spot 1983–present, forwards 1990–present (12Y/15Y/20Y end 2018); USD per 1 unit of currency |
| WTI crude spot | Daily | WRDS Datastream + FRED | 1986–present |
| WTI/Brent futures curve | Daily | WRDS Datastream futures | WTI 2006–2026-04 (source stopped updating), Brent 2003–present; nearby 1–12 (F1–F12) |
| Precious metals | Daily | WRDS Datastream | 1968–present (gold), 1976–present (platinum) |
| LME base metals | Daily | WRDS Datastream | 1988–present (aluminium), 1993–present (lead) |
| Energy commodities | Daily | WRDS Datastream | 1970–present (Brent), 1983–present (gasoline) |
| Agricultural commodities | Daily | WRDS Datastream | 1979–present (grains), 1985–present (softs) |
| S&P GSCI indices | Daily | WRDS Datastream | 1969–present (spot, total return, excess return) |
| Refinitiv CRB index | Daily | WRDS Datastream | 1956–2021 |
| Country equity indices | Daily | WRDS Datastream | ~47 countries, 1950–present (US/JP), EM from 1971–2000; total return for 33; columns are ISO2 codes |
| MSCI country indices | Monthly | MSCI website | 1990–present, 45 countries, USD gross total return + price |
| VIX family | Daily | FRED | 1990–present (VIX), 2007–present (VXV 3-month) |
| World Bank macro | Annual | World Bank API | 1960–present, ~180–215 countries |
| World Bank fiscal | Annual | World Bank API | 1990–2011 for USD levels (~35 countries); 1990–2024 for expenditure and debt % of GDP (109–159 countries) |
| IMF BOP/IIP/PIP (CPIS)/DIP (CDIS) | Annual | IMF data API (api.imf.org) | 1980–present (BOP/IIP), 2001– (PIP), 2009– (DIP) |
| World Bank International Debt Statistics | Annual | World Bank API (IDS + WDI archives) | 1970–present |
| IMF World Economic Outlook | Annual | IMF bulk download | 1980–2029, 196 countries, 15 indicators |
| Monthly CPI (IMF IFS) | Monthly | WRDS Datastream (tr_ds_econ) | 1950–present, 164 countries, index + YoY |
| Quarterly balance of payments (IMF IFS) | Quarterly | WRDS Datastream (tr_ds_econ) | 1970–present, 11 aggregates × ~110–120 countries |
| BIS international debt securities | Quarterly | BIS Statistics API | 1993–present, amounts outstanding, ~155 countries |
| BIS locational banking statistics | Quarterly | BIS Statistics API | 2000–present, 48 reporting countries, cross-border claims |
| BIS effective exchange rates | Monthly | BIS Statistics API | real broad 1994–present (64 economies), nominal narrow 1964–present (26) |
| US Treasury TIC foreign holders | Monthly | US Treasury | 2000–present, 53 countries |
| CFTC FX futures positioning | Weekly | CFTC API | 2006–present (TFF, 13 contracts), 1986–present (legacy, 11 contracts) |
| Central bank policy rates | Daily | BIS Statistics API | 1946–present (GB, JP, …; US from 1954), 48 countries + euro area |
| Government bond yields 10Y | Monthly | WRDS Datastream (tr_ds_econ) | 1950–present, 41 countries (DE/UK/IE/PT/GR end 2019) |

---

## Prerequisites

- Python 3.10+
- A [WRDS account](https://wrds-www.wharton.upenn.edu/) with subscriptions to:
  - Compustat (for `fx_spot`)
  - LSEG Datastream via WRDS (`tr_ds_equities`, `tr_ds_comds`, `tr_ds_fut`, `tr_ds_econ`) — most datasets
- WRDS credentials in environment variables (see Setup)

---

## Setup

```bash
pip install -r requirements.txt
```

Set your WRDS credentials as environment variables. The pipeline reads these at startup — no credentials are stored in files in this repo.

**Windows (PowerShell, per session):**
```powershell
$env:WRDS_USERNAME = "your_username"
$env:WRDS_PASSWORD = "your_password"
```

**Windows (persistent, via System Properties → Environment Variables)** or add to your shell profile.

**macOS/Linux:**
```bash
export WRDS_USERNAME=your_username
export WRDS_PASSWORD=your_password
```

On first run the WRDS client asks to create a `~/.pgpass` (or `%APPDATA%\postgresql\pgpass.conf` on Windows) for password-less reconnects. The pipeline answers **y** automatically when the credentials are set — this caches credentials locally and silences subsequent prompts.

---

## Usage

All commands are run from the repo root.

**Pull one dataset (incremental):**
```bash
python wrdsdl.py pull fx_spot
python wrdsdl.py pull ds_metals
python wrdsdl.py pull ds_equity_indices
```

**Pull everything (incremental — skips rows already downloaded):**
```bash
python wrdsdl.py pull --all
```

**Force a full re-pull (ignores watermark):**
```bash
python wrdsdl.py refresh ds_metals
```

**Run all clean scripts (produces wide outputs in `macrodata/`):**
```bash
python wrdsdl.py clean
```

**Run a single clean script:**
```bash
python wrdsdl.py clean commodities
python wrdsdl.py clean equity_indices
```

**Browse what's been pulled:**
```bash
python wrdsdl.py catalog
```

**Explore a WRDS library or table schema:**
```bash
python wrdsdl.py discover tr_ds_comds
python wrdsdl.py discover tr_ds_comds --table wrds_cmdy_info
```

---

## Directory layout

```
config/
  datasets.yaml          # dataset manifest — add new datasets here
  connection.yaml        # env-var names for WRDS credentials
  currency_country.csv   # ISO currency ↔ country crosswalk

src/
  cli.py                 # entry point (wrdsdl.py)
  adapters/              # one adapter per data source type
    wrds_sql.py          # generic Compustat/WRDS SQL table pull
    datastream.py        # single-mnemonic Datastream commodity series
    wrds_fut.py          # Datastream futures term structure builder
    wrds_fx.py           # Datastream FX spot + forward rates
    wrds_ds_comds.py     # Datastream commodity spots/indices (multi-mnemonic)
    wrds_ds_index.py     # Datastream equity index panel (multi-mnemonic)
    wrds_ds_econ.py      # Datastream economic series, tr_ds_econ (CPI, BOP, bond yields)
    external.py          # FRED, World Bank, file-based sources
    imf.py               # IMF data API, api.imf.org (BOP, IIP, PIP/CPIS, DIP/CDIS)
    wb_api.py            # World Bank API v2 sources endpoint (IDS, WDI archives)
    imf_weo.py           # IMF World Economic Outlook bulk file
    bis.py               # BIS Statistics REST API
    tic.py               # US Treasury TIC Major Foreign Holders
    cftc.py              # CFTC Commitments of Traders (Socrata API)
    msci_web.py          # MSCI country index levels (public webapp endpoint)

clean/                   # one script per output family
  fx_spot.py             # → macrodata/fx_spot/
  fx_forward.py          # → macrodata/fx_forward/
  oil.py                 # → macrodata/oil/
  oil_curve.py           # → macrodata/oil_curve/
  commodities.py         # → macrodata/commodities/  (metals/energy/agri/indices)
  equity_indices.py      # → macrodata/equity_indices/
  inflation.py           # → macrodata/inflation/
  macro.py               # → macrodata/macro/
  capital_flows.py       # → macrodata/capital_flows/
  bilateral.py           # → macrodata/bilateral/
  vol.py                 # → macrodata/vol/
  interest_rates.py      # → macrodata/interest_rates/cbpol_wide + bond_yield_10y_wide
  cpi_monthly.py         # → macrodata/cpi_monthly/
  bop_quarterly.py       # → macrodata/bop_quarterly/
  tic.py                 # → macrodata/tic/tic_holdings_wide.{parquet,csv}
  bis_debt_sec.py        # → macrodata/bis_debt_sec/bis_debt_sec_by_{nat,res}_wide.{parquet,csv}
  bis_lbs.py             # → macrodata/bis_lbs/bis_lbs_wide.{parquet,csv}
  bis_eer.py             # → macrodata/bis_eer/{reer,neer}_wide.{parquet,csv}
  imf_weo.py             # → macrodata/imf_weo/weo_{subject}_wide.{parquet,csv} + weo_long.parquet
  msci.py                # → macrodata/msci/
  cftc_fx.py             # → macrodata/cftc_fx/
  partial_default.py     # → macrodata/sovereign_debt/

data/                    # raw Parquet from pull pipeline (one folder per dataset)
macrodata/                  # clean wide-format outputs (Parquet + CSV)
```

---

## Output format

**Wide tables** (the main output): rows = dates, columns = assets/countries/mnemonics.

```python
import pandas as pd

# Commodity prices
metals  = pd.read_parquet("macrodata/commodities/metals_wide.parquet")
energy  = pd.read_parquet("macrodata/commodities/energy_wide.parquet")
indices = pd.read_parquet("macrodata/commodities/indices_wide.parquet")

# Country equity indices — price level and total return (columns are ISO2 country codes)
pi = pd.read_parquet("macrodata/equity_indices/equity_pi_wide.parquet")
ri = pd.read_parquet("macrodata/equity_indices/equity_ri_wide.parquet")

# FX spot — country ISO3 columns
fx = pd.read_parquet("macrodata/fx_spot/fx_spot_country_wide.parquet")

# WEO — one file per indicator, date × country
gdp_growth = pd.read_parquet("macrodata/imf_weo/weo_ngdp_rpch_wide.parquet")
govt_debt   = pd.read_parquet("macrodata/imf_weo/weo_ggxwdg_ngdp_wide.parquet")   # % of GDP
fiscal_bal  = pd.read_parquet("macrodata/imf_weo/weo_ggxcnl_ngdp_wide.parquet")   # % of GDP
# or load all in long format
weo = pd.read_parquet("macrodata/imf_weo/weo_long.parquet")

# BIS international debt securities outstanding (USD millions, quarterly)
bis_by_nat = pd.read_parquet("macrodata/bis_debt_sec/bis_debt_sec_by_nat_wide.parquet")  # by nationality
bis_by_res = pd.read_parquet("macrodata/bis_debt_sec/bis_debt_sec_by_res_wide.parquet")  # by residence

# US Treasury foreign holders (billions USD, monthly)
tic = pd.read_parquet("macrodata/tic/tic_holdings_wide.parquet")

# BIS locational banking statistics — cross-border claims by reporting country (USD millions, quarterly)
bis_lbs = pd.read_parquet("macrodata/bis_lbs/bis_lbs_wide.parquet")
```

Parquet preserves column dtypes (dates stay dates, floats stay floats). Most `.parquet` files have a companion `.csv` for quick inspection in Excel (not `macro_panel`, `vol_long` or the CPIS matrices).

---

## Known limitations

- **LME copper, zinc, nickel, tin cash prices** are not in `tr_ds_comds`. The series `LCPCASH`, `LZZCASH`, `LNICASH`, `LTICASH` appear to live in a different WRDS schema. Workaround: use the futures term structure from `ds_wti_curve` / `ds_brent_curve` pattern applied to LME.
- **Henry Hub natural gas** (`NATLGAS`) ended 2020-09 in Datastream. No active USD spot series found in `tr_ds_comds` after that date; UK NBP gas (`NATBGAS`, GBP) is active.
- **IMF datasets** (imf_bop, imf_iip, imf_cpis, imf_cdis) come from `api.imf.org`. The old `dataservices.imf.org` API was retired in 2025; CPIS and CDIS are now published as PIP and DIP.
- **Bloomberg Commodity Index (BCOM)** not found in `tr_ds_comds`. Use S&P GSCI (`CGSYSPT`) instead; CRB (`NYFECRB`) ended 2021-02.
- **NYMEX WTI futures** (`ds_wti_curve`) stop on 2026-04-03: WRDS stopped updating every NWS/NCL contract. ICE Brent (`ds_brent_curve`), `ds_wti_front` (Datastream `CRUDOIL`, WTI spot at Cushing) and FRED WTI spot are current.
- **FX quoting conventions differ**: `macrodata/fx_spot/` is local currency per 1 USD; `macrodata/fx_forward/` is USD per 1 unit of currency (EUR ≈ 1.15, JPY ≈ 0.0064). Datastream pairs quoted per 100/1000 units are rescaled.
- **Brazil equity** (`D2BRFS$`) is the DJGL Brazil Financial Services sub-index, not the Bovespa (IBOVESPA). Swap this mnemonic in `config/datasets.yaml` if you need the headline index.
- **TIC country list changes over time**: `mfhhis01.txt` covers 2000 to the last full calendar year (19–45 countries per month, 53 in total); the current year comes from SLT Table 5, which lists only the top ~20 holders. The set of reported countries has changed (new countries are added when their holdings cross a reporting threshold). The `All Other` residual is not kept.
- **IMF WEO subject code changes**: The codes in the WEO bulk file change between editions. `GGR_NGDP`/`GGX_NGDP`/`GGXONLB_NGDP` are the correct % of GDP codes as of Oct 2024; older editions used `GGREV`/`GGEXP`/`GGPB`. `GGXCNL`/`GGXONLB`/`GGXWDG`/`GGXWDN` without `_NGDP` are in national currency (billions), not % of GDP.
- **World Bank fiscal coverage** (`wb_govt_revenue`, `wb_govt_expenditure`) is sparse — 35 countries (13–24 per year), 1990–2011 only. `wb_govt_revenue_pct` and `wb_fiscal_balance_pct` return no data. Use IMF WEO (`GGR_NGDP`, `GGX_NGDP`) for broader coverage (196 countries).

---

## License

The code in this repository is released under the [MIT License](LICENSE).

The license covers the code only, not the data it downloads. Each source keeps its own terms: WRDS and LSEG Datastream data are licensed to your institution's subscription and may not be redistributed, and the IMF, World Bank, BIS, FRED, US Treasury, CFTC and MSCI data are subject to their providers' terms of use. That is why `data/`, `macrodata/` and `downloads/` are never committed.
