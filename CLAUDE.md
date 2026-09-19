# CLAUDE.md — AI helper instructions

This file gives an AI assistant the context needed to work in this repo without re-deriving the architecture from scratch.

---

## What this repo does

Config-driven pipeline: download financial/macro data from WRDS, FRED, and World Bank → store as raw Parquet in `data/` → clean/pivot to wide format in `macrodata/`. Entry point is `python wrdsdl.py <subcommand>`.

---

## Architecture

```
config/datasets.yaml      ← single source of truth for all datasets
wrdsdl.py                 ← thin shim: sys.path + invokes src/cli.py:main()
src/cli.py                ← argument parsing, dispatch, pull/clean orchestration
src/adapters/<name>.py    ← one adapter per source type; each exports pull(conn, config, watermark)
src/connection.py         ← WRDS connection with monkey-patched input() for non-interactive auth
src/storage.py            ← writes Parquet with Hive partitioning; read back with pd.read_parquet(dir)
src/state.py              ← watermark load/save (max date from last pull, stored as JSON)
clean/<name>.py           ← reads data/, writes macrodata/; standalone scripts, no src/ imports
```

**Data flow:**
1. `datasets.yaml` defines a dataset (name, source, config keys)
2. `cli.py:do_pull()` dispatches to the matching adapter
3. Adapter returns a DataFrame; storage writes it partitioned by date
4. Watermark is updated to `max(date_col)`
5. Next pull passes `watermark - lookback_days` to adapter → adapter adds `AND date > '{watermark}'` to SQL
6. Storage merges the incremental chunk into the existing year partitions (see *Incremental pulls* below)

---

## Adding a new dataset

1. Add an entry in `config/datasets.yaml` with `name`, `source`, and any source-specific keys.
2. If the source type is new, create `src/adapters/<source>.py` with a `pull(conn, config, watermark)` function that returns a DataFrame.
3. Add the source name to the dispatch in `src/cli.py:do_pull()` and to the `wrds_targets` list in `cmd_pull()` (or `noconn_targets` if it doesn't need a WRDS connection).
4. Optionally add a `clean/<name>.py` and register it in `_CLEAN_SCRIPTS` in `cli.py`.

---

## Adapter reference

### wrds_sql
Generic table pull from any WRDS library. Config: `library`, `table`, `fields`, `incremental_key`, `partition_by`.

### datastream
Single-mnemonic Datastream commodity series. Config: `mnemonic`. Queries `tr_ds_comds.wrds_cmdy_info + wrds_cmdy_data`. Output columns: `date_`, `close_`, `dsp`.

### wrds_ds_comds
Multi-mnemonic Datastream commodity spots/indices. Config: `mnemonics` (list), `start`. Source: `tr_ds_comds`. Output columns: `date_`, `dsmnemonic`, `name`, `comdesc`, `unitdesc`, `isocur`, `close_`, `dsp`. Price: use `close_` primary, `dsp` as fallback.

### wrds_ds_index
Multi-mnemonic Datastream equity index panel. Config: `mnemonics` (list), `fields` (default `[pi_, ri]`), `start`. Source: `tr_ds_equities.ds2equityindex + ds2indexdata`. **Date column is `valuedate`** (not `marketdate`). Output columns: `valuedate`, `dsindexmnem`, `indexdesc`, `region`, `isocurrcode`, `pi_`, `ri`.

### wrds_fx
Datastream FX spot + forward rates. Config: `currencies` (list of non-USD ISO codes), `tenors` (list of ratetypecodes), `start`. Source: `tr_ds_equities.ds2fxcode + ds2fxrate`. **Date column is `exratedate`**. Ratetypecodes: `SPOT`, `ONFD`, `TNFD`, `1WFD`, `1MFD`–`11MF`, `1YFD`–`10YF`, `12YF`, `15YF`, `20YF`. Empty list = no filter = pull all.

### wrds_fut
Datastream futures term structure from individual contracts. Config: `dsmnem_prefix` (e.g. `NWS` for NYMEX WTI, `LLC` for ICE Brent), `currency`, `max_nearby` (default 12), `price_col` (default `settlement`). Ranks contracts by `lasttrddate` per day → assigns nearby positions 1..N. Output columns: `date_`, `nearby`, `price`, `contrdate`, `lasttrddate`.

### external
FRED, World Bank, or local file. Config: `provider` (`fred`/`worldbank`/`file`), `series_id`/`indicator`/`path`. No WRDS connection needed.

### imf
IMF SDMX API. Config: `dataset` (BOP/IIP/CPIS/CDIS), `frequency`, `indicators`. No WRDS connection needed. **Blocked on some institutional networks** — `dataservices.imf.org` must be reachable.

### imf_weo
IMF World Economic Outlook bulk download. Config: `year`, `edition` (1=April, 2=October), `subjects` (list of WEO subject codes), `start`. No WRDS connection needed. Downloads from `https://www.imf.org/-/media/Files/Publications/WEO/WEO-Database/{year}/{Month}/WEO{Mon}{year}all.xls`. File is UTF-16 LE tab-delimited (not real Excel, despite .xls extension). Cached at `downloads/imf_weo/`. Subject codes as of Oct 2024: `GGR_NGDP`, `GGX_NGDP`, `GGXCNL`, `GGXONLB`, `GGXWDG`, `GGXWDN`, `NGDPD`, `NGDP_RPCH`, `PCPIPCH`, `BCA_NGDPD`, `LUR`. **Note: older editions (before ~2022) used different codes: `GGREV`/`GGEXP`/`GGPB` instead of `GGR_NGDP`/`GGX_NGDP`/`GGXONLB`.** Output: `date, country, subject_code, subject_descriptor, units, value`.

### wrds_ds_econ
Multi-mnemonic Datastream economic series (tr_ds_econ library — IMF IFS and national sources). Config: `mnemonics` (list), `start`. **Schema differs from other tr_ds_* tables**: join key is `ecoseriesid` (not `dsmnemonic`); value column is `series_value` (not `close_`); date column is `perioddate` (not `date_`). The adapter normalises output to `date_, dsmnemonic, close_` to match `wrds_ds_comds` conventions. **`ecodata` is point-in-time**: each revision of an observation is a separate row (`changeseq` 0 = first release, then 1, 2, …; plus `announceddate`, `msgseq`). The adapter keeps only the latest vintage via `DISTINCT ON (dsmnemonic, perioddate) ORDER BY changeseq DESC`. Before 2026-09-19 it pulled every vintage (up to 69 per observation) and the clean scripts' `groupby().last()` picked one arbitrarily — CPI YoY had 5,645 cells >50% since 2000 vs 638 after the fix. Requires WRDS connection. Mostly monthly frequency. **`wrds_ecoinfo.freqcode` uses `MONT` (not `M`) for monthly series** — use `WHERE freqcode = 'MONT'` when discovering mnemonics. Monthly CPI dataset: `ds_cpi_monthly` uses IMF IFS "Consumer Prices, All Items" mnemonic pattern `{CC}I64...F`, 164 countries, 1950–present. Clean: `macrodata/cpi_monthly/cpi_index_wide.parquet` (index levels) and `cpi_yoy_wide.parquet` (YoY % change computed as `pct_change(12)`). Mnemonic→country mapping is in `clean/cpi_monthly.py:_MNEMONIC_TO_COUNTRY`. Quarterly BOP dataset: `ds_bop_quarterly` — 11 IMF BOP aggregates × ~110–121 countries, quarterly 1970–present, 990k rows. Mnemonic pattern `{CC}I{suffix}` where suffix identifies the series (see datasets.yaml comments). 2-char Datastream country prefixes differ from ISO2 (e.g. `BD`=Germany, `OE`=Austria, `CH`=China, `CN`=Canada, `KO`=S.Korea). Euro Area aggregate (`EM` prefix) excluded in clean script. Clean: `macrodata/bop_quarterly/` — one `{series}_wide.parquet` per series (country names as columns). Use `bop_meta.csv` for mnemonic→country→series mapping and unit codes.

### bis
BIS Statistics REST API (`stats.bis.org/api/v1`). Config: `dataflow`, `key` (dot-separated dimension values), `start`, `period_format` (optional: `quarterly` default, `monthly`, `daily`). No WRDS connection needed. **Correct dataflow IDs** (from live API as of 2026-06): `WS_DEBT_SEC2_PUB` (international debt securities), `WS_CBS_PUB` (consolidated banking), `WS_LBS_D_PUB` (locational banking), `WS_TC` (total credit), `WS_EER` (effective exchange rates), `WS_CBPOL` (central bank policy rates). The `WS_DEBT_SEC2` ID used in older documentation no longer exists — use `WS_DEBT_SEC2_PUB`. Key `Q.....C.A..TO1.C.A.A.A.A.C` = quarterly, all issuers, total amounts outstanding in all currencies. **For daily/monthly data (e.g. WS_CBPOL), set `period_format: daily` or `period_format: monthly`** — the default `quarterly` will send wrong `startPeriod` format and return no data. Output: `date, <dimension_cols>, obs_value`.

**WS_LBS_D_PUB key structure** (verified 2026-06-28): 8 dimensions — `FREQ.L_MEASURE.L_POSITION.L_INSTR.L_DENOM.L_CURR_TYPE.L_PARENT_CTY.L_REP_BANK_TYPE`. The API returns extra columns beyond the key: `l_rep_cty` (reporting country ISO2), `l_cp_sector` (counterpart sector), `l_cp_country` (counterpart country), `l_pos_type` (position type). To get total cross-border claims per reporting country: filter to `l_cp_sector=A, l_cp_country=5J, l_pos_type=N` — gives one row per (date, reporting country). `5J` = all counterpart countries aggregated. `5A` = all reporting countries aggregate (exclude from country-level output). Key `Q.S.C.A.TO1.A.5J.A` = quarterly, stocks, claims (assets), all instruments, all currencies USD-equiv, all counterparts, all bank types.

**WS_EER key structure** (verified 2026-06-29): 4 dimensions — `FREQ.EER_TYPE.EER_BASKET.REF_AREA`. EER_TYPE: `R`=real (CPI-adjusted), `N`=nominal. EER_BASKET: `B`=broad (61 economies, from 1994), `N`=narrow (27 economies, from 1964). REF_AREA: ISO2 country code, or empty (trailing dot) for all. **Wildcard syntax is trailing dot, NOT `A`** — `M.R.B.` returns all countries; `M.R.B.A` returns 404. Index 2020=100. `period_format: monthly` required. Datasets: `bis_eer_real` (REER broad, 1994–) and `bis_eer_nominal` (NEER narrow, 1964–). Clean: `macrodata/bis_eer/reer_wide.parquet` and `neer_wide.parquet`.

### tic
US Treasury TIC Major Foreign Holders. Config: `start`. No WRDS connection needed. Fetches two files: `mfhhis01.txt` from `https://treasury.gov/resource-center/data-chart-center/tic/Documents/` (archive, 2000 to the last full calendar year, one tab-delimited block per year) and `slt_table5.txt` from `ticdata.treasury.gov/.../tic/Documents/` (SLT Table 5, rolling 13 months, tab-delimited, `YYYY-MM` column headers). SLT wins where they overlap. **`mfh.txt` is dead — frozen at Jan 2023** (verified 2026-09-19); SLT Table 5 replaced it. SLT lists only the top ~20 holders vs ~36 in the archive, so the current calendar year has fewer countries until Treasury appends it to the archive. Footnote suffixes (`Belgium  5/`, `United Kingdom 2/`) are stripped by `_clean_country`. Output: `date, country, holdings_bln_usd`.

### cftc
CFTC Commitments of Traders — futures positions by trader category. No WRDS connection needed. Config: `report` (`tff`/`legacy`/`disagg`), `contract_codes` (list), `start`, optional `dataset_id` override. Source: Socrata API at `publicreporting.cftc.gov` (no API key; an app token only raises the anonymous rate limit). Weekly — positions as of Tuesday, released Friday 3:30pm ET.

Reports: `tff` = Traders in Financial Futures, dataset `gpe5-46if`, 2006-06-13– — the one for FX/rates/equity-index. Sectors: dealer, asset_mgr, lev_money, other_rept, nonrept. `legacy` = dataset `6dca-aqww`, 1986-01-15– — only noncomm/comm/nonrept but 20 extra years. `disagg` = dataset `72hh-3qpy`, **physical commodities only, contains no FX**.

**ALWAYS filter with `contract_codes`, never contract or exchange names** (verified 2026-07-24): exchange names changed from `INTERNATIONAL MONETARY MARKET` to `CHICAGO MERCANTILE EXCHANGE` on 2000-08-29, so an exchange filter silently drops all pre-2000 history (14.5 years for the majors); and contract names are rewritten *retroactively* — code `112741` now reads `NZ DOLLAR` across its entire history in `contract_market_name`, while pre-2022-02-08 rows still say `NEW ZEALAND DOLLAR` in `market_and_exchange_names`. Codes are stable across both renames and unique per exchange.

CME FX codes: `099741` EUR, `097741` JPY, `096742` GBP, `092741` CHF, `090741` CAD, `232741` AUD, `112741` NZD, `095741` MXN, `102741` BRL, `122741` ZAR, `089741` RUB (dead 2022-03-15), `299741` EUR/GBP, `399741` EUR/JPY.

`long`/`short` **exclude** spreading, which is reported separately; net = long − short. Identities that must hold (both verified): sector nets sum to 0, and sum of longs + all spreading = open interest. Clean: `macrodata/cftc_fx/` — `{tff,legacy}_<sector>_net_wide.parquet` (date × ISO currency), plus `_open_interest_wide`, `cftc_fx_long`, `cftc_fx_meta.csv`.

### msci_web
MSCI Standard (Large+Mid Cap) country equity index levels. No WRDS connection needed. Config: `start` (default `1990-01-01`), `frequency` (`M` monthly default, `Q` quarterly). Uses MSCI's public webapp endpoint (`www.msci.com/webapp/indexperf/charts`) — no API key required. Downloads both gross total return (`priceLevel=41`) and price return (`priceLevel=0`) in USD (`currency=15`). Batches 45 countries across two requests (batch size 20) with a 1-second pause between. **Russia excluded**: MSCI suspended the index post-Feb 2022, endpoint returns HTTP 500. XLS response has copyright rows after the data — filtered via `pd.to_datetime(..., errors='coerce').dropna()`. Output: `date, iso2, gross_tr, price_idx`. Clean: `macrodata/msci/msci_gross_tr_wide.parquet` and `msci_price_wide.parquet`.

---

## WRDS Datastream schema map

```
tr_ds_comds
  wrds_cmdy_info   : comcode, dsmnemonic, name, comdesc, unitdesc, isocur, seriestype (S=spot, I=index)
  wrds_cmdy_data   : comcode, date_, close_, dsp

tr_ds_equities
  ds2equityindex   : dsindexcode, dsindexmnem, region, indexdesc, isocurrcode, indexstatuscode
  ds2indexdata     : dsindexcode, valuedate, pi_, ri, mv
  ds2fxcode        : exrateintcode, fromcurrcode, tocurrcode, ratetypecode, exratedesc
  ds2fxrate        : exrateintcode, exratedate, midrate, bidrate, offerrate
  wrds_ds2dsf      : dscode, marketdate, p (equity security prices — NOT index data)
  wrds_ds_names    : dscode, dssecname, typecode (IN=index, EQ=equity, ...)

tr_ds_fut
  wrds_contract_info  : dsmnem, contrdate (MMYY), lasttrddate, isocurrcode, contrname
  wrds_fut_contract   : dsmnem, date_, settlement, p
  wrds_cseries_info   : dsmnem (continuous series)
  wrds_fut_series     : dsmnem, date_, settlement

tr_ds_econ
  wrds_ecoinfo  : ecoseriesid, dsmnemonic, desc_english, freqcode, mktcode, mktdesc,
                  currcode, unitcodedesc, srccode, ...  (series metadata)
  ecodata       : ecoseriesid, changeseq, perioddate, series_value, msgseq, announceddate  (point-in-time: one row per vintage)
  — Join on ecoseriesid (NOT dsmnemonic). Date col = perioddate. Value col = series_value.
  — wrds_ds_econ adapter normalises output to date_, dsmnemonic, close_ for consistency.
```

**Column name inconsistencies across Datastream tables (common source of errors):**
- Date column: `date_` (comds/fut), `exratedate` (fx), `valuedate` (equityindex), `marketdate` (wrds_ds2dsf)
- Price column: `close_` (comds), `dsp` (comds fallback), `settlement`/`p` (fut), `midrate`/`bidrate`/`offerrate` (fx), `pi_`/`ri`/`mv` (index)

---

## Critical code patterns

### Raw SQL (pandas 2.x + SQLAlchemy compatibility fix)
`wrds.Connection.raw_sql()` fails with pandas 2.x + SQLAlchemy 2.x. All adapters use this pattern instead:

```python
from sqlalchemy import text as sa_text

def _raw_sql(conn, sql):
    with conn.engine.connect() as c:
        return pd.read_sql(sa_text(sql), c)
```

**Never use `conn.raw_sql(sql, params=dict)` with bound parameters** — it silently breaks. Build the SQL string directly with f-strings (inputs are config values, not user input, so injection is not a concern).

### Non-interactive WRDS auth
`wrds.Connection()` calls `input()` and `getpass.getpass()` even when credentials are in env vars. `src/connection.py` monkey-patches both before connecting and restores them in a `finally` block. After first run, pgpass is written and subsequent connections are silent.

### Incremental pulls
Every adapter receives `watermark` (a date string like `"2024-01-15"` or `None` for full pull). Convention:
```python
wm_clause = f"AND date_col > '{watermark}'" if watermark else f"AND date_col >= '{start}'"
```

---

## Known missing data

- **LME cash prices for Cu/Zn/Ni/Sn** (`LCPCASH`, `LZZCASH`, `LNICASH`, `LTICASH`) — not in `tr_ds_comds`. Location unknown; try `tr_ds_equities.wrds_ds_names` or `tr_ds_equities.wrds_ds2dsf`.
- **Henry Hub nat gas after 2020** — `NATLGAS` is dead. UK NBP `NATBGAS` (GBP) is active.
- **Bloomberg Commodity Index (BCOM)** — not found in `tr_ds_comds`.
- **NYMEX WTI continuous series** (`NCLCS00`) — not on WRDS at all. Use `ds_wti_curve` (nearby 1–12 built from individual contracts) instead.
- **NYMEX WTI futures stop 2026-04-03** — every `NWS` and `NCL` contract in `tr_ds_fut.wrds_fut_contract` has its last price on 2026-04-03 (verified 2026-09-19), so `ds_wti_curve` is frozen there. Source-side outage, not a prefix problem. ICE Brent (`LLC`) is current; front-month WTI (`ds_wti_front`, `CRUDOIL`) and FRED WTI spot are also current.
- **IMF SDMX host** — `dataservices.imf.org` fails DNS resolution (not just a firewall block) as of 2026-09-19; the `imf_*` datasets have never been pulled.
- **World Bank indicators** `GC.REV.TOTL.GD.ZS` ("invalid value") and `GC.BAL.CASH.GD.ZS` ("deleted or archived") return nothing, so `wb_govt_revenue_pct` and `wb_fiscal_balance_pct` have no data.
- **Brent individual contract prefix** confirmed as `LLC` (verified 2026-06-25). Dead prefix `LBZCS` also exists but ends ~2005.
- **Brazil equity mnemonic** `D2BRFS$` is DJGL Brazil Financial Services, not IBOVESPA. To fix: find the IBOVESPA mnemonic in `ds2equityindex` and update `config/datasets.yaml`. The `MNEMONIC_TO_ISO2` dict in `clean/equity_indices.py` maps this to `BR` regardless — once the mnemonic is corrected in datasets.yaml and data is re-pulled, the BR column will automatically map to the correct index.
- **TIC historical URL** — The archive is at `treasury.gov` (not `ticdata.treasury.gov`), filename `mfhhis01.txt`. The file `mfhis.txt` and `mfhhis01.csv` also exist at the same path but `mfhhis01.txt` is most reliable.
- **WEO subject code drift** — IMF renumbered fiscal codes: `GGREV→GGR_NGDP`, `GGEXP→GGX_NGDP`, `GGPB→GGXONLB`. If subjects return 0 rows, verify codes against the downloaded `.xls` file with `pd.read_csv(path, sep='\t', encoding='utf-16-le')['WEO Subject Code'].unique()`.
- **BIS dataflow naming** — `WS_DEBT_SEC2` was renamed to `WS_DEBT_SEC2_PUB`. Always verify dataflow IDs with `python wrdsdl.py discover bis --dataflow <ID>` before building keys.
- **CME exchange data** — `cmegroup.com` is Akamai-protected and returns HTTP 403 to scripted requests (both the settlements API and plain product pages), verified 2026-07-24. Deep history is behind CME DataMine (paid). For positioning data use the `cftc` adapter instead; the CFTC publishes who holds CME futures positions.
- **CFTC `EURO FX` code 099741 pre-1999** — carries 10 observations from 1986-01-15 to 1986-08-29 that are the **European Currency Unit (ECU)** contract, then a 12-year gap before the euro contract starts 1999-01-05. Different instrument; `clean/cftc_fx.py` drops them. Do not splice into a EUR series.
- **CFTC New Zealand dollar** — searching for `NEW ZEALAND` in `contract_market_name` returns nothing; the contract (code `112741`) is named `NZ DOLLAR` there across all history. Full TFF history runs 2006-06-13–present.
- **Germany / UK 10Y bond yields** — `BDGBOND.` (DE) and `UKMEDYLD` (UK) both end 2019-09 in `tr_ds_econ`. Datastream stopped updating these series. Current DE/UK yields need an alternative source (e.g. ECB, BoE, or FRED).

**Lookback.** The watermark is the max date across *all* series, so a panel with a ragged edge (CPI, BOP, bond yields, equity indices on the last trading day) would never get its late reporters. `do_pull` therefore subtracts `lookback_days` from the watermark before calling the adapter (default 14 in `defaults:`; 365–730 for the monthly/quarterly panels; `0` for `imf_weo`, which is vintage-based). Verified 2026-09-19: without it, CPI June 2026 was stuck at 44 of ~150 countries and `fx_forward` 2026-07-22 at 3 of 69 series.

**Storage merge.** Each year partition is a single `year=YYYY/part-0.parquet`. A full pull overwrites the partitions it touches; an incremental pull (`append=True`) reads the partition, drops stored rows dated on/after the chunk's first date, and appends the chunk. This makes the lookback overlap, inclusive-start adapters (`bis` startPeriod, FRED `observation_start`, `msci_web`) and re-runs after a crash all safe. **Before 2026-09-19 the incremental path overwrote the partition with just the new rows** — it never fired only because every dataset had been full-pulled once.

---

## Clean script conventions

- Read from `data/<dataset_name>/` with `pd.read_parquet(Path("data") / name)`
- Normalize dates: `pd.to_datetime(df["date_col"]).dt.normalize()`
- **World Bank annual data**: pivot on `date` (datetime), NOT on `year` (int). Convert: `wide["year"] = pd.to_datetime(wide["year"], format="%Y"); wide.rename(columns={"year": "date"})`. Wide per-indicator files get a `date` datetime column; the panel files (`macro_panel.parquet`) keep `year` as int since it's an identifier alongside `iso3c`.
- **Oil/other sources with `datetime.date`**: use `.dt.normalize()` not `.dt.date` — the latter creates Python `datetime.date` objects (object dtype), not `datetime64[ns]`, causing parquet read issues.
- Write to `macrodata/<family>/` with both `.parquet` (always) and `.csv` (unless `--no-csv`)
- Wide format: `df.pivot(index="date", columns="id_col", values="value_col")`
- Duplicate (date, id) rows: `groupby(...).last()` before pivot — storage may produce them across Parquet partition boundaries
- Gracefully skip missing datasets (print a message, don't crash)
- Register in `_CLEAN_SCRIPTS` in `src/cli.py` to include in `python wrdsdl.py clean`

---

## Output conventions

- Wide files: `macrodata/<family>/<name>_wide.parquet` — rows=dates, cols=assets/countries
- Long files: `macrodata/<family>/<name>_long.parquet` — rows=(date, id, value)
- Metadata: `macrodata/<family>/<name>_meta.csv` — id → description/currency/country
- Country panels: columns use **local mnemonic** (e.g. `DJINDUS`, `JAPDOWA`); `equity_meta.csv` maps these to region codes and currency
- FX forward: by-tenor wide files in `macrodata/fx_forward/by_tenor/{tenor}_wide.parquet`
