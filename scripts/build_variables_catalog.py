"""
Generate variables.csv in the repo root.

One row per main output parquet file. Auto-reads date range and series count from
each file; human-curated descriptions and metadata are defined in CATALOG below.

n_series:
  wide files         number of data columns (excluding date/year and any `id_cols`)
  long/panel files   number of distinct keys in the entry's `series_by` columns
                     (e.g. (currency, tenor) for fx_forward_long)

Usage:
    python scripts/build_variables_catalog.py
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Hand-curated catalog entries
# Keys are paths relative to the repo root. Optional keys (not written to the CSV):
#   series_by  columns whose distinct combinations are the series (long/panel files)
#   id_cols    non-date identifier columns to exclude from a wide file's series count
# ---------------------------------------------------------------------------
CATALOG: list[dict] = [
    # ── Trade in goods (IMF ITG + IMTS) ─────────────────────────────────────
    dict(
        variable_id="trade_goods_exports_monthly",
        path="macrodata/trade/goods_exports_monthly_wide.parquet",
        description="Merchandise exports, free on board (FOB), monthly. IMF International Trade in Goods (ITG); country totals, not by partner.",
        family="trade",
        frequency="monthly",
        source="IMF ITG (api.imf.org)",
        unit="USD",
        panel_columns="ISO3 country code",
    ),
    dict(
        variable_id="trade_goods_imports_monthly",
        path="macrodata/trade/goods_imports_monthly_wide.parquet",
        description="Merchandise imports, cost-insurance-freight (CIF), monthly. IMF International Trade in Goods (ITG).",
        family="trade",
        frequency="monthly",
        source="IMF ITG (api.imf.org)",
        unit="USD",
        panel_columns="ISO3 country code",
    ),
    dict(
        variable_id="trade_goods_balance_monthly",
        path="macrodata/trade/goods_balance_monthly_wide.parquet",
        description="Merchandise trade balance, monthly: exports FOB less imports CIF. Not the BPM6 balance (CIF imports include freight and insurance) — for that use capital_flows/imf_bop goods_net.",
        family="trade",
        frequency="monthly",
        source="IMF ITG (api.imf.org)",
        unit="USD",
        panel_columns="ISO3 country code",
    ),
    dict(
        variable_id="trade_goods_exports_annual",
        path="macrodata/trade/goods_exports_annual_wide.parquet",
        description="Merchandise exports FOB, annual, 1948-present; broader country coverage than the monthly file.",
        family="trade",
        frequency="annual",
        source="IMF ITG (api.imf.org)",
        unit="USD",
        panel_columns="ISO3 country code",
    ),
    dict(
        variable_id="trade_goods_imports_annual",
        path="macrodata/trade/goods_imports_annual_wide.parquet",
        description="Merchandise imports CIF, annual, 1948-present.",
        family="trade",
        frequency="annual",
        source="IMF ITG (api.imf.org)",
        unit="USD",
        panel_columns="ISO3 country code",
    ),
    dict(
        variable_id="trade_goods_balance_annual",
        path="macrodata/trade/goods_balance_annual_wide.parquet",
        description="Merchandise trade balance, annual: exports FOB less imports CIF (see trade_goods_balance_monthly on the CIF caveat).",
        family="trade",
        frequency="annual",
        source="IMF ITG (api.imf.org)",
        unit="USD",
        panel_columns="ISO3 country code",
    ),
    dict(
        variable_id="trade_goods_long",
        path="macrodata/trade/trade_goods_long.parquet",
        description="Country totals in long format: (date, iso3c, freq, indicator, value) with freq in {monthly, annual} and indicator in {exports_fob_usd, imports_cif_usd}.",
        family="trade",
        frequency="monthly+annual",
        source="IMF ITG (api.imf.org)",
        unit="USD",
        panel_columns="long: one series per (iso3c, freq, indicator)",
        series_by=["iso3c", "freq", "indicator"],
    ),
    dict(
        variable_id="trade_bilateral_long",
        path="macrodata/trade/bilateral_trade_long.parquet",
        description="Bilateral merchandise trade, annual: (year, reporter, partner, indicator, value), exports FOB and imports CIF. IMF IMTS, the successor to Direction of Trade Statistics. IMF aggregate codes (G001 world, GX*, TX*) are dropped; see trade_meta.csv.",
        family="trade",
        frequency="annual",
        source="IMF IMTS (api.imf.org)",
        unit="USD",
        panel_columns="long: one series per (reporter, partner, indicator)",
        series_by=["reporter", "partner", "indicator"],
    ),
    # ── Commodities ─────────────────────────────────────────────────────────
    dict(
        variable_id="commodities_metals",
        path="macrodata/commodities/metals_wide.parquet",
        description="Metals spot prices: gold (GOLDBLN), silver (SILVPM$ Perth Mint, from 2012; SLVCASH London fix, dead 2014), platinum (PLATFRE), palladium (PALLADM). Also LME aluminium (LAHCASH), aluminium alloy (LADCASH) and lead (LEDCASH).",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds)",
        unit="USD per troy oz (precious; SLVCASH in US cents per troy oz) / USD per metric ton (LME)",
        panel_columns="Datastream mnemonic",
    ),
    dict(
        variable_id="commodities_energy",
        path="macrodata/commodities/energy_wide.parquet",
        description="Energy commodity spot prices: Brent crude (OILBREN), Henry Hub gas (NATLGAS, dead 2020), heating oil (EIAHONY), gasoline (GSUNLRG).",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds)",
        unit="USD per barrel / USD per MMBTU / cents per gallon",
        panel_columns="Datastream mnemonic",
    ),
    dict(
        variable_id="commodities_agri",
        path="macrodata/commodities/agri_wide.parquet",
        description="Agricultural commodity spot prices: wheat (WHEATMP), corn (CORNUS2), soybeans (SOYBEAN), coffee (COFDICA), cocoa (COCINUS), sugar (WSUGDLY), cotton (COTTONM).",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds)",
        unit="USD per bushel (wheat, corn, soybeans) / cents per pound (coffee, sugar) / USD per pound (cotton) / USD per metric ton (cocoa)",
        panel_columns="Datastream mnemonic",
    ),
    dict(
        variable_id="commodities_indices",
        path="macrodata/commodities/indices_wide.parquet",
        description="S&P GSCI (spot/total-return/excess-return), GSCI sub-indices (non-energy, agriculture, precious metals; spot and total return), Refinitiv Equal Weight Commodity Index (NYFECRB, ex-CRB, dead 2021).",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds)",
        unit="index",
        panel_columns="Datastream mnemonic",
    ),
    dict(
        variable_id="oil_wti_spot_fred",
        path="macrodata/oil/fred_wti_spot.parquet",
        description="WTI crude oil spot price (Cushing, OK) from FRED (DCOILWTICO). Single series.",
        family="commodity",
        frequency="daily",
        source="FRED (DCOILWTICO)",
        unit="USD per barrel",
        panel_columns="single series",
    ),
    dict(
        variable_id="oil_wti_front_ds",
        path="macrodata/oil/ds_wti_front.parquet",
        description="WTI crude oil spot price, Cushing (Datastream CRUDOIL; not a futures series despite the file name). Single series, cross-check for FRED DCOILWTICO.",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds, mnemonic CRUDOIL)",
        unit="USD per barrel",
        panel_columns="single series",
    ),
    dict(
        variable_id="oil_wti_curve",
        path="macrodata/oil_curve/wti_wide.parquet",
        description="NYMEX WTI futures term structure: nearby contracts 1–12 built from individual contracts ranked by last trading date. Columns are nearby positions. WRDS stopped updating NWS contracts after 2026-04-03.",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_fut, prefix NWS)",
        unit="USD per barrel",
        panel_columns="nearby position F1..F12 (F1=front month, F2=next, …)",
    ),
    dict(
        variable_id="oil_brent_curve",
        path="macrodata/oil_curve/brent_wide.parquet",
        description="ICE Brent futures term structure: nearby contracts 1–12 built from individual contracts ranked by last trading date. Columns are nearby positions.",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_fut, prefix LLC)",
        unit="USD per barrel",
        panel_columns="nearby position F1..F12 (F1=front month, F2=next, …)",
    ),
    dict(
        variable_id="oil_wti_curve_metrics",
        path="macrodata/oil_curve/wti_metrics.parquet",
        description="WTI curve metrics: slope_12_1 = log(F12/F1)/11, slope_6_1 = log(F6/F1)/5 (log slope per month; negative = backwardation), spread_2_1 = F2-F1, spread_3_1 = F3-F1, basis = F1 - FRED spot.",
        family="commodity",
        frequency="daily",
        source="Derived from oil_wti_curve and FRED DCOILWTICO",
        unit="log slope per month (slopes) / USD per barrel (spreads, basis)",
        panel_columns="metric name",
        id_cols=("commodity",),
    ),
    dict(
        variable_id="oil_brent_curve_metrics",
        path="macrodata/oil_curve/brent_metrics.parquet",
        description="Brent curve metrics: slope_12_1, slope_6_1 (log slope per month), spread_2_1, spread_3_1. No basis column (no Brent spot series is used).",
        family="commodity",
        frequency="daily",
        source="Derived from oil_brent_curve",
        unit="log slope per month (slopes) / USD per barrel (spreads)",
        panel_columns="metric name",
        id_cols=("commodity",),
    ),
    dict(
        variable_id="oil_curve_long",
        path="macrodata/oil_curve/oil_curve_long.parquet",
        description="WTI and Brent futures curves stacked in long format: (date, commodity, tenor, price).",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_fut, prefixes NWS and LLC)",
        unit="USD per barrel",
        panel_columns="long: one series per (commodity, tenor)",
        series_by=["commodity", "tenor"],
    ),
    # ── Equity indices ───────────────────────────────────────────────────────
    dict(
        variable_id="equity_price_index",
        path="macrodata/equity_indices/equity_pi_wide.parquet",
        description="Country equity index price levels (pi_) for 47 countries. Columns are ISO2 codes mapped from Datastream index mnemonics (US=DJINDUS, JP=JAPDOWA, GB=FTATNOF, …; map in equity_meta.csv). BR is DJGL Brazil Financial Services, not IBOVESPA.",
        family="equity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2indexdata)",
        unit="index level in the index's own currency: local for most; USD for AT, BR, NG, RU, SG; JPY for CH, FR; EUR for DK, NO (equity_meta.csv isocurrcode)",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    dict(
        variable_id="equity_total_return",
        path="macrodata/equity_indices/equity_ri_wide.parquet",
        description="Country equity index total return (ri, dividends reinvested) for 33 countries. Same structure as equity_price_index.",
        family="equity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2indexdata)",
        unit="total return index in the index's own currency: local for most; USD for AT, BR, NG, RU, SG; JPY for CH, FR; EUR for DK, NO",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    dict(
        variable_id="msci_gross_total_return",
        path="macrodata/msci/msci_gross_tr_wide.parquet",
        description="MSCI Standard (large+mid cap) country index, gross total return, 45 countries (Russia excluded: index suspended 2022).",
        family="equity",
        frequency="monthly",
        source="MSCI public index-performance webapp (priceLevel=41, currency=USD)",
        unit="index level, USD",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    dict(
        variable_id="msci_price_return",
        path="macrodata/msci/msci_price_wide.parquet",
        description="MSCI Standard (large+mid cap) country index, price return, 45 countries (Russia excluded: index suspended 2022).",
        family="equity",
        frequency="monthly",
        source="MSCI public index-performance webapp (priceLevel=0, currency=USD)",
        unit="index level, USD",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    # ── FX ───────────────────────────────────────────────────────────────────
    dict(
        variable_id="fx_spot_vs_usd_by_country",
        path="macrodata/fx_spot/fx_spot_country_wide.parquet",
        description="FX spot rates vs USD for 202 countries (each currency mapped to every country using it, via config/currency_country.csv). Columns are ISO 3166-1 alpha-3 country codes. All currencies, majors included, are local currency per 1 USD. From Compustat exrt_dly via cross-rates through the anchor currency.",
        family="fx",
        frequency="daily",
        source="WRDS Compustat (comp.exrt_dly)",
        unit="local currency per USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="fx_spot_vs_usd_by_currency",
        path="macrodata/fx_spot/fx_spot_currency_wide.parquet",
        description="Same as fx_spot_vs_usd_by_country but columns are ISO 4217 currency codes (205, including legacy currencies).",
        family="fx",
        frequency="daily",
        source="WRDS Compustat (comp.exrt_dly)",
        unit="local currency per USD",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_spot_long",
        path="macrodata/fx_spot/fx_spot_long.parquet",
        description="Compustat FX spot rates in long format: (date, currency, exratd).",
        family="fx",
        frequency="daily",
        source="WRDS Compustat (comp.exrt_dly)",
        unit="local currency per USD",
        panel_columns="long: one series per currency",
        series_by=["currency"],
    ),
    # ── FX forward rates ─────────────────────────────────────────────────────
    dict(
        variable_id="fx_forward_long",
        path="macrodata/fx_forward/fx_forward_long.parquet",
        description="All Datastream FX forward and spot rates vs USD in long format: (date, currency, tenor, rate). 58 tenors, 173 currencies. Units: USD per 1 unit of currency (inverse of fx_spot).",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxcode + ds2fxrate)",
        unit="USD per unit of currency",
        panel_columns="long: one series per (currency, tenor)",
        series_by=["currency", "tenor"],
    ),
    dict(
        variable_id="fx_spot_ds",
        path="macrodata/fx_forward/by_tenor/SPOT_wide.parquet",
        description="FX spot rates from Datastream (ds2fxrate ratetypecode=SPOT), 173 currencies vs USD. Longer history than Compustat spot for some EM currencies.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, SPOT)",
        unit="USD per unit of currency",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_1m",
        path="macrodata/fx_forward/by_tenor/1MFD_wide.parquet",
        description="FX 1-month forward rates vs USD (Datastream ratetypecode=1MFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 1MFD)",
        unit="USD per unit of currency",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_3m",
        path="macrodata/fx_forward/by_tenor/3MFD_wide.parquet",
        description="FX 3-month forward rates vs USD (Datastream ratetypecode=3MFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 3MFD)",
        unit="USD per unit of currency",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_6m",
        path="macrodata/fx_forward/by_tenor/6MFD_wide.parquet",
        description="FX 6-month forward rates vs USD (Datastream ratetypecode=6MFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 6MFD)",
        unit="USD per unit of currency",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_1y",
        path="macrodata/fx_forward/by_tenor/1YFD_wide.parquet",
        description="FX 1-year forward rates vs USD (Datastream ratetypecode=1YFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 1YFD)",
        unit="USD per unit of currency",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_2y",
        path="macrodata/fx_forward/by_tenor/2YFD_wide.parquet",
        description="FX 2-year forward rates vs USD (Datastream ratetypecode=2YFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 2YFD)",
        unit="USD per unit of currency",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_5y",
        path="macrodata/fx_forward/by_tenor/5YFD_wide.parquet",
        description="FX 5-year forward rates vs USD (Datastream ratetypecode=5YFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 5YFD)",
        unit="USD per unit of currency",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="bis_reer",
        path="macrodata/bis_eer/reer_wide.parquet",
        description="BIS real (CPI-based) effective exchange rates, broad basket, 64 economies, 1994–present.",
        family="fx",
        frequency="monthly",
        source="BIS Statistics API (WS_EER, key M.R.B.)",
        unit="index (2020=100)",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    dict(
        variable_id="bis_neer",
        path="macrodata/bis_eer/neer_wide.parquet",
        description="BIS nominal effective exchange rates, narrow basket, 26 economies, 1964–present.",
        family="fx",
        frequency="monthly",
        source="BIS Statistics API (WS_EER, key M.N.N.)",
        unit="index (2020=100)",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    # ── CFTC FX positioning ──────────────────────────────────────────────────
    *[
        dict(
            variable_id=f"cftc_{report}_{sector}_net",
            path=f"macrodata/cftc_fx/{report}_{sector}_net_wide.parquet",
            description=f"CFTC Commitments of Traders ({label}): net futures position (long - short, spreading excluded) of {who} in CME currency futures. Positions as of Tuesday.",
            family="fx",
            frequency="weekly",
            source=src,
            unit="contracts (net)",
            panel_columns="ISO currency code (EURGBP/EURJPY for crosses)",
        )
        for report, label, src, sectors in [
            ("tff", "Traders in Financial Futures, 2006–", "CFTC Socrata API (TFF, gpe5-46if)",
             [("dealer", "dealers/intermediaries"), ("asset_mgr", "asset managers"),
              ("lev_money", "leveraged funds"), ("other_rept", "other reportables"),
              ("nonrept", "non-reportables")]),
            ("legacy", "legacy report, 1986–", "CFTC Socrata API (legacy, 6dca-aqww)",
             [("noncomm", "non-commercials"), ("comm", "commercials"),
              ("nonrept", "non-reportables")]),
        ]
        for sector, who in sectors
    ],
    dict(
        variable_id="cftc_tff_open_interest",
        path="macrodata/cftc_fx/tff_open_interest_wide.parquet",
        description="CFTC open interest in CME currency futures, TFF report (2006–).",
        family="fx",
        frequency="weekly",
        source="CFTC Socrata API (TFF, gpe5-46if)",
        unit="contracts",
        panel_columns="ISO currency code (EURGBP/EURJPY for crosses)",
    ),
    dict(
        variable_id="cftc_legacy_open_interest",
        path="macrodata/cftc_fx/legacy_open_interest_wide.parquet",
        description="CFTC open interest in CME currency futures, legacy report (1986–; pre-1999 ECU rows dropped from EUR).",
        family="fx",
        frequency="weekly",
        source="CFTC Socrata API (legacy, 6dca-aqww)",
        unit="contracts",
        panel_columns="ISO currency code",
    ),
    dict(
        variable_id="cftc_fx_long",
        path="macrodata/cftc_fx/cftc_fx_long.parquet",
        description="CFTC FX positioning, all fields from both reports stacked (long/short/spreading by trader category, open interest, nets); report column = tff/legacy.",
        family="fx",
        frequency="weekly",
        source="CFTC Socrata API (TFF gpe5-46if + legacy 6dca-aqww)",
        unit="contracts",
        panel_columns="long: one series per (report, contract_code)",
        series_by=["report", "contract_code"],
    ),
    # ── Interest rates ───────────────────────────────────────────────────────
    dict(
        variable_id="cbpol_central_bank_rate",
        path="macrodata/interest_rates/cbpol_wide.parquet",
        description="Central bank policy rates, daily, 49 columns: 48 countries + XM (euro area); 38 still reporting in 2026 (10 pre-euro national rates end 1998–2022; AR ends 2025-07). GB, FR, IT, JP, NL, CH, DK, ES, PT, BE, AT, IN, SE from 1946, DE 1948, US 1954, CA 1960; most EM from the late 1980s–2000s.",
        family="rates",
        frequency="daily",
        source="BIS Statistics API (WS_CBPOL)",
        unit="percent per annum",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    dict(
        variable_id="bond_yield_10y",
        path="macrodata/interest_rates/bond_yield_10y_wide.parquet",
        description="Government bond yields, monthly, 41 countries; 10-year benchmark except KR (3-year), BE (6-years-and-over) and MX (UDIBONO, inflation-linked). DE, GB, IE, PT and GR end 2019-09. End-of-period unless noted in config/datasets.yaml.",
        family="rates",
        frequency="monthly",
        source="WRDS Datastream (tr_ds_econ.ecodata)",
        unit="percent per annum",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    # ── Volatility ───────────────────────────────────────────────────────────
    dict(
        variable_id="volatility_vix",
        path="macrodata/vol/vol_daily.parquet",
        description="Volatility indices: VIX (30-day implied vol on S&P 500) and VIX3M (formerly VXV, 3-month). Wide format, columns vix and vix3m.",
        family="vol",
        frequency="daily",
        source="FRED (VIXCLS, VXVCLS)",
        unit="annualised percent",
        panel_columns="index name",
    ),
    # ── Inflation ────────────────────────────────────────────────────────────
    dict(
        variable_id="wb_cpi_level",
        path="macrodata/inflation/wb_cpi_wide.parquet",
        description="Consumer price index level (2010=100) from World Bank for ~192 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (FP.CPI.TOTL)",
        unit="index (2010=100)",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_inflation_rate",
        path="macrodata/inflation/wb_inflation_wide.parquet",
        description="Annual CPI inflation rate (%) from World Bank for ~193 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (FP.CPI.TOTL.ZG)",
        unit="percent per year",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="cpi_monthly_index",
        path="macrodata/cpi_monthly/cpi_index_wide.parquet",
        description="Monthly CPI index levels (IMF IFS line 64, consumer prices all items) for 164 countries. Columns are Datastream mnemonics {CC}I64...F; country names in cpi_meta.csv. Base year varies by country.",
        family="macro",
        frequency="monthly",
        source="WRDS Datastream (tr_ds_econ; IMF IFS)",
        unit="index (base year varies by country)",
        panel_columns="Datastream mnemonic ({CC}I64...F)",
    ),
    dict(
        variable_id="cpi_monthly_yoy",
        path="macrodata/cpi_monthly/cpi_yoy_wide.parquet",
        description="Monthly CPI inflation, year-over-year % change of cpi_monthly_index (pct_change(12) * 100), 164 countries.",
        family="macro",
        frequency="monthly",
        source="Derived from cpi_monthly_index",
        unit="percent (year over year)",
        panel_columns="Datastream mnemonic ({CC}I64...F)",
    ),
    # ── World Bank macro ─────────────────────────────────────────────────────
    dict(
        variable_id="wb_gdp_usd",
        path="macrodata/macro/wide/wb_gdp_usd.parquet",
        description="GDP in current USD for ~214 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NY.GDP.MKTP.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_gdp_growth",
        path="macrodata/macro/wide/wb_gdp_growth.parquet",
        description="Real GDP growth rate (%) for ~214 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NY.GDP.MKTP.KD.ZG)",
        unit="percent per year",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_gdp_per_capita",
        path="macrodata/macro/wide/wb_gdp_pcap_usd.parquet",
        description="GDP per capita in current USD for ~214 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NY.GDP.PCAP.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_household_consumption",
        path="macrodata/macro/wide/wb_consumption_hh.parquet",
        description="Household final consumption expenditure (current USD) for ~190 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.CON.PRVT.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_govt_consumption",
        path="macrodata/macro/wide/wb_consumption_govt.parquet",
        description="Government final consumption expenditure (current USD) for ~188 countries. This is the G in C+I+G+NX, NOT fiscal revenue/expenditure.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.CON.GOVT.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_investment",
        path="macrodata/macro/wide/wb_investment.parquet",
        description="Gross fixed capital formation (current USD) for ~181 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.GDI.FTOT.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_exports",
        path="macrodata/macro/wide/wb_exports.parquet",
        description="Exports of goods and services (current USD) for ~194 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.EXP.GNFS.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_imports",
        path="macrodata/macro/wide/wb_imports.parquet",
        description="Imports of goods and services (current USD) for ~194 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.IMP.GNFS.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_current_account",
        path="macrodata/macro/wide/wb_current_account.parquet",
        description="Current account balance (current USD) for ~200 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (BN.CAB.XOKA.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_fdi_inflows",
        path="macrodata/macro/wide/wb_fdi_inflows.parquet",
        description="Foreign direct investment net inflows (current USD) for ~204 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (BX.KLT.DINV.CD.WD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_fdi_outflows",
        path="macrodata/macro/wide/wb_fdi_outflows.parquet",
        description="Foreign direct investment net outflows (current USD) for ~198 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (BM.KLT.DINV.CD.WD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_portfolio_equity_flows",
        path="macrodata/macro/wide/wb_portfolio_equity.parquet",
        description="Portfolio equity net inflows (current USD) for ~186 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (BX.PEF.TOTL.CD.WD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_macro_panel",
        path="macrodata/macro/panel/macro_panel_wide.parquet",
        description="Country-year panel of the 12 World Bank macro indicators above (gdp_usd, gdp_growth_pct, …, portfolio_equity_usd), one column each.",
        family="macro",
        frequency="annual",
        source="World Bank (indicators as in the wb_* rows)",
        unit="current USD (gdp_growth_pct: percent)",
        panel_columns="panel: rows (year, iso3c, iso2c, country_name) × indicator columns; n_series = countries",
        series_by=["iso3c"],
    ),
    # ── IMF WEO ─────────────────────────────────────────────────────────────
    dict(
        variable_id="weo_gdp_usd",
        path="macrodata/imf_weo/weo_ngdpd_wide.parquet",
        description="GDP in current USD (billions) from IMF WEO, 196 countries, 1980–2029 (incl. projections).",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (NGDPD)",
        unit="billions of current USD",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_gdp_growth",
        path="macrodata/imf_weo/weo_ngdp_rpch_wide.parquet",
        description="Real GDP growth rate (%) from IMF WEO, 196 countries.",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (NGDP_RPCH)",
        unit="percent per year",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_inflation",
        path="macrodata/imf_weo/weo_pcpipch_wide.parquet",
        description="CPI inflation rate (%, average consumer prices) from IMF WEO, 196 countries.",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (PCPIPCH)",
        unit="percent per year",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_current_account_pct_gdp",
        path="macrodata/imf_weo/weo_bca_ngdpd_wide.parquet",
        description="Current account balance (% of GDP) from IMF WEO, 195 countries.",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (BCA_NGDPD)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_unemployment",
        path="macrodata/imf_weo/weo_lur_wide.parquet",
        description="Unemployment rate (%) from IMF WEO, 114 countries.",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (LUR)",
        unit="percent of labor force",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_revenue_pct_gdp",
        path="macrodata/imf_weo/weo_ggr_ngdp_wide.parquet",
        description="General government revenue (% of GDP) from IMF WEO, 196 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGR_NGDP)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_expenditure_pct_gdp",
        path="macrodata/imf_weo/weo_ggx_ngdp_wide.parquet",
        description="General government total expenditure (% of GDP) from IMF WEO, 196 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGX_NGDP)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_fiscal_balance_pct_gdp",
        path="macrodata/imf_weo/weo_ggxcnl_ngdp_wide.parquet",
        description="General government net lending/borrowing = fiscal balance (% of GDP) from IMF WEO, 196 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXCNL_NGDP)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_primary_balance_pct_gdp",
        path="macrodata/imf_weo/weo_ggxonlb_ngdp_wide.parquet",
        description="General government primary net lending/borrowing (% of GDP) from IMF WEO, 188 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXONLB_NGDP)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_debt_gross_pct_gdp",
        path="macrodata/imf_weo/weo_ggxwdg_ngdp_wide.parquet",
        description="General government gross debt (% of GDP) from IMF WEO, 194 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXWDG_NGDP)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_debt_net_pct_gdp",
        path="macrodata/imf_weo/weo_ggxwdn_ngdp_wide.parquet",
        description="General government net debt (% of GDP) from IMF WEO, 91 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXWDN_NGDP)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_fiscal_balance_lcu",
        path="macrodata/imf_weo/weo_ggxcnl_wide.parquet",
        description="General government net lending/borrowing in levels, national currency (not comparable across countries), IMF WEO, 196 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXCNL)",
        unit="national currency, billions",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_primary_balance_lcu",
        path="macrodata/imf_weo/weo_ggxonlb_wide.parquet",
        description="General government primary net lending/borrowing in levels, national currency, IMF WEO, 188 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXONLB)",
        unit="national currency, billions",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_debt_gross_lcu",
        path="macrodata/imf_weo/weo_ggxwdg_wide.parquet",
        description="General government gross debt in levels, national currency, IMF WEO, 194 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXWDG)",
        unit="national currency, billions",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_debt_net_lcu",
        path="macrodata/imf_weo/weo_ggxwdn_wide.parquet",
        description="General government net debt in levels, national currency, IMF WEO, 91 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXWDN)",
        unit="national currency, billions",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_long",
        path="macrodata/imf_weo/weo_long.parquet",
        description="All 15 WEO subjects in long format: (date, country, subject_code, subject_descriptor, units, value).",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024",
        unit="varies by subject (units column)",
        panel_columns="long: one series per (country, subject_code)",
        series_by=["country", "subject_code"],
    ),
    # ── External accounts: quarterly BOP (IMF IFS via Datastream) ────────────
    *[
        dict(
            variable_id=f"bop_q_{label}",
            path=f"macrodata/bop_quarterly/{label}_wide.parquet",
            description=f"Quarterly balance of payments: {desc} (IMF IFS via Datastream, mnemonic {{CC}}I{suffix}). BPM6 signs: financial-account assets/liabilities positive = net acquisition/incurrence.",
            family="external",
            frequency="quarterly",
            source="WRDS Datastream (tr_ds_econ; IMF IFS BOP)",
            unit="USD millions (typical; units not stored, see tr_ds_econ.wrds_ecoinfo)",
            panel_columns="country name (Datastream prefix; see bop_meta.csv)",
        )
        for label, suffix, desc in [
            ("ca",                "109BXF", "current account balance"),
            ("goods_balance",     "1A9BXF", "goods balance"),
            ("capital_account",   "209BAA", "capital account balance"),
            ("financial_account", "309NAA", "financial account balance"),
            ("fdi_assets",        "3A9AAA", "direct investment, assets"),
            ("fdi_liabs",         "3A9LAA", "direct investment, liabilities"),
            ("portfolio_assets",  "3B9AAA", "portfolio investment, assets"),
            ("portfolio_liabs",   "3B9LAA", "portfolio investment, liabilities"),
            ("other_inv_assets",  "3D9AAA", "other investment, assets"),
            ("other_inv_liabs",   "3D9LAA", "other investment, liabilities"),
            ("reserve_assets",    "3E9AAA", "reserve assets"),
        ]
    ],
    # ── External accounts: annual BOP/IIP panel (IMF) ────────────────────────
    dict(
        variable_id="capital_flows_panel",
        path="macrodata/capital_flows/panel/capital_flows_wide.parquet",
        description="IMF BOP flows (dataset=bop_flow) and IIP stocks (dataset=iip_stock) by functional category: FDI, portfolio equity/debt, other investment, reserves (assets/liabilities/net), plus CA/KA/FA balances and NIIP. One column per indicator; per-indicator year × country files in macrodata/capital_flows/wide/.",
        family="external",
        frequency="annual",
        source="IMF BOP + IIP (api.imf.org, BPM6)",
        unit="USD",
        panel_columns="panel: rows (year, iso3c, dataset) × 34 indicator columns; n_series = countries",
        series_by=["iso3c"],
    ),
    dict(
        variable_id="capital_flows_long",
        path="macrodata/capital_flows/panel/capital_flows_long.parquet",
        description="Same data as capital_flows_panel in long format: (year, iso3c, indicator, value, dataset).",
        family="external",
        frequency="annual",
        source="IMF BOP + IIP (api.imf.org, BPM6)",
        unit="USD",
        panel_columns="long: one series per (iso3c, indicator)",
        series_by=["iso3c", "indicator"],
    ),
    dict(
        variable_id="bilateral_portfolio_positions",
        path="macrodata/bilateral/cpis_long.parquet",
        description="IMF Portfolio Investment Positions by counterpart economy (formerly CPIS): holdings of reporter in securities issued by counterpart; total, equity, debt, long-/short-term debt. 94 reporters; counterpart G001 = world.",
        family="external",
        frequency="annual",
        source="IMF PIP (api.imf.org)",
        unit="USD",
        panel_columns="long: one series per (reporter, counterpart, indicator)",
        series_by=["reporter", "counterpart", "indicator"],
    ),
    dict(
        variable_id="bilateral_fdi_positions",
        path="macrodata/bilateral/cdis_long.parquet",
        description="IMF Direct Investment Positions by counterpart economy (formerly CDIS): inward/outward FDI positions (total, equity, debt), directional principle. 143 reporters.",
        family="external",
        frequency="annual",
        source="IMF DIP (api.imf.org)",
        unit="USD",
        panel_columns="long: one series per (reporter, counterpart, indicator)",
        series_by=["reporter", "counterpart", "indicator"],
    ),
    # ── BIS ─────────────────────────────────────────────────────────────────
    dict(
        variable_id="bis_intl_debt_by_nationality",
        path="macrodata/bis_debt_sec/bis_debt_sec_by_nat_wide.parquet",
        description="BIS international debt securities, amounts outstanding, by issuer nationality (issuer_res=3P 'all countries excluding residents', issuer_nat=country); all maturities, all-sector, all-currency totals. 155 countries, quarterly, 1993-Q1–present.",
        family="fiscal",
        frequency="quarterly",
        source="BIS Statistics API (WS_DEBT_SEC2_PUB, MEASURE=I)",
        unit="USD millions",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    dict(
        variable_id="bis_intl_debt_by_residence",
        path="macrodata/bis_debt_sec/bis_debt_sec_by_res_wide.parquet",
        description="BIS international debt securities, amounts outstanding, by issuer residence (issuer_res=country, issuer_nat=3P); all maturities, all-sector, all-currency totals. 158 countries, quarterly, 1993-Q1–present.",
        family="fiscal",
        frequency="quarterly",
        source="BIS Statistics API (WS_DEBT_SEC2_PUB, MEASURE=I)",
        unit="USD millions",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    # ── BIS LBS ──────────────────────────────────────────────────────────────
    dict(
        variable_id="bis_lbs_crossborder_claims",
        path="macrodata/bis_lbs/bis_lbs_wide.parquet",
        description="BIS Locational Banking Statistics: total cross-border claims of reporting banking systems on all counterparties (USD millions). 48 reporting countries, quarterly, 2000–present.",
        family="macro",
        frequency="quarterly",
        source="BIS Statistics API (WS_LBS_D_PUB, key Q.S.C.A.TO1.A.5J.A)",
        unit="USD millions",
        panel_columns="ISO 3166-1 alpha-2 country code (reporting banking system)",
    ),
    # ── TIC ─────────────────────────────────────────────────────────────────
    dict(
        variable_id="tic_foreign_holders",
        path="macrodata/tic/tic_holdings_wide.parquet",
        description="Foreign holdings of US Treasury securities (billions USD). 53 columns: countries plus the groupings 'Oil Exporters' and 'Carib Bnkng Ctrs'; 19–45 holders listed per month. Monthly, 2000-03–present.",
        family="monetary",
        frequency="monthly",
        source="US Treasury TIC (mfhhis01.txt + slt_table5.txt)",
        unit="billions of USD",
        panel_columns="country name",
    ),
    # ── Sovereign debt (World Bank IDS) ──────────────────────────────────────
    dict(
        variable_id="sovereign_debt_panel",
        path="macrodata/sovereign_debt/ids_panel.parquet",
        description="Country-year panel of PPG external debt, debt service and arrears, GDP, and partial default (arrears / (arrears + PPG debt service); in_default = partial_default > 1%), after Arellano, Mateos-Planas & Ríos-Rull (JPE 2023). Countries IDS no longer covers are filled from WDI and WDI archive vintages (data_source column).",
        family="fiscal",
        frequency="annual",
        source="World Bank IDS (source 6) + WDI (source 2) + WDI archives (source 57)",
        unit="current USD (levels); ratios (partial_default, *_gdp)",
        panel_columns="panel: rows (iso3c, year) × variable columns; n_series = countries",
        series_by=["iso3c"],
    ),
    dict(
        variable_id="sovereign_debt_ids_long",
        path="macrodata/sovereign_debt/ids_long.parquet",
        description="Every pulled World Bank IDS series in long format, actual years only (projections dropped); includes aggregates (is_aggregate).",
        family="fiscal",
        frequency="annual",
        source="World Bank IDS (source 6)",
        unit="current USD",
        panel_columns="long: one series per (iso3c, series)",
        series_by=["iso3c", "series"],
    ),
    dict(
        variable_id="partial_default",
        path="macrodata/sovereign_debt/partial_default_wide.parquet",
        description="Partial default rate = PPG arrears / (arrears + PPG debt service), 0 when no arrears; year × country.",
        family="fiscal",
        frequency="annual",
        source="Derived from World Bank IDS / WDI (see sovereign_debt_panel)",
        unit="ratio (0–1)",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
]


def read_parquet_stats(path: Path, series_by: list[str] | None = None,
                       id_cols: tuple[str, ...] = ()) -> dict:
    """Read date range and series count from a parquet file (see module docstring)."""
    try:
        import pyarrow.parquet as pq
        schema = pq.read_schema(path)
        # Get column names excluding the date index / date column and identifiers
        all_cols = schema.names
        data_cols = [c for c in all_cols
                     if c not in ("date", "year", "__null_dask_index__", "index") and c not in id_cols]

        # Read just enough to get date range
        df = pd.read_parquet(path)
        idx = df.index
        if "datetime" in str(idx.dtype):
            dates = pd.to_datetime(idx)
        elif idx.name in ("date", "year") and "datetime" not in str(idx.dtype):
            # Named index that looks like years (e.g. 1980, 1981...)
            try:
                dates = pd.to_datetime(idx.astype(int).astype(str) + "-01-01", format="%Y-%m-%d")
            except Exception:
                dates = pd.Series(dtype="datetime64[ns]")
        else:
            # Look for a date-like column
            if "date" in df.columns or "date_" in df.columns:
                col = "date" if "date" in df.columns else "date_"
                try:
                    dates = pd.to_datetime(df[col])
                except Exception:
                    dates = pd.Series(dtype="datetime64[ns]")
            elif "year" in df.columns:
                # Integer year column (World Bank style): 1960, 1961, ...
                try:
                    dates = pd.to_datetime(df["year"].astype(str) + "-01-01", format="%Y-%m-%d")
                except Exception:
                    dates = pd.Series(dtype="datetime64[ns]")
            else:
                dates = pd.Series(dtype="datetime64[ns]")

        # Long/panel files: count distinct series keys, not columns
        n_series = len(df[series_by].drop_duplicates()) if series_by else len(data_cols)

        return {
            "n_series":  n_series,
            "date_min":  str(dates.min().date()) if not dates.empty else None,
            "date_max":  str(dates.max().date()) if not dates.empty else None,
        }
    except Exception as e:
        return {"n_series": None, "date_min": None, "date_max": None, "error": str(e)}


def main() -> None:
    rows = []
    for entry in CATALOG:
        path_rel = entry["path"]
        path_abs  = ROOT / path_rel

        stats = read_parquet_stats(
            path_abs, entry.get("series_by"), entry.get("id_cols", ())
        ) if path_abs.exists() else {
            "n_series": None, "date_min": None, "date_max": None,
        }
        if "error" in stats:
            print(f"    ERROR reading {path_rel}: {stats['error']}")

        rows.append({
            "variable_id":   entry["variable_id"],
            "path":          path_rel,
            "description":   entry["description"],
            "family":        entry["family"],
            "frequency":     entry["frequency"],
            "source":        entry["source"],
            "unit":          entry["unit"],
            "panel_columns": entry["panel_columns"],
            "n_series":      stats.get("n_series"),
            "date_min":      stats.get("date_min"),
            "date_max":      stats.get("date_max"),
            "file_exists":   path_abs.exists(),
        })

    df = pd.DataFrame(rows)
    out = ROOT / "variables.csv"
    df.to_csv(out, index=False)

    missing = df[~df["file_exists"]]
    print(f"Wrote {len(df)} rows to {out}")
    print(f"  {len(df) - len(missing)} files present, {len(missing)} missing (not yet pulled)")
    if len(missing):
        for _, r in missing.iterrows():
            print(f"    MISSING: {r['path']}")

    print("\nSummary by family:")
    print(df.groupby("family")[["variable_id"]].count().rename(columns={"variable_id":"count"}).to_string())


if __name__ == "__main__":
    main()
