"""
WRDS data download pipeline CLI.

Run from repo root:
  python wrdsdl.py pull fx_spot
  python wrdsdl.py pull --all
  python wrdsdl.py discover comp
  python wrdsdl.py discover comp --table exrt_fwd
  python wrdsdl.py discover imf --dataset BOP
  python wrdsdl.py discover imf --dataset PIP
  python wrdsdl.py refresh fx_spot
  python wrdsdl.py validate
  python wrdsdl.py catalog
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

from .connection import get_env_credential, wrds_connection
from . import discovery, normalize, storage, state, catalog
from .adapters import wrds_sql, datastream, wrds_fut, wrds_fx, wrds_ds_comds, wrds_ds_index, wrds_ds_econ, external, imf as imf_adapter, tic, bis, imf_weo, msci_web, cftc, wb_api


# ── Config loading ────────────────────────────────────────────────────────────

def load_config(config_dir: str = "config") -> tuple[dict, list[dict]]:
    config_path = Path(config_dir)

    datasets_file = config_path / "datasets.yaml"
    if not datasets_file.exists():
        raise FileNotFoundError(f"datasets.yaml not found at {datasets_file.resolve()}")

    with datasets_file.open(encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    defaults = manifest.get("defaults", {})
    datasets: list[dict] = manifest.get("datasets", [])
    for ds in datasets:
        for k, v in defaults.items():
            ds.setdefault(k, v)

    conn_config: dict = {}
    conn_yaml = config_path / "connection.yaml"
    if conn_yaml.exists():
        with conn_yaml.open(encoding="utf-8") as f:
            conn_config = yaml.safe_load(f) or {}

    return conn_config, datasets


def find_dataset(datasets: list[dict], name: str) -> dict:
    matches = [ds for ds in datasets if ds["name"] == name]
    if not matches:
        available = [d["name"] for d in datasets]
        raise ValueError(f"Dataset '{name}' not in manifest. Available: {available}")
    return matches[0]


def _wrds_username(conn_config: dict) -> str | None:
    wrds_cfg = conn_config.get("wrds", {})
    env_key = wrds_cfg.get("username_env", "WRDS_USERNAME")
    return get_env_credential(env_key)


# ── Core pull logic ───────────────────────────────────────────────────────────

def do_pull(conn, ds_config: dict, force_full: bool = False) -> None:
    name = ds_config["name"]
    source = ds_config["source"]
    storage_root = ds_config.get("storage_root", "./data")
    incremental_key: str | None = ds_config.get("incremental_key")
    partition_by: list[str] = ds_config.get("partition_by", [])
    partition_col = partition_by[0] if partition_by else incremental_key

    watermark = None
    if not force_full and incremental_key:
        watermark = state.load_watermark(name, storage_root)
        if watermark:
            print(f"  Incremental from watermark: {watermark}")
            # The watermark is the max date across all series, so late reporters
            # and revisions behind it are never fetched. Re-pull a trailing window;
            # storage.write_parquet(append=True) replaces it in place.
            lookback = int(ds_config.get("lookback_days", 0))
            if lookback:
                watermark = str((pd.Timestamp(watermark) - pd.Timedelta(days=lookback)).date())
                print(f"  Lookback {lookback}d -> re-pulling from {watermark}")

    print(f"Pulling: {name}  (source={source})")

    if source == "wrds_sql":
        df = wrds_sql.pull(conn, ds_config, watermark)
    elif source == "datastream":
        df = datastream.pull(conn, ds_config, watermark)
    elif source == "wrds_fut":
        df = wrds_fut.pull(conn, ds_config, watermark)
    elif source == "wrds_fx":
        df = wrds_fx.pull(conn, ds_config, watermark)
    elif source == "wrds_ds_comds":
        df = wrds_ds_comds.pull(conn, ds_config, watermark)
    elif source == "wrds_ds_index":
        df = wrds_ds_index.pull(conn, ds_config, watermark)
    elif source == "wrds_ds_econ":
        df = wrds_ds_econ.pull(conn, ds_config, watermark)
    elif source == "external":
        df = external.pull(ds_config, watermark)
    elif source == "imf":
        df = imf_adapter.pull(ds_config, watermark)
    elif source == "tic":
        df = tic.pull(conn, ds_config, watermark)
    elif source == "bis":
        df = bis.pull(conn, ds_config, watermark)
    elif source == "imf_weo":
        df = imf_weo.pull(conn, ds_config, watermark)
    elif source == "msci_web":
        df = msci_web.pull(ds_config, watermark)
    elif source == "cftc":
        df = cftc.pull(ds_config, watermark)
    elif source == "wb_api":
        df = wb_api.pull(conn, ds_config, watermark)
    else:
        raise ValueError(f"Unknown source '{source}'")

    if df.empty:
        print(f"  No new data for {name}.")
        return

    date_col = incremental_key or "datadate"
    if date_col in df.columns:
        df = normalize.normalize_dates(df, date_col)

    print(f"  {len(df):,} rows fetched.")

    storage.write_parquet(
        df, name, partition_col=date_col, storage_root=storage_root,
        append=watermark is not None,
    )

    date_series = pd.to_datetime(df[date_col], errors="coerce") if date_col in df.columns else pd.Series(dtype="datetime64[ns]")
    meta: dict = {
        "dataset": name,
        "source": source,
        "rows": len(df),
        "date_min": str(date_series.min().date()) if not date_series.dropna().empty else None,
        "date_max": str(date_series.max().date()) if not date_series.dropna().empty else None,
        "schema": {col: str(dtype) for col, dtype in df.dtypes.items()},
    }
    storage.write_sidecar(meta, name, storage_root)

    if incremental_key and not date_series.dropna().empty:
        new_wm = str(date_series.max().date())
        state.save_watermark(name, new_wm, storage_root)
        print(f"  Watermark -> {new_wm}")

    catalog.update_catalog(meta, storage_root)
    print(f"  Saved -> {Path(storage_root) / name}")


# ── Subcommand handlers ───────────────────────────────────────────────────────

def cmd_pull(args, conn_config: dict, datasets: list[dict], force_full: bool = False) -> None:
    targets = datasets if getattr(args, "all", False) else [find_dataset(datasets, args.dataset)]

    wrds_targets = [ds for ds in targets if ds["source"] in ("wrds_sql", "datastream", "wrds_fut", "wrds_fx", "wrds_ds_comds", "wrds_ds_index", "wrds_ds_econ")]
    noconn_targets = [ds for ds in targets if ds["source"] in ("external", "imf", "tic", "bis", "imf_weo", "msci_web", "cftc", "wb_api")]

    if wrds_targets:
        with wrds_connection(username=_wrds_username(conn_config)) as conn:
            for ds in wrds_targets:
                try:
                    do_pull(conn, ds, force_full=force_full)
                except Exception as exc:
                    print(f"ERROR pulling {ds['name']}: {exc}", file=sys.stderr)

    for ds in noconn_targets:
        try:
            do_pull(None, ds, force_full=force_full)
        except Exception as exc:
            print(f"ERROR pulling {ds['name']}: {exc}", file=sys.stderr)


def cmd_discover(args, conn_config: dict) -> None:
    if args.library.lower() == "imf":
        dataset = getattr(args, "dataset", None)
        if not dataset:
            print("Usage: python wrdsdl.py discover imf --dataset <DATASET>")
            print("IMF.STA dataflows, e.g.: BOP, IIP, PIP (ex-CPIS), DIP (ex-CDIS), IL, MFS_IR, CPI")
            return
        print(f"\nIMF dataflow: IMF.STA:{dataset}")
        codes = imf_adapter.discover(dataset)
        for dim, codelist in codes.items():
            print(f"\n  Dimension: {dim}  ({len(codelist)} codes)")
            for code, label in list(codelist.items())[:30]:
                print(f"    {code:20s}  {label}")
            if len(codelist) > 30:
                print(f"    ... ({len(codelist) - 30} more)")
        return

    if args.library.lower() == "bis":
        dataflow = getattr(args, "dataset", None)
        if not dataflow:
            print("Usage: python wrdsdl.py discover bis --dataset <DATAFLOW>")
            print("Example dataflows: WS_DEBT_SEC2_PUB, WS_LBS_D_PUB, WS_TC, WS_EER, WS_CBPOL")
            return
        print(f"\nBIS dataflow: {dataflow}")
        dims = bis.discover(dataflow)
        for dim, codes in dims.items():
            print(f"\n  {dim}  ({len(codes)} codes)")
            for code, label in list(codes.items())[:20]:
                print(f"    {code:20s}  {label}")
            if len(codes) > 20:
                print(f"    ... ({len(codes) - 20} more)")
        return

    with wrds_connection(username=_wrds_username(conn_config)) as conn:
        if getattr(args, "table", None):
            print(f"\nSchema: {args.library}.{args.table}")
            schema = discovery.describe_table(conn, args.library, args.table)
            print(schema.to_string(index=False))
            print("\nSample rows (5):")
            sample = discovery.sample_table(conn, args.library, args.table)
            print(sample.to_string(index=False))
        else:
            print(f"\nLibrary: {args.library}")
            tables = conn.list_tables(library=args.library)
            for t in sorted(tables):
                print(f"  {t}")


def cmd_validate(args, conn_config: dict, datasets: list[dict]) -> None:
    with wrds_connection(username=_wrds_username(conn_config)) as conn:
        libs = set(discovery.list_libraries(conn))
        print("\nValidation report")
        print("-" * 60)
        for ds in datasets:
            name = ds["name"]
            source = ds["source"]
            storage_root = ds.get("storage_root", "./data")

            if source == "wrds_sql":
                lib = ds.get("library", "")
                subscribed = lib in libs
                status = "✓ subscribed" if subscribed else "✗ NOT subscribed"
                print(f"\n{name}  [{source}]  library={lib}  {status}")
                if subscribed and ds.get("fields"):
                    try:
                        schema = discovery.describe_table(conn, lib, ds["table"])
                        table_cols = set(schema["name"].str.lower()) if "name" in schema.columns else set()
                        missing = [f for f in ds["fields"] if f.lower() not in table_cols]
                        if missing:
                            print(f"  WARNING: requested fields not in table: {missing}")
                        else:
                            print(f"  Fields OK: {ds['fields']}")
                    except Exception as exc:
                        print(f"  WARNING: could not describe table: {exc}")
            elif source == "external":
                print(f"\n{name}  [{source}]  provider={ds.get('provider')}")
            else:
                print(f"\n{name}  [{source}]")

            meta_path = Path(storage_root) / name / "_meta.json"
            if meta_path.exists():
                with meta_path.open() as f:
                    meta = json.load(f)
                rows = meta.get("rows", 0)
                print(f"  Last pull: {meta.get('pulled_at', '?')}  rows={rows:,}  {meta.get('date_min')} -> {meta.get('date_max')}")
            else:
                print(f"  Not yet pulled.")


# ── Clean subcommand ──────────────────────────────────────────────────────────

# Ordered list of clean scripts; each runs independently and skips missing data.
_CLEAN_SCRIPTS: list[tuple[str, list[str]]] = [
    ("clean/fx_spot.py",        []),
    ("clean/fx_forward.py",     []),
    ("clean/oil.py",            []),
    ("clean/oil_curve.py",      []),
    ("clean/inflation.py",      []),
    ("clean/macro.py",          []),
    ("clean/capital_flows.py",  []),
    ("clean/bilateral.py",      []),
    ("clean/vol.py",            []),
    ("clean/commodities.py",    []),
    ("clean/equity_indices.py", []),
    ("clean/interest_rates.py", []),
    ("clean/cpi_monthly.py",   []),
    ("clean/bop_quarterly.py", []),
    ("clean/tic.py",            []),
    ("clean/bis_debt_sec.py",   []),
    ("clean/bis_lbs.py",        []),
    ("clean/bis_eer.py",        []),
    ("clean/imf_weo.py",        []),
    ("clean/msci.py",           []),
    ("clean/cftc_fx.py",        []),
    ("clean/partial_default.py", []),
]


def cmd_clean(args) -> None:
    scripts = _CLEAN_SCRIPTS
    if getattr(args, "script", None):
        # Run a single named script (match by basename)
        target = args.script if args.script.endswith(".py") else f"clean/{args.script}.py"
        scripts = [(s, extra) for s, extra in scripts if s == target or s.endswith(f"/{args.script}.py")]
        if not scripts:
            print(f"ERROR: '{args.script}' not in the clean pipeline. Available:")
            for s, _ in _CLEAN_SCRIPTS:
                print(f"  {s}")
            sys.exit(1)

    extra_flags: list[str] = []
    if not getattr(args, "csv", True):
        extra_flags.append("--no-csv")

    errors: list[str] = []
    for script, script_flags in scripts:
        sep = "-" * 60
        print(f"\n{sep}\n{script}\n{sep}")
        result = subprocess.run(
            [sys.executable, script] + script_flags + extra_flags,
            check=False,
        )
        if result.returncode != 0:
            errors.append(script)
            print(f"  WARNING: exited with code {result.returncode}")

    print(f"\n{'='*60}")
    if errors:
        print(f"Clean finished with errors in: {errors}")
    else:
        print(f"All {len(scripts)} clean script(s) completed successfully.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(prog="wrdsdl", description="WRDS data download pipeline")
    parser.add_argument("--config", default="config", help="Config directory (default: config)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pull = sub.add_parser("pull", help="Incremental pull of dataset(s)")
    p_pull.add_argument("dataset", nargs="?", help="Dataset name from manifest")
    p_pull.add_argument("--all", action="store_true", help="Pull every dataset in the manifest")

    p_refresh = sub.add_parser("refresh", help="Force full re-pull (ignores watermark)")
    p_refresh.add_argument("dataset", help="Dataset name")

    p_discover = sub.add_parser("discover", help="Explore WRDS library/table structure, IMF dataset codes, or BIS dataflows")
    p_discover.add_argument("library", help="WRDS library (e.g. comp, crsp), 'imf', or 'bis'")
    p_discover.add_argument("--table", help="Describe and sample a specific WRDS table")
    p_discover.add_argument("--dataset", help="IMF dataset code (e.g. BOP) or BIS dataflow (e.g. WS_DEBT_SEC2_PUB)")

    sub.add_parser("validate", help="Check subscriptions and schema against manifest")
    sub.add_parser("catalog", help="Show pull history from catalog")

    p_clean = sub.add_parser("clean", help="Run all (or one) clean scripts on already-pulled data")
    p_clean.add_argument("script", nargs="?", help="Run only this clean script (e.g. fx_spot or fx_spot.py)")
    p_clean.add_argument("--no-csv", action="store_false", dest="csv", help="Skip CSV output in all scripts")
    p_clean.set_defaults(csv=True)

    args = parser.parse_args()
    conn_config, datasets = load_config(args.config)
    storage_root = datasets[0].get("storage_root", "./data") if datasets else "./data"

    if args.command == "pull":
        if not getattr(args, "all", False) and not args.dataset:
            parser.error("Specify a dataset name or --all")
        cmd_pull(args, conn_config, datasets)
    elif args.command == "refresh":
        args.all = False
        state.clear_watermark(args.dataset, storage_root)
        cmd_pull(args, conn_config, datasets, force_full=True)
    elif args.command == "discover":
        cmd_discover(args, conn_config)
    elif args.command == "validate":
        cmd_validate(args, conn_config, datasets)
    elif args.command == "catalog":
        catalog.print_catalog(storage_root)
    elif args.command == "clean":
        cmd_clean(args)


if __name__ == "__main__":
    main()
