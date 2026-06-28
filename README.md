# daily-data-pull

A config-driven pipeline for pulling, storing, and cleaning financial and macroeconomic data from WRDS (Datastream/Compustat), FRED, and the World Bank.

---

## What's in it

| Dataset group | Frequency | Source | Coverage |
|---|---|---|---|
| FX spot rates | Daily | WRDS Compustat | 1970–present, ~200 pairs |
| FX forward rates | Daily | WRDS Datastream | 1964–present, all tenors up to 20Y |
| WTI crude spot | Daily | WRDS Datastream + FRED | 1983–present |
| WTI/Brent futures curve | Daily | WRDS Datastream futures | 1990–present, nearby 1–12 |
| Precious metals | Daily | WRDS Datastream | 1968–present (gold), 1976–present (platinum) |
| LME base metals | Daily | WRDS Datastream | 1988–present (aluminium, lead) |
| Energy commodities | Daily | WRDS Datastream | 1970–present (Brent), 1983–present (gasoline) |
| Agricultural commodities | Daily | WRDS Datastream | 1979–present (grains), 1985–present (softs) |
| S&P GSCI indices | Daily | WRDS Datastream | 1969–present (spot, total return, excess return) |
| Refinitiv CRB index | Daily | WRDS Datastream | 1956–2021 |
| Country equity indices | Daily | WRDS Datastream | ~47 countries, 1950–present (US/JP), 1970s–present (EM); columns are ISO2 codes |
| VIX family | Daily | FRED | 1990–present (VIX), 2007–present (VXV 3-month) |
| World Bank macro | Annual | World Bank API | 1960–present, ~180 countries |
| World Bank fiscal | Annual | World Bank API | 1990–present, ~35 countries |
| IMF BOP/IIP/CPIS/CDIS | Annual | IMF SDMX API | 1980–present (network-dependent) |
| IMF World Economic Outlook | Annual | IMF bulk download | 1980–2029, 196 countries, 11 indicators |
| BIS international debt securities | Quarterly | BIS Statistics API | 1993–present, 87 countries |
| BIS locational banking statistics | Quarterly | BIS Statistics API | 2000–present, 48 reporting countries, cross-border claims |
| US Treasury TIC foreign holders | Monthly | US Treasury | 2000–present, 57 countries |
| Central bank policy rates | Daily | BIS Statistics API | 1946–present (US), 39 countries |
| Government bond yields 10Y | Monthly | WRDS Datastream (tr_ds_econ) | 1950–present, 41 countries |

---

## Prerequisites

- Python 3.10+
- A [WRDS account](https://wrds-www.wharton.upenn.edu/) with subscriptions to:
  - Compustat (for `fx_spot`)
  - LSEG Datastream via WRDS (`tr_ds_equities`, `tr_ds_comds`, `tr_ds_fut`) — most datasets
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

On first run the WRDS client will ask to create a `~/.pgpass` (or `%APPDATA%\postgresql\pgpass.conf` on Windows) for password-less reconnects. Answer **y** — this caches credentials locally and silences subsequent prompts.

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
    external.py          # FRED, World Bank, file-based sources
    imf.py               # IMF SDMX API (BOP, IIP, CPIS, CDIS)
    imf_weo.py           # IMF World Economic Outlook bulk file
    bis.py               # BIS Statistics REST API
    tic.py               # US Treasury TIC Major Foreign Holders

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
  tic.py                 # → macrodata/tic_holdings_wide.{parquet,csv}
  bis_debt_sec.py        # → macrodata/bis_debt_sec_by_{nat,res}_wide.{parquet,csv}
  imf_weo.py             # → macrodata/weo_{subject}_wide.{parquet,csv} + weo_long.parquet

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
gdp_growth = pd.read_parquet("macrodata/weo_ngdp_rpch_wide.parquet")
govt_debt   = pd.read_parquet("macrodata/weo_ggxwdg_wide.parquet")   # % of GDP
fiscal_bal  = pd.read_parquet("macrodata/weo_ggxcnl_wide.parquet")   # % of GDP
# or load all in long format
weo = pd.read_parquet("macrodata/weo_long.parquet")

# BIS international debt securities outstanding (USD millions, quarterly)
bis_by_nat = pd.read_parquet("macrodata/bis_debt_sec_by_nat_wide.parquet")  # by nationality
bis_by_res = pd.read_parquet("macrodata/bis_debt_sec_by_res_wide.parquet")  # by residence

# US Treasury foreign holders (billions USD, monthly)
tic = pd.read_parquet("macrodata/tic_holdings_wide.parquet")

# BIS locational banking statistics — cross-border claims by reporting country (USD millions, quarterly)
bis_lbs = pd.read_parquet("macrodata/bis_lbs_wide.parquet")
```

Parquet preserves column dtypes (dates stay dates, floats stay floats). Each `.parquet` file has a companion `.csv` for quick inspection in Excel.

---

## Known limitations

- **LME copper, zinc, nickel, tin cash prices** are not in `tr_ds_comds`. The series `LCPCASH`, `LZZCASH`, `LNICASH`, `LTICASH` appear to live in a different WRDS schema. Workaround: use the futures term structure from `ds_wti_curve` / `ds_brent_curve` pattern applied to LME.
- **Henry Hub natural gas** (`NATLGAS`) ended 2020-09 in Datastream. No active USD spot series found in `tr_ds_comds` after that date; UK NBP gas (`NATBGAS`, GBP) is active.
- **IMF datasets** (imf_bop, imf_iip, imf_cpis, imf_cdis) require access to `dataservices.imf.org`. This is blocked on some institutional networks. They work fine on unrestricted connections.
- **Bloomberg Commodity Index (BCOM)** not found in `tr_ds_comds`. Use S&P GSCI (`CGSYSPT`) or CRB (`NYFECRB`) as alternatives.
- **Brazil equity** (`D2BRFS$`) is the DJGL Brazil Financial Services sub-index, not the Bovespa (IBOVESPA). Swap this mnemonic in `config/datasets.yaml` if you need the headline index.
- **TIC country list changes over time**: `mfhhis01.txt` covers 2000–present with ~57 countries, but the set of reported countries has changed (new countries are added when their holdings cross a reporting threshold). The `All Other` residual captures the rest.
- **IMF WEO subject code changes**: The codes in the WEO bulk file change between editions. `GGR_NGDP`/`GGX_NGDP`/`GGXONLB` are the correct codes as of Oct 2024; older editions used `GGREV`/`GGEXP`/`GGPB`.
- **World Bank fiscal coverage** (`wb_govt_revenue`, `wb_govt_expenditure`) is sparse — around 35 countries with data mainly after 2000. Use IMF WEO (`GGR_NGDP`, `GGX_NGDP`) for broader coverage (196 countries).
