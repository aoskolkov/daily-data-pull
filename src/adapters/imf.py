"""
Adapter for the IMF data API (api.imf.org, SDMX 2.1 REST).

The old SDMX-JSON service (dataservices.imf.org/REST/SDMX_JSON.svc) was retired
with the move to the new IMF data portal in 2025; the host no longer resolves.
The replacement needs no API key:

    data:       https://api.imf.org/external/sdmx/2.1/data/IMF.STA,{FLOW}/{KEY}
    structure:  https://api.imf.org/external/sdmx/3.0/structure/dataflow/IMF.STA/{FLOW}/+

Datasets were renamed and restructured (IFS-style codes like BFDI are gone):
    BOP   Balance of Payments          COUNTRY.BOP_ACCOUNTING_ENTRY.INDICATOR.UNIT.FREQUENCY
    IIP   International Inv. Position  COUNTRY.BOP_ACCOUNTING_ENTRY.INDICATOR.UNIT.FREQUENCY
    PIP   Portfolio Inv. Positions by Counterpart (formerly CPIS)
          COUNTRY.ACCOUNTING_ENTRY.INDICATOR.SECTOR.COUNTERPART_SECTOR.COUNTERPART_COUNTRY.FREQUENCY
    DIP   Direct Inv. Positions by Counterpart (formerly CDIS)
          COUNTRY.DV_TYPE.INDICATOR.COUNTERPART_COUNTRY.FREQUENCY
Countries are ISO3. OBS_VALUE is in units (e.g. USD), not scaled; SCALE is a
display hint only.

Config keys (datasets.yaml)
---------------------------
  source: imf
  dataflow: BOP                 # IMF.STA dataflow id
  dims:                         # full series key, in the dataflow's dimension order
    COUNTRY: ""                 #   "" = all, a string, or a list (joined with '+')
    BOP_ACCOUNTING_ENTRY: [A_NFA_T, L_NIL_T]
    INDICATOR: [D_F, P_F]
    UNIT: USD
    FREQUENCY: A
  labels:                       # optional: "<code>.<code>" over label_dims -> label;
    A_NFA_T.D_F: fdi_assets     #   rows whose combination is not listed are dropped
  label_dims: [BOP_ACCOUNTING_ENTRY, INDICATOR]
  chunk_by: INDICATOR           # optional: one request per code in this dimension
  start: "1980"

Output: date, country, indicator (label, or raw code without labels), value,
plus every other dimension as a lower-case column, e.g. counterpart_country.

Discovery:  python wrdsdl.py discover imf --dataset BOP
"""

from __future__ import annotations

import io
import time

import pandas as pd
import requests

DATA_URL = "https://api.imf.org/external/sdmx/2.1/data"
STRUCTURE_URL = "https://api.imf.org/external/sdmx/3.0/structure/dataflow"
AGENCY = "IMF.STA"
_CSV = {"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}
_PAUSE = 0.5


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None, headers: dict | None = None,
         retries: int = 4, timeout: int = 1800) -> requests.Response:
    for attempt in range(1, retries + 1):
        time.sleep(_PAUSE)
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in (429, 502, 503, 504):
                wait = 20 * attempt
                print(f"  HTTP {resp.status_code}. Waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 404:   # SDMX "no results found"
                return resp
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as exc:
            if attempt == retries:
                raise
            print(f"  Request failed ({exc}). Retry {attempt}/{retries}...")
    raise RuntimeError(f"Failed after {retries} attempts: {url}")


def _fetch_csv(dataflow: str, key: str, start: str | None) -> pd.DataFrame:
    params = {"detail": "dataonly"}
    if start:
        params["startPeriod"] = start
    resp = _get(f"{DATA_URL}/{AGENCY},{dataflow}/{key}", params, _CSV)
    if resp.status_code == 404 or not resp.text.strip():
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(resp.text), dtype=str)
    # dataonly still emits every attribute column (empty); series without
    # observations in the window come back as rows with no TIME_PERIOD.
    df = df.dropna(subset=["TIME_PERIOD", "OBS_VALUE"])
    return df[[c for c in df.columns if df[c].notna().any()]]


# ── Keys and dates ───────────────────────────────────────────────────────────

def _key(dims: dict) -> str:
    return ".".join("+".join(v) if isinstance(v, list) else str(v or "") for v in dims.values())


def _period_to_date(p: pd.Series) -> pd.Series:
    """'2024' -> 2024-01-01, '2024-Q3' -> 2024-07-01, '2024-M05' -> 2024-05-01, '2024-S2' -> 2024-07-01."""
    p = p.astype(str)
    year = p.str[:4]
    month = pd.Series("01", index=p.index)
    q = p.str.extract(r"-Q(\d)$")[0]
    m = p.str.extract(r"-M?(\d{2})$")[0]
    s = p.str.extract(r"-S(\d)$")[0]
    month = month.where(q.isna(), ((q.astype(float) - 1) * 3 + 1).map(lambda x: f"{int(x):02d}" if pd.notna(x) else "01"))
    month = month.where(m.isna(), m)
    month = month.where(s.isna(), s.map(lambda x: "07" if x == "2" else "01"))
    return pd.to_datetime(year + "-" + month + "-01", errors="coerce")


# ── Discovery ────────────────────────────────────────────────────────────────

def _structure(dataflow: str) -> tuple[list[str], dict[str, dict[str, str]], dict[str, str]]:
    """Return (dimension ids in key order, {dimension: {code: label}}, {any code: label})."""
    resp = _get(f"{STRUCTURE_URL}/{AGENCY}/{dataflow}/+",
                {"references": "descendants", "detail": "full"}, timeout=300)
    data = resp.json()["data"]
    def _name(c: dict) -> str:
        n = c.get("name")
        return n if isinstance(n, str) else c.get("names", {}).get("en", "")

    codelists = {
        cl["id"]: {c["id"]: _name(c) for c in cl.get("codes", [])}
        for cl in data.get("codelists", [])
    }
    concept_cl = {}
    for cs in data.get("conceptSchemes", []):
        for c in cs.get("concepts", []):
            enum = c.get("coreRepresentation", {}).get("enumeration", "")
            if enum:
                concept_cl[c["id"]] = enum.split(":")[-1].split("(")[0]
    dims = data["dataStructures"][0]["dataStructureComponents"]["dimensionList"]["dimensions"]
    order = [d["id"] for d in sorted(dims, key=lambda d: d.get("position", 0))]
    # Dataflow-specific lists (CL_PIP_COUNTRY: TX093 = "SEFER + SSIO", ...) name codes
    # the generic lists the concepts point to lack; keep them as a lookup fallback.
    names: dict[str, str] = {}
    for cl_id in sorted(codelists, key=lambda k: k.startswith(f"CL_{dataflow}_")):
        names.update(codelists[cl_id])
    return order, {d: codelists.get(concept_cl.get(d, ""), {}) for d in order}, names


def discover(dataset: str, sample_country: str = "USA") -> dict[str, dict[str, str]]:
    """
    {dimension: {code: label}} for an IMF dataflow. The codelists are huge
    (CL_BOP_INDICATOR has ~1,000 codes), so codes are restricted to those that
    occur in a one-country sample pull whenever that pull succeeds.
    """
    order, codes, names = _structure(dataset)
    print(f"  Key order: {'.'.join(order)}")
    dims = {d: (sample_country if d == "COUNTRY" else "") for d in order}
    try:
        sample = _fetch_csv(dataset, _key(dims), start=None)
    except Exception as exc:
        print(f"  Sample pull failed ({exc}); showing full codelists.")
        sample = pd.DataFrame()
    if sample.empty:
        return codes
    print(f"  Codes below are those present in the {sample_country} sample ({len(sample):,} obs).")
    return {
        d: {c: codes[d].get(c) or names.get(c, "") for c in sorted(sample[d].dropna().unique())}
        if d in sample.columns else codes[d]
        for d in order
    }


# ── Pull ─────────────────────────────────────────────────────────────────────

def pull(config: dict, watermark=None) -> pd.DataFrame:
    dataflow = config["dataflow"]
    dims: dict = dict(config["dims"])
    labels: dict = config.get("labels") or {}
    label_dims: list[str] = config.get("label_dims") or ["INDICATOR"]
    chunk_by: str | None = config.get("chunk_by")
    start = str(watermark)[:4] if watermark is not None else str(config.get("start", ""))

    chunks = [dims]
    if chunk_by and isinstance(dims.get(chunk_by), list):
        chunks = [{**dims, chunk_by: code} for code in dims[chunk_by]]

    frames = []
    for d in chunks:
        what = d.get(chunk_by, "") if chunk_by else "all"
        t0 = time.time()
        df = _fetch_csv(dataflow, _key(d), start or None)
        print(f"  {dataflow} {what}: {len(df):,} obs ({time.time() - t0:.0f}s)")
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)

    if labels:
        combo = df[label_dims].astype(str).agg(".".join, axis=1)
        df = df[combo.isin(labels)].copy()
        df["indicator_code"] = df["INDICATOR"]
        df["INDICATOR"] = combo[df.index].map(labels)

    keep = [c for c in dims if c in df.columns and c != "FREQUENCY"]
    out = df[keep].copy()
    out.columns = [c.lower() for c in keep]
    if "indicator_code" in df.columns:
        out["indicator_code"] = df["indicator_code"]
    out["freq"] = df["FREQUENCY"] if "FREQUENCY" in df.columns else None
    out["date"] = _period_to_date(df["TIME_PERIOD"])
    out["value"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    out["source"] = f"imf_{dataflow.lower()}"
    out = out.dropna(subset=["date", "value"]).reset_index(drop=True)

    n_c = out["country"].nunique() if "country" in out.columns else "?"
    print(f"  {dataflow}: {len(out):,} rows, {n_c} countries, "
          f"{out['indicator'].nunique()} indicators, {out['date'].min().date()} – {out['date'].max().date()}")
    return out
