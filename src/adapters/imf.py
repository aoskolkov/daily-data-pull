"""
Adapter for the IMF SDMX JSON REST API.

Covers: BOP (flows), IIP (stocks), CPIS (bilateral portfolio), CDIS (bilateral FDI).
No API key required. Rate-limited to avoid 429s.

API docs: https://dataservices.imf.org/REST/SDMX_JSON.svc/help

Discovery (find valid indicator codes before filling the manifest):
    python wrdsdl.py discover imf --dataset BOP
    python wrdsdl.py discover imf --dataset IIP
    python wrdsdl.py discover imf --dataset CPIS
    python wrdsdl.py discover imf --dataset CDIS
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd
import requests

BASE_URL = "https://dataservices.imf.org/REST/SDMX_JSON.svc"
_PAUSE = 0.6          # seconds between requests; IMF throttles at ~10 req/s


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None, retries: int = 4) -> dict:
    for attempt in range(1, retries + 1):
        time.sleep(_PAUSE)
        try:
            resp = requests.get(url, params=params, timeout=90)
            if resp.status_code == 429:
                wait = 15 * attempt
                print(f"  Rate-limited. Waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            if attempt == retries:
                raise
            print(f"  Request failed ({exc}). Retry {attempt}/{retries}...")
    raise RuntimeError(f"Failed after {retries} attempts: {url}")


# ── Discovery ─────────────────────────────────────────────────────────────────

def discover(dataset: str) -> dict[str, dict[str, str]]:
    """
    Return {dimension_name: {code: label}} for an IMF dataset.
    Use to find valid indicator codes before setting the manifest.
    """
    url = f"{BASE_URL}/DataStructure/{dataset}"
    data = _get(url)

    codelists = (
        data.get("Structure", {})
        .get("CodeLists", {})
        .get("CodeList", [])
    )
    if isinstance(codelists, dict):
        codelists = [codelists]

    result: dict[str, dict[str, str]] = {}
    for cl in codelists:
        codes = cl.get("Code", [])
        if isinstance(codes, dict):
            codes = [codes]
        dim_id = cl.get("@id", "?")
        result[dim_id] = {
            c["@value"]: (
                c.get("Description", {}).get("#text", "")
                if isinstance(c.get("Description"), dict)
                else str(c.get("Description", ""))
            )
            for c in codes
        }
    return result


# ── SDMX JSON parsing ─────────────────────────────────────────────────────────

def _parse_compact(data: dict) -> pd.DataFrame:
    """
    Parse a CompactData response into a flat DataFrame.

    Each Series becomes rows; dimension attributes become columns.
    UNIT_MULT is applied automatically (0=units, 3=thousands, 6=millions, 9=billions).
    """
    ds = data.get("CompactData", {}).get("DataSet", {})
    series_raw = ds.get("Series")
    if not series_raw:
        return pd.DataFrame()

    if isinstance(series_raw, dict):
        series_raw = [series_raw]

    rows: list[dict] = []
    for series in series_raw:
        # Dimension values from @ attributes
        dims = {k.lstrip("@"): v for k, v in series.items() if k.startswith("@")}
        unit_mult = int(dims.pop("UNIT_MULT", 0) or 0)
        dims.pop("TIME_FORMAT", None)
        multiplier = 10 ** unit_mult

        obs = series.get("Obs", [])
        if isinstance(obs, dict):
            obs = [obs]
        for ob in obs:
            val_str = ob.get("@OBS_VALUE")
            if val_str is None:
                continue
            try:
                val = float(val_str) * multiplier
            except (ValueError, TypeError):
                continue
            rows.append({**dims, "period": ob["@TIME_PERIOD"], "value": val})

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _fetch_series(dataset: str, key: str, start: str, end: str) -> pd.DataFrame:
    url = f"{BASE_URL}/CompactData/{dataset}/{key}"
    params = {"startPeriod": start, "endPeriod": end}
    return _parse_compact(_get(url, params))


# ── BOP / IIP: non-bilateral ──────────────────────────────────────────────────

def _pull_nonbilateral(config: dict, watermark=None) -> pd.DataFrame:
    dataset    = config["dataset"]           # "BOP" or "IIP"
    frequency  = config.get("frequency", "A")
    indicators = config.get("indicators") or []
    start = str(watermark)[:4] if watermark is not None else config.get("start", "1980")
    end   = str(date.today().year)

    if not indicators:
        raise ValueError(
            f"No indicators listed for dataset '{dataset}'.\n"
            f"Run:  python wrdsdl.py discover imf --dataset {dataset}\n"
            f"Then add the codes you need to config/datasets.yaml under 'indicators:'."
        )

    frames: list[pd.DataFrame] = []
    for indicator in indicators:
        key = f"{frequency}..{indicator}"      # double-dot = wildcard REF_AREA
        print(f"  {dataset}.{indicator}...", end=" ", flush=True)
        df = _fetch_series(dataset, key, start, end)
        if df.empty:
            print("no data")
        else:
            frames.append(df)
            print(f"{len(df):,} rows")

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)

    # Normalise column names
    col_map = {}
    for c in result.columns:
        u = c.upper()
        if u == "REF_AREA":
            col_map[c] = "iso2c"
        elif u == "INDICATOR":
            col_map[c] = "indicator"
        elif u == "FREQ":
            col_map[c] = "freq"
    result = result.rename(columns=col_map)

    result["date"] = pd.to_datetime(
        result["period"].astype(str).str[:4] + "-01-01", errors="coerce"
    )
    result["source"] = f"imf_{dataset.lower()}"
    return result.dropna(subset=["date", "value"])


# ── CPIS / CDIS: bilateral ────────────────────────────────────────────────────

def _pull_bilateral(config: dict, watermark=None) -> pd.DataFrame:
    """
    Pull CPIS or CDIS — bilateral (reporter × counterpart × instrument).

    Strategy: try a full wildcard first. If the response is too large or errors,
    fall back to pulling per reporting country using the REF_AREA codelist.
    """
    dataset   = config["dataset"]
    frequency = config.get("frequency", "A")
    start = str(watermark)[:4] if watermark is not None else config.get("start", "2001")
    end   = str(date.today().year)

    # Try full wildcard
    key = f"{frequency}..."
    print(f"  {dataset}: trying full pull (all reporters × counterparts)...")
    try:
        df = _fetch_series(dataset, key, start, end)
        if not df.empty:
            return _finalize_bilateral(df, dataset)
    except Exception as exc:
        print(f"  Full pull failed ({exc}). Falling back to per-reporter...")

    # Fall back: one reporter at a time
    codes = discover(dataset)
    reporter_codelist = next(
        (v for k, v in codes.items() if "REF_AREA" in k or "REPORTER" in k), {}
    )
    if not reporter_codelist:
        raise RuntimeError(f"Could not find reporter codelist for {dataset}")

    reporters = list(reporter_codelist.keys())
    print(f"  Pulling {len(reporters)} reporters...")
    frames: list[pd.DataFrame] = []
    for reporter in reporters:
        k = f"{frequency}.{reporter}.."
        try:
            df = _fetch_series(dataset, k, start, end)
            if not df.empty:
                frames.append(df)
        except Exception as exc:
            print(f"  WARNING: {reporter} failed: {exc}")

    if not frames:
        return pd.DataFrame()
    return _finalize_bilateral(pd.concat(frames, ignore_index=True), dataset)


def _finalize_bilateral(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    col_map = {}
    for c in df.columns:
        u = c.upper()
        if u == "REF_AREA":
            col_map[c] = "reporter"
        elif u in ("COUNTERPART_AREA", "CPART_AREA", "COUNTERPART"):
            col_map[c] = "counterpart"
        elif u == "INDICATOR":
            col_map[c] = "indicator"
        elif u == "FREQ":
            col_map[c] = "freq"
    df = df.rename(columns=col_map)
    df["date"] = pd.to_datetime(
        df["period"].astype(str).str[:4] + "-01-01", errors="coerce"
    )
    df["source"] = f"imf_{dataset.lower()}"
    n_reporters    = df["reporter"].nunique()    if "reporter"    in df.columns else "?"
    n_counterparts = df["counterpart"].nunique() if "counterpart" in df.columns else "?"
    print(f"  {dataset}: {len(df):,} rows, {n_reporters} reporters × {n_counterparts} counterparts")
    return df.dropna(subset=["date", "value"])


# ── Dispatch ──────────────────────────────────────────────────────────────────

def pull(config: dict, watermark=None) -> pd.DataFrame:
    dataset = config["dataset"]
    if dataset in ("CPIS", "CDIS"):
        return _pull_bilateral(config, watermark)
    return _pull_nonbilateral(config, watermark)
