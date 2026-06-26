# CLAUDE.md — AI helper instructions

This file gives an AI assistant the context needed to work in this repo without re-deriving the architecture from scratch.

---

## What this repo does

Config-driven pipeline: download financial/macro data from WRDS, FRED, and World Bank → store as raw Parquet in `data/` → clean/pivot to wide format in `output/`. Entry point is `python wrdsdl.py <subcommand>`.

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
clean/<name>.py           ← reads data/, writes output/; standalone scripts, no src/ imports
```

**Data flow:**
1. `datasets.yaml` defines a dataset (name, source, config keys)
2. `cli.py:do_pull()` dispatches to the matching adapter
3. Adapter returns a DataFrame; storage writes it partitioned by date
4. Watermark is updated to `max(date_col)`
5. Next pull passes `watermark` to adapter → adapter adds `AND date > '{watermark}'` to SQL

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
Multi-mnemonic Datastream economic series (tr_ds_econ library — IMF IFS and national sources). Config: `mnemonics` (list), `start`. **Schema differs from other tr_ds_* tables**: join key is `ecoseriesid` (not `dsmnemonic`); value column is `series_value` (not `close_`); date column is `perioddate` (not `date_`). The adapter normalises output to `date_, dsmnemonic, close_` to match `wrds_ds_comds` conventions. Requires WRDS connection. Mostly monthly frequency.

### bis
BIS Statistics REST API (`stats.bis.org/api/v1`). Config: `dataflow`, `key` (dot-separated dimension values), `start`, `period_format` (optional: `quarterly` default, `monthly`, `daily`). No WRDS connection needed. **Correct dataflow IDs** (from live API as of 2026-06): `WS_DEBT_SEC2_PUB` (international debt securities), `WS_CBS_PUB` (consolidated banking), `WS_LBS_D_PUB` (locational banking), `WS_TC` (total credit), `WS_EER` (effective exchange rates), `WS_CBPOL` (central bank policy rates). The `WS_DEBT_SEC2` ID used in older documentation no longer exists — use `WS_DEBT_SEC2_PUB`. Key `Q.....C.A..TO1.C.A.A.A.A.C` = quarterly, all issuers, total amounts outstanding in all currencies. **For daily/monthly data (e.g. WS_CBPOL), set `period_format: daily` or `period_format: monthly`** — the default `quarterly` will send wrong `startPeriod` format and return no data. Output: `date, <dimension_cols>, obs_value`.

### tic
US Treasury TIC Major Foreign Holders. Config: `start`. No WRDS connection needed. Fetches two files: `mfhhis01.txt` from `https://treasury.gov/resource-center/data-chart-center/tic/Documents/` (full archive, 2000–present, 26 year-blocks in one tab-delimited file) and `mfh.txt` from `ticdata.treasury.gov` (current rolling window for most recent months). Output: `date, country, holdings_bln_usd`.

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
  ecodata       : ecoseriesid, perioddate, series_value  (observations)
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
- **Brent individual contract prefix** confirmed as `LLC` (verified 2026-06-25). Dead prefix `LBZCS` also exists but ends ~2005.
- **Brazil equity mnemonic** `D2BRFS$` is DJGL Brazil Financial Services, not IBOVESPA. To fix: find the IBOVESPA mnemonic in `ds2equityindex` and update `config/datasets.yaml`.
- **TIC historical URL** — The archive is at `treasury.gov` (not `ticdata.treasury.gov`), filename `mfhhis01.txt`. The file `mfhis.txt` and `mfhhis01.csv` also exist at the same path but `mfhhis01.txt` is most reliable.
- **WEO subject code drift** — IMF renumbered fiscal codes: `GGREV→GGR_NGDP`, `GGEXP→GGX_NGDP`, `GGPB→GGXONLB`. If subjects return 0 rows, verify codes against the downloaded `.xls` file with `pd.read_csv(path, sep='\t', encoding='utf-16-le')['WEO Subject Code'].unique()`.
- **BIS dataflow naming** — `WS_DEBT_SEC2` was renamed to `WS_DEBT_SEC2_PUB`. Always verify dataflow IDs with `python wrdsdl.py discover bis --dataflow <ID>` before building keys.
- **Germany / UK 10Y bond yields** — `BDGBOND.` (DE) and `UKMEDYLD` (UK) both end 2019-09 in `tr_ds_econ`. Datastream stopped updating these series. Current DE/UK yields need an alternative source (e.g. ECB, BoE, or FRED).

---

## Clean script conventions

- Read from `data/<dataset_name>/` with `pd.read_parquet(Path("data") / name)`
- Normalize dates: `pd.to_datetime(df["date_col"]).dt.normalize()`
- Write to `output/<family>/` with both `.parquet` (always) and `.csv` (unless `--no-csv`)
- Wide format: `df.pivot(index="date", columns="id_col", values="value_col")`
- Duplicate (date, id) rows: `groupby(...).last()` before pivot — storage may produce them across Parquet partition boundaries
- Gracefully skip missing datasets (print a message, don't crash)
- Register in `_CLEAN_SCRIPTS` in `src/cli.py` to include in `python wrdsdl.py clean`

---

## Output conventions

- Wide files: `output/<family>/<name>_wide.parquet` — rows=dates, cols=assets/countries
- Long files: `output/<family>/<name>_long.parquet` — rows=(date, id, value)
- Metadata: `output/<family>/<name>_meta.csv` — id → description/currency/country
- Country panels: columns use **local mnemonic** (e.g. `DJINDUS`, `JAPDOWA`); `equity_meta.csv` maps these to region codes and currency
- FX forward: by-tenor wide files in `output/fx_forward/by_tenor/{tenor}_wide.parquet`
