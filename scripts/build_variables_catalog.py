"""
Generate variables.csv in the repo root.

One row per output parquet file. Auto-reads date range and column count from each
file; human-curated descriptions and metadata are defined in CATALOG below.

Usage:
    python scripts/build_variables_catalog.py
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Hand-curated catalog entries
# Keys are paths relative to the repo root.
# ---------------------------------------------------------------------------
CATALOG: list[dict] = [
    # ── Commodities ─────────────────────────────────────────────────────────
    dict(
        variable_id="commodities_metals",
        path="output/commodities/metals_wide.parquet",
        description="Precious metals spot prices: gold (GOLDBLN), silver (SILVPM$), platinum (PLATFRE), palladium (PALLADM). Also LME aluminium (LAHCASH, LADCASH) and lead (LEDCASH).",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds)",
        unit="USD per troy oz (precious) / USD per metric ton (LME)",
        panel_columns="Datastream mnemonic",
    ),
    dict(
        variable_id="commodities_energy",
        path="output/commodities/energy_wide.parquet",
        description="Energy commodity spot prices: Brent crude (OILBREN), Henry Hub gas (NATLGAS, dead 2020), heating oil (EIAHONY), gasoline (GSUNLRG).",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds)",
        unit="USD per barrel / USD per MMBTU / cents per gallon",
        panel_columns="Datastream mnemonic",
    ),
    dict(
        variable_id="commodities_agri",
        path="output/commodities/agri_wide.parquet",
        description="Agricultural commodity spot prices: wheat (WHEATMP), corn (CORNUS2), soybeans (SOYBEAN), coffee (COFDICA), cocoa (COCINUS), sugar (WSUGDLY), cotton (COTTONM).",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds)",
        unit="USD per bushel / cents per pound / USD per metric ton",
        panel_columns="Datastream mnemonic",
    ),
    dict(
        variable_id="commodities_indices",
        path="output/commodities/indices_wide.parquet",
        description="S&P GSCI (spot/total-return/excess-return), GSCI sub-indices (energy, non-energy, agriculture, precious metals), Refinitiv CRB (dead 2021).",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds)",
        unit="index",
        panel_columns="Datastream mnemonic",
    ),
    dict(
        variable_id="oil_wti_spot_fred",
        path="output/oil/fred_wti_spot.parquet",
        description="WTI crude oil spot price (Cushing, OK) from FRED (DCOILWTICO). Single series.",
        family="commodity",
        frequency="daily",
        source="FRED (DCOILWTICO)",
        unit="USD per barrel",
        panel_columns="single series",
    ),
    dict(
        variable_id="oil_wti_front_ds",
        path="output/oil/ds_wti_front.parquet",
        description="NYMEX WTI front-month continuous series (CRUDOIL) from Datastream. Single series.",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_comds, mnemonic CRUDOIL)",
        unit="USD per barrel",
        panel_columns="single series",
    ),
    dict(
        variable_id="oil_wti_curve",
        path="output/oil_curve/wti_wide.parquet",
        description="NYMEX WTI futures term structure: nearby contracts 1–12 built from individual contracts ranked by last trading date. Columns are nearby positions.",
        family="commodity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_fut, prefix NWS)",
        unit="USD per barrel",
        panel_columns="nearby position (1=front month, 2=next, …)",
    ),
    # ── Equity indices ───────────────────────────────────────────────────────
    dict(
        variable_id="equity_price_index",
        path="output/equity_indices/equity_pi_wide.parquet",
        description="Country equity index price levels (pi_) for ~47 countries. Columns are Datastream index mnemonics (DJINDUS=US, JAPDOWA=Japan, FTSEALL=UK, etc.).",
        family="equity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2indexdata)",
        unit="local currency index",
        panel_columns="Datastream index mnemonic",
    ),
    dict(
        variable_id="equity_total_return",
        path="output/equity_indices/equity_ri_wide.parquet",
        description="Country equity index total return (ri_, dividends reinvested) for ~33 countries. Same structure as equity_price_index.",
        family="equity",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2indexdata)",
        unit="local currency total return index",
        panel_columns="Datastream index mnemonic",
    ),
    # ── FX ───────────────────────────────────────────────────────────────────
    dict(
        variable_id="fx_spot_vs_usd_by_country",
        path="output/fx_spot/fx_spot_country_wide.parquet",
        description="FX spot rates vs USD for ~197 countries. Columns are ISO 3166-1 alpha-3 country codes. Direction: local currency per 1 USD (except EUR/GBP/AUD/NZD which are USD per 1 unit). From Compustat exrt_dly.",
        family="fx",
        frequency="daily",
        source="WRDS Compustat (comp.exrt_dly)",
        unit="local currency per USD (or USD per local for majors)",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="fx_spot_vs_usd_by_currency",
        path="output/fx_spot/fx_spot_currency_wide.parquet",
        description="Same as fx_spot_vs_usd_by_country but columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Compustat (comp.exrt_dly)",
        unit="local currency per USD (or USD per local for majors)",
        panel_columns="ISO 4217 currency code",
    ),
    # ── FX forward rates ─────────────────────────────────────────────────────
    dict(
        variable_id="fx_forward_long",
        path="output/fx_forward/fx_forward_long.parquet",
        description="All FX forward and spot rates in long format: (date, currency, tenor, rate). 58 tenors from Datastream, 173 currencies. Units: local currency per 1 USD.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxcode + ds2fxrate)",
        unit="local currency per USD",
        panel_columns="ISO 4217 currency code × tenor (ratetypecode)",
    ),
    dict(
        variable_id="fx_spot_ds",
        path="output/fx_forward/by_tenor/SPOT_wide.parquet",
        description="FX spot rates from Datastream (ds2fxrate ratetypecode=SPOT), 173 currencies vs USD. Longer history than Compustat spot for some EM currencies.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, SPOT)",
        unit="local currency per USD",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_1m",
        path="output/fx_forward/by_tenor/1MFD_wide.parquet",
        description="FX 1-month forward rates vs USD (Datastream ratetypecode=1MFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 1MFD)",
        unit="local currency per USD",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_3m",
        path="output/fx_forward/by_tenor/3MFD_wide.parquet",
        description="FX 3-month forward rates vs USD (Datastream ratetypecode=3MFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 3MFD)",
        unit="local currency per USD",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_6m",
        path="output/fx_forward/by_tenor/6MFD_wide.parquet",
        description="FX 6-month forward rates vs USD (Datastream ratetypecode=6MFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 6MFD)",
        unit="local currency per USD",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_1y",
        path="output/fx_forward/by_tenor/1YFD_wide.parquet",
        description="FX 1-year forward rates vs USD (Datastream ratetypecode=1YFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 1YFD)",
        unit="local currency per USD",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_2y",
        path="output/fx_forward/by_tenor/2YFD_wide.parquet",
        description="FX 2-year forward rates vs USD (Datastream ratetypecode=2YFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 2YFD)",
        unit="local currency per USD",
        panel_columns="ISO 4217 currency code",
    ),
    dict(
        variable_id="fx_forward_5y",
        path="output/fx_forward/by_tenor/5YFD_wide.parquet",
        description="FX 5-year forward rates vs USD (Datastream ratetypecode=5YFD). Columns are ISO 4217 currency codes.",
        family="fx",
        frequency="daily",
        source="WRDS Datastream (tr_ds_equities.ds2fxrate, 5YFD)",
        unit="local currency per USD",
        panel_columns="ISO 4217 currency code",
    ),
    # ── Interest rates ───────────────────────────────────────────────────────
    dict(
        variable_id="cbpol_central_bank_rate",
        path="output/interest_rates/cbpol_wide.parquet",
        description="Central bank policy rates, daily, 39–49 countries. Columns are ISO 3166-1 alpha-2 country codes (XM = Eurozone). US from 1954, G10 from 1970s–1980s, EM from 1990s–2000s.",
        family="rates",
        frequency="daily",
        source="BIS Statistics API (WS_CBPOL)",
        unit="percent per annum",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    dict(
        variable_id="bond_yield_10y",
        path="output/interest_rates/bond_yield_10y_wide.parquet",
        description="10-year government bond yields, monthly, 41 countries. Columns are ISO 3166-1 alpha-2 country codes. Mostly end-of-period benchmark yields from national sources via Datastream.",
        family="rates",
        frequency="monthly",
        source="WRDS Datastream (tr_ds_econ.ecodata)",
        unit="percent per annum",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    # ── Volatility ───────────────────────────────────────────────────────────
    dict(
        variable_id="volatility_vix",
        path="output/vol/vol_daily.parquet",
        description="Volatility indices: VIX (1-month implied vol on S&P 500), VXV (3-month). Wide format, one column per index.",
        family="vol",
        frequency="daily",
        source="FRED (VIXCLS, VXVCLS)",
        unit="annualised percent",
        panel_columns="index name",
    ),
    # ── Inflation ────────────────────────────────────────────────────────────
    dict(
        variable_id="wb_cpi_level",
        path="output/inflation/wb_cpi_wide.parquet",
        description="Consumer price index level (2010=100) from World Bank for ~192 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (FP.CPI.TOTL)",
        unit="index (2010=100)",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_inflation_rate",
        path="output/inflation/wb_inflation_wide.parquet",
        description="Annual CPI inflation rate (%) from World Bank for ~193 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (FP.CPI.TOTL.ZG)",
        unit="percent per year",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    # ── World Bank macro ─────────────────────────────────────────────────────
    dict(
        variable_id="wb_gdp_usd",
        path="output/macro/wide/wb_gdp_usd.parquet",
        description="GDP in current USD for ~214 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NY.GDP.MKTP.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_gdp_growth",
        path="output/macro/wide/wb_gdp_growth.parquet",
        description="Real GDP growth rate (%) for ~214 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NY.GDP.MKTP.KD.ZG)",
        unit="percent per year",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_gdp_per_capita",
        path="output/macro/wide/wb_gdp_pcap_usd.parquet",
        description="GDP per capita in current USD for ~214 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NY.GDP.PCAP.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_household_consumption",
        path="output/macro/wide/wb_consumption_hh.parquet",
        description="Household final consumption expenditure (current USD) for ~188 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.CON.PRVT.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_govt_consumption",
        path="output/macro/wide/wb_consumption_govt.parquet",
        description="Government final consumption expenditure (current USD) for ~186 countries. This is the G in C+I+G+NX, NOT fiscal revenue/expenditure.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.CON.GOVT.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_investment",
        path="output/macro/wide/wb_investment.parquet",
        description="Gross fixed capital formation (current USD) for ~179 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.GDI.FTOT.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_exports",
        path="output/macro/wide/wb_exports.parquet",
        description="Exports of goods and services (current USD) for ~192 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.EXP.GNFS.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_imports",
        path="output/macro/wide/wb_imports.parquet",
        description="Imports of goods and services (current USD) for ~192 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (NE.IMP.GNFS.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_current_account",
        path="output/macro/wide/wb_current_account.parquet",
        description="Current account balance (current USD) for ~200 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (BN.CAB.XOKA.CD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_fdi_inflows",
        path="output/macro/wide/wb_fdi_inflows.parquet",
        description="Foreign direct investment net inflows (current USD) for ~204 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (BX.KLT.DINV.CD.WD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_fdi_outflows",
        path="output/macro/wide/wb_fdi_outflows.parquet",
        description="Foreign direct investment net outflows (current USD) for ~198 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (BM.KLT.DINV.CD.WD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    dict(
        variable_id="wb_portfolio_equity_flows",
        path="output/macro/wide/wb_portfolio_equity.parquet",
        description="Portfolio equity net inflows (current USD) for ~191 countries.",
        family="macro",
        frequency="annual",
        source="World Bank (BX.PEF.TOTL.CD.WD)",
        unit="current USD",
        panel_columns="ISO 3166-1 alpha-3 country code",
    ),
    # ── IMF WEO ─────────────────────────────────────────────────────────────
    dict(
        variable_id="weo_gdp_usd",
        path="output/weo_ngdpd_wide.parquet",
        description="GDP in current USD (billions) from IMF WEO, 196 countries, 1980–2029 (incl. projections).",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (NGDPD)",
        unit="billions of current USD",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_gdp_growth",
        path="output/weo_ngdp_rpch_wide.parquet",
        description="Real GDP growth rate (%) from IMF WEO, 196 countries.",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (NGDP_RPCH)",
        unit="percent per year",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_inflation",
        path="output/weo_pcpipch_wide.parquet",
        description="CPI inflation rate (%) from IMF WEO, 196 countries.",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (PCPIPCH)",
        unit="percent per year",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_current_account_pct_gdp",
        path="output/weo_bca_ngdpd_wide.parquet",
        description="Current account balance (% of GDP) from IMF WEO, 195 countries.",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (BCA_NGDPD)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_unemployment",
        path="output/weo_lur_wide.parquet",
        description="Unemployment rate (%) from IMF WEO, 114 countries.",
        family="macro",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (LUR)",
        unit="percent of labor force",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_revenue_pct_gdp",
        path="output/weo_ggr_ngdp_wide.parquet",
        description="General government revenue (% of GDP) from IMF WEO, 196 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGR_NGDP)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_expenditure_pct_gdp",
        path="output/weo_ggx_ngdp_wide.parquet",
        description="General government total expenditure (% of GDP) from IMF WEO, 196 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGX_NGDP)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_fiscal_balance_pct_gdp",
        path="output/weo_ggxcnl_wide.parquet",
        description="General government net lending/borrowing = fiscal balance (% of GDP) from IMF WEO, 196 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXCNL)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_primary_balance_pct_gdp",
        path="output/weo_ggxonlb_wide.parquet",
        description="General government primary net lending/borrowing (% of GDP) from IMF WEO, 188 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXONLB)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_debt_gross_pct_gdp",
        path="output/weo_ggxwdg_wide.parquet",
        description="General government gross debt (% of GDP) from IMF WEO, 194 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXWDG)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    dict(
        variable_id="weo_govt_debt_net_pct_gdp",
        path="output/weo_ggxwdn_wide.parquet",
        description="General government net debt (% of GDP) from IMF WEO, 91 countries.",
        family="fiscal",
        frequency="annual",
        source="IMF World Economic Outlook Oct 2024 (GGXWDN)",
        unit="percent of GDP",
        panel_columns="country name",
    ),
    # ── BIS ─────────────────────────────────────────────────────────────────
    dict(
        variable_id="bis_intl_debt_by_nationality",
        path="output/bis_debt_sec_by_nat_wide.parquet",
        description="BIS international debt securities outstanding by issuer nationality (USD millions). issuer_res=3P means issued outside home country. 87 countries, quarterly.",
        family="fiscal",
        frequency="quarterly",
        source="BIS Statistics API (WS_DEBT_SEC2_PUB)",
        unit="USD millions",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    dict(
        variable_id="bis_intl_debt_by_residence",
        path="output/bis_debt_sec_by_res_wide.parquet",
        description="BIS international debt securities outstanding by issuer residence country (USD millions). 87 countries, quarterly.",
        family="fiscal",
        frequency="quarterly",
        source="BIS Statistics API (WS_DEBT_SEC2_PUB)",
        unit="USD millions",
        panel_columns="ISO 3166-1 alpha-2 country code",
    ),
    # ── TIC ─────────────────────────────────────────────────────────────────
    dict(
        variable_id="tic_foreign_holders",
        path="output/tic_holdings_wide.parquet",
        description="Foreign holdings of US Treasury securities by country (billions USD). 57 countries, monthly, 2000–present.",
        family="monetary",
        frequency="monthly",
        source="US Treasury TIC (mfhhis01.txt + mfh.txt)",
        unit="billions of USD",
        panel_columns="country name",
    ),
]


def read_parquet_stats(path: Path) -> dict:
    """Read date range and column count from a parquet file without loading all data."""
    try:
        import pyarrow.parquet as pq
        schema = pq.read_schema(path)
        # Get column names excluding the date index
        all_cols = schema.names
        data_cols = [c for c in all_cols if c not in ("date", "__null_dask_index__", "index")]

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

        return {
            "n_series":  len(data_cols),
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

        stats = read_parquet_stats(path_abs) if path_abs.exists() else {
            "n_series": None, "date_min": None, "date_max": None,
        }

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
