"""
Clean CFTC Commitments of Traders FX positioning → macrodata/cftc_fx/.

Reads:  data/cftc_fx_tff/      (TFF report, 2006–present, 13 contracts)
        data/cftc_fx_legacy/   (legacy report, 1986–present, 11 contracts)

Writes: macrodata/cftc_fx/tff_<sector>_net_wide.{parquet,csv}
        macrodata/cftc_fx/tff_open_interest_wide.{parquet,csv}
        macrodata/cftc_fx/legacy_<sector>_net_wide.{parquet,csv}
        macrodata/cftc_fx/legacy_open_interest_wide.{parquet,csv}
        macrodata/cftc_fx/cftc_fx_long.{parquet,csv}   — tidy, all fields
        macrodata/cftc_fx/cftc_fx_meta.csv             — code → currency map

Wide files are date × currency. Values are NET positioning (long - short) in
contracts. Spreading is excluded from net by construction: the CFTC reports it
separately because a spread position is simultaneously long and short.

Columns are ISO currency codes rather than contract names, since CFTC contract
names drift and get rewritten retroactively (see config/datasets.yaml).
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TFF_DIR = ROOT / "data" / "cftc_fx_tff"
LEGACY_DIR = ROOT / "data" / "cftc_fx_legacy"
OUT_DIR = ROOT / "macrodata" / "cftc_fx"

# Stable contract code → ISO currency. Verified against the live API 2026-07-24.
CODE_TO_CCY = {
    "099741": "EUR",
    "097741": "JPY",
    "096742": "GBP",
    "092741": "CHF",
    "090741": "CAD",
    "232741": "AUD",
    "112741": "NZD",
    "095741": "MXN",
    "102741": "BRL",
    "122741": "ZAR",
    "089741": "RUB",
    "299741": "EURGBP",
    "399741": "EURJPY",
}

# Code 099741 also carries 10 observations from Jan–Aug 1986 that are the
# European Currency Unit contract, not the euro, followed by a 12-year gap.
# Different instrument — drop rather than splice into a EUR series.
EUR_CONTRACT_START = "1999-01-01"

TFF_SECTORS = ["dealer", "asset_mgr", "lev_money", "other_rept", "nonrept"]
LEGACY_SECTORS = ["noncomm", "comm", "nonrept"]


def _load(data_dir: Path, label: str) -> pd.DataFrame | None:
    if not data_dir.exists() or not any(data_dir.iterdir()):
        print(f"  Skipping {label}: not yet pulled"
              f"  (python wrdsdl.py pull {data_dir.name})")
        return None

    df = pd.read_parquet(data_dir)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["contract_code"] = df["contract_code"].astype(str).str.zfill(6)
    df["ccy"] = df["contract_code"].map(CODE_TO_CCY)

    unmapped = sorted(df.loc[df["ccy"].isna(), "contract_code"].unique())
    if unmapped:
        print(f"  WARNING: unmapped contract codes dropped from {label}: {unmapped}")
        df = df.dropna(subset=["ccy"])

    # Drop the pre-euro ECU observations carried under the EUR contract code.
    ecu = (df["ccy"] == "EUR") & (df["date"] < pd.Timestamp(EUR_CONTRACT_START))
    if ecu.any():
        print(f"  {label}: dropped {ecu.sum()} pre-1999 ECU observations from EUR")
        df = df[~ecu]

    # Storage can emit duplicate (date, contract) rows across partition boundaries.
    df = df.sort_values(["date", "ccy"]).drop_duplicates(
        subset=["date", "contract_code"], keep="last"
    )
    return df


def _write_wide(df: pd.DataFrame, values: str, label: str, no_csv: bool) -> None:
    sub = df.dropna(subset=[values])
    if sub.empty:
        print(f"  {label}: no data, skipped")
        return

    wide = (
        sub.groupby(["date", "ccy"])[values].last()
           .unstack("ccy")
           .sort_index()
    )
    wide.columns.name = None
    wide.index.name = "date"

    out = OUT_DIR / label
    wide.to_parquet(str(out) + ".parquet")
    if not no_csv:
        wide.to_csv(str(out) + ".csv")
    print(f"  {label}: {wide.shape[0]} dates × {wide.shape[1]} currencies"
          f"  ({wide.index.min().date()} – {wide.index.max().date()})")


def _process(df: pd.DataFrame, prefix: str, sectors: list[str], no_csv: bool) -> None:
    for sector in sectors:
        long_col, short_col = f"{sector}_long", f"{sector}_short"
        if long_col not in df.columns or short_col not in df.columns:
            print(f"  {prefix}_{sector}: columns missing, skipped")
            continue
        df[f"{sector}_net"] = df[long_col] - df[short_col]
        _write_wide(df, f"{sector}_net", f"{prefix}_{sector}_net_wide", no_csv)

    if "open_interest" in df.columns:
        _write_wide(df, "open_interest", f"{prefix}_open_interest_wide", no_csv)


def main(no_csv: bool = False) -> None:
    tff = _load(TFF_DIR, "cftc_fx_tff")
    legacy = _load(LEGACY_DIR, "cftc_fx_legacy")

    if tff is None and legacy is None:
        print("\nNothing processed. Pull first:")
        print("  python wrdsdl.py pull cftc_fx_tff")
        print("  python wrdsdl.py pull cftc_fx_legacy")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    frames = []
    if tff is not None:
        print("  TFF (2006–present, sector breakdown):")
        _process(tff, "tff", TFF_SECTORS, no_csv)
        frames.append(tff.assign(report="tff"))

    if legacy is not None:
        print("  Legacy (1986–present, commercial/non-commercial):")
        _process(legacy, "legacy", LEGACY_SECTORS, no_csv)
        frames.append(legacy.assign(report="legacy"))

    # Tidy long file — every field from both reports, stacked.
    combined = pd.concat(frames, ignore_index=True).sort_values(
        ["report", "date", "ccy"]
    )
    combined.to_parquet(OUT_DIR / "cftc_fx_long.parquet", index=False)
    if not no_csv:
        combined.to_csv(OUT_DIR / "cftc_fx_long.csv", index=False)
    print(f"  cftc_fx_long: {len(combined):,} rows")

    meta = (
        combined.groupby(["report", "contract_code", "ccy"])
        .agg(contract=("contract", "last"),
             n_obs=("date", "size"),
             first=("date", "min"),
             last=("date", "max"))
        .reset_index()
        .sort_values(["report", "ccy"])
    )
    meta.to_csv(OUT_DIR / "cftc_fx_meta.csv", index=False)
    print(f"  cftc_fx_meta.csv: {len(meta)} contract-report rows")


if __name__ == "__main__":
    main(no_csv="--no-csv" in sys.argv)
