"""
Adapter for the World Bank API v2 multidimensional ("sources") endpoint.

Needed for International Debt Statistics (IDS, source 6): its series are keyed
by country × series × counterpart-area × time, and the plain indicator endpoint
(/country/{c}/indicator/{s}, used by pandas_datareader and the `external`
adapter) answers "indicator not found" for IDS-only series such as arrears.

    https://api.worldbank.org/v2/sources/{src}/country/{c}/series/{s}
        [/counterpart-area/{area}] [/version/{vintage}] /time/all?format=json

Sources used here:
     2  World Development Indicators
     6  International Debt Statistics (low- and middle-income countries only;
        countries that graduate to high income drop out of the whole history)
    57  WDI Database Archives — past WDI/GDF vintages (e.g. 201906), the only
        public source for graduated countries' debt and for the PPG arrears
        totals DT.IXA.DPPG.CD / DT.AXA.DPPG.CD (last filled in vintage 201906)

Config keys (datasets.yaml)
---------------------------
  source: wb_api
  wb_source: 6
  series: [DT.DOD.DPPG.CD, ...]
  countries: all              # or a list of ISO3 codes
  counterpart_area: WLD       # sources with a Counterpart-Area dimension (IDS)
  versions: {"201906": [BGR, RUS]}   # source 57: vintage -> countries
  start: 1970                 # drop earlier years

Output: date, country, country_name, is_aggregate, series, value, wb_source,
        version, counterpart_area
"""

from __future__ import annotations

import time

import pandas as pd
import requests

BASE_URL = "https://api.worldbank.org/v2"
_PAUSE = 0.3


def _get_json(url: str, params: dict, retries: int = 4):
    for attempt in range(1, retries + 1):
        time.sleep(_PAUSE)
        try:
            resp = requests.get(url, params=params, timeout=300)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:
                # Unknown series/version -> XML error page, not JSON
                raise ValueError(f"non-JSON response ({resp.text[:160]!r})") from None
        except requests.exceptions.RequestException as exc:
            if attempt == retries:
                raise
            print(f"  Request failed ({exc}). Retry {attempt}/{retries}...")
    raise RuntimeError(f"Failed after {retries} attempts: {url}")


def _fetch(src: int, countries: str, series: str, area: str | None, version: str | None) -> pd.DataFrame:
    path = f"{BASE_URL}/sources/{src}/country/{countries}/series/{series}/"
    if area:
        path += f"counterpart-area/{area}/"
    if version:
        path += f"version/{version}/"
    path += "time/all"

    rows, page, pages = [], 1, 1
    while page <= pages:
        data = _get_json(path, {"format": "json", "per_page": 20000, "page": page})
        if not isinstance(data, dict):
            msg = data[0].get("message", [{}])[0].get("value", data) if isinstance(data, list) and data else data
            raise ValueError(f"{series}: {msg}")
        pages = int(data.get("pages", 1))
        for rec in data["source"]["data"]:
            if rec.get("value") is None:
                continue
            v = {x["concept"].lower(): x["id"] for x in rec["variable"]}
            rows.append((v.get("country"), v.get("series"), v.get("time"), rec["value"]))
        page += 1
    return pd.DataFrame(rows, columns=["country", "series", "time", "value"])


def _country_meta() -> pd.DataFrame:
    data = _get_json(f"{BASE_URL}/country", {"format": "json", "per_page": 500})
    return pd.DataFrame(
        [(c["id"], c["name"], c["region"]["value"] == "Aggregates") for c in data[1]],
        columns=["country", "country_name", "is_aggregate"],
    )


def pull(conn, config: dict, watermark=None) -> pd.DataFrame:
    src = int(config["wb_source"])
    series: list[str] = config["series"]
    area = config.get("counterpart_area")
    start = int(config.get("start", 1960))

    countries = config.get("countries", "all")
    jobs = [(None, countries if isinstance(countries, str) else ";".join(countries))]
    if config.get("versions"):
        jobs = [(str(ver), ";".join(cs)) for ver, cs in config["versions"].items()]

    frames = []
    for version, ctry in jobs:
        n = 0
        for s in series:        # one series per request: a bad code fails alone
            try:
                df = _fetch(src, ctry, s, area, version)
            except ValueError as exc:
                print(f"  WARNING: source {src} {version or ''} {exc}")
                continue
            if df.empty:
                continue
            df["version"] = version
            frames.append(df)
            n += len(df)
        print(f"  {f'vintage {version}' if version else f'source {src}'}: {n:,} obs")
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["year"] = pd.to_numeric(df["time"].str[2:], errors="coerce")
    df = df[df["year"] >= start]
    df["date"] = pd.to_datetime(df["year"].astype(int).astype(str) + "-01-01")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["wb_source"] = src
    df["counterpart_area"] = area
    df = df.merge(_country_meta(), on="country", how="left")

    out = df[["date", "country", "country_name", "is_aggregate", "series", "value",
              "wb_source", "version", "counterpart_area"]].dropna(subset=["value"])
    print(f"  {len(out):,} rows, {out['country'].nunique()} countries, {out['series'].nunique()} series, "
          f"{out['date'].min().year}–{out['date'].max().year}")
    return out.reset_index(drop=True)
