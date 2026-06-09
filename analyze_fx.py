"""Compute distribution stats of daily FX log changes and write text reports.

Input is expected to be a wide CSV with columns:
    date, <CURRENCY_1>, <CURRENCY_2>, ...
where currency columns are levels in local currency per USD.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_INPUT = "fx_daily.csv"
DEFAULT_OUTPUT_ALL = "fx_log_change_stats_all.txt"
DEFAULT_OUTPUT_SUBSET = "fx_log_change_stats_subset.txt"
DEFAULT_OUTPUT_MOVEMENTS = "fx_large_movement_dates.txt"
DEFAULT_SUBSET = [
    "AUD",
    "NZD",
    "NOK",
    "SEK",
    "GBP",
    "EUR",
    "CAD",
    "JPY",
    "RUB",
    "CHF",
]
PERCENTILES = [1, 2, 5, 10, 25, 50, 75, 90, 95, 98, 99]
DEFAULT_MOVEMENT_THRESHOLD = 0.01


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute percentile and moment stats for daily FX log changes."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help=f"Input CSV path (default: {DEFAULT_INPUT})")
    parser.add_argument(
        "--output-all",
        default=DEFAULT_OUTPUT_ALL,
        help=f"Output TXT for all currencies (default: {DEFAULT_OUTPUT_ALL})",
    )
    parser.add_argument(
        "--output-subset",
        default=DEFAULT_OUTPUT_SUBSET,
        help=f"Output TXT for subset currencies (default: {DEFAULT_OUTPUT_SUBSET})",
    )
    parser.add_argument(
        "--output-movements",
        default=DEFAULT_OUTPUT_MOVEMENTS,
        help=f"Output TXT for large movement dates (default: {DEFAULT_OUTPUT_MOVEMENTS})",
    )
    parser.add_argument(
        "--subset",
        nargs="+",
        default=DEFAULT_SUBSET,
        help="Subset currency list for second report.",
    )
    parser.add_argument(
        "--movement-threshold",
        type=float,
        default=DEFAULT_MOVEMENT_THRESHOLD,
        help=f"Absolute daily movement threshold for date lists (default: {DEFAULT_MOVEMENT_THRESHOLD}).",
    )
    parser.add_argument(
        "--keep-weekends",
        action="store_true",
        help="Keep weekend rows (default behavior is to exclude Saturdays and Sundays).",
    )
    parser.add_argument(
        "--density-dir",
        default="densities",
        help="Directory where subset-currency density PDFs are written (default: densities).",
    )
    return parser.parse_args()


def filter_to_weekdays(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Return dataframe filtered to weekdays when a valid date column is present."""
    if "date" not in df.columns:
        return df, False

    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"]).sort_values("date")
    out = out[out["date"].dt.weekday < 5]
    return out, True


def compute_log_change_stats(series: pd.Series) -> dict[str, float]:
    values = pd.to_numeric(series, errors="coerce")
    values = values.where(values > 0)
    log_changes = np.log(values).diff().dropna()

    stats: dict[str, float] = {}
    for p in PERCENTILES:
        stats[f"p{p:02d}"] = float(log_changes.quantile(p / 100)) if not log_changes.empty else np.nan

    stats["mean"] = float(log_changes.mean()) if not log_changes.empty else np.nan
    stats["std"] = float(log_changes.std(ddof=1)) if len(log_changes) > 1 else np.nan
    stats["skewness"] = float(log_changes.skew()) if len(log_changes) > 2 else np.nan
    stats["kurtosis"] = float(log_changes.kurt()) if len(log_changes) > 3 else np.nan
    stats["n_log_changes"] = float(len(log_changes))

    return stats


def compute_daily_percent_changes(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    values = values.where(values > 0)
    return values.pct_change().dropna()


def build_stats_table(df: pd.DataFrame, currencies: list[str]) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []

    for ccy in currencies:
        row: dict[str, float | str] = {"currency": ccy}
        if ccy in df.columns:
            row.update(compute_log_change_stats(df[ccy]))
        else:
            for p in PERCENTILES:
                row[f"p{p:02d}"] = np.nan
            row["mean"] = np.nan
            row["std"] = np.nan
            row["skewness"] = np.nan
            row["kurtosis"] = np.nan
            row["n_log_changes"] = 0.0
        rows.append(row)

    return pd.DataFrame(rows)


def write_report(path: Path, stats_df: pd.DataFrame, title: str) -> None:
    ordered_cols = ["currency"] + [f"p{p:02d}" for p in PERCENTILES] + [
        "mean",
        "std",
        "skewness",
        "kurtosis",
        "n_log_changes",
    ]

    report_df = stats_df[ordered_cols].copy()
    report_df["n_log_changes"] = report_df["n_log_changes"].fillna(0).astype(int)

    with path.open("w", encoding="utf-8") as f:
        f.write(title + "\n")
        f.write("Daily log change = log(level_t) - log(level_{t-1})\n\n")
        f.write(report_df.to_string(index=False, float_format=lambda x: f"{x:.8f}"))
        f.write("\n")


def write_density_plots(df: pd.DataFrame, currencies: list[str], out_dir: Path, weekdays_only: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    for ccy in currencies:
        if ccy not in df.columns:
            print(f"Skipping density for {ccy}: not in input columns")
            continue

        values = pd.to_numeric(df[ccy], errors="coerce")
        values = values.where(values > 0)
        log_changes = np.log(values).diff().dropna()

        if log_changes.empty:
            print(f"Skipping density for {ccy}: no valid log-change observations")
            continue

        fig, ax = plt.subplots(figsize=(8.5, 5.0))

        counts, edges = np.histogram(log_changes.to_numpy(), bins=80, density=True)
        centers = (edges[:-1] + edges[1:]) / 2

        ax.hist(log_changes.to_numpy(), bins=80, density=True, alpha=0.28, color="#4C72B0", edgecolor="none")
        ax.plot(centers, counts, color="#1F3A93", linewidth=1.5)

        subtitle = "weekdays only" if weekdays_only else "including weekends"
        ax.set_title(f"{ccy}: density of daily log FX changes ({subtitle})")
        ax.set_xlabel("Daily log change")
        ax.set_ylabel("Density")
        ax.grid(True, alpha=0.2)

        out_path = out_dir / f"{ccy}_density.pdf"
        fig.tight_layout()
        fig.savefig(out_path, format="pdf")
        plt.close(fig)


def write_large_movement_report(path: Path, df: pd.DataFrame, currencies: list[str], threshold: float) -> None:
    date_to_currencies: dict[pd.Timestamp, list[tuple[str, float]]] = {}
    currency_to_dates: list[tuple[str, list[tuple[pd.Timestamp, float]]]] = []

    for ccy in currencies:
        if ccy not in df.columns or "date" not in df.columns:
            currency_to_dates.append((ccy, []))
            continue

        working = df[["date", ccy]].copy()
        working["change"] = compute_daily_percent_changes(working[ccy])
        working = working.dropna(subset=["change"])
        hits = working[working["change"].abs() > threshold][["date", "change"]]

        currency_hits: list[tuple[pd.Timestamp, float]] = []
        for row in hits.itertuples(index=False):
            date_value = pd.Timestamp(row.date)
            change_value = float(row.change)
            currency_hits.append((date_value, change_value))
            date_to_currencies.setdefault(date_value, []).append((ccy, change_value))

        currency_hits.sort(key=lambda item: item[0])
        currency_to_dates.append((ccy, currency_hits))

    sorted_dates = sorted(date_to_currencies.items(), key=lambda item: item[0])

    with path.open("w", encoding="utf-8") as f:
        f.write(f"Dates with absolute daily movement greater than {threshold:.2%}\n")
        f.write("Daily movement = level_t / level_{t-1} - 1\n\n")

        for ccy, hits in currency_to_dates:
            f.write(f"{ccy}:\n")
            if not hits:
                f.write("  none\n\n")
                continue

            dates_text = ", ".join(
                f"{date_value.date().isoformat()} ({change_value:+.4%})" for date_value, change_value in hits
            )
            f.write(f"  {dates_text}\n\n")

        f.write("Date counts across currencies:\n")
        if not sorted_dates:
            f.write("  none\n")
            return

        for date_value, entries in sorted_dates:
            f.write(f"  {date_value.date().isoformat()}: {len(entries)} currencies\n")


def main() -> None:
    args = parse_args()

    df = pd.read_csv(args.input)
    weekend_adjusted = False
    if not args.keep_weekends:
        df, weekend_adjusted = filter_to_weekdays(df)

    currencies = sorted([c for c in df.columns if c.lower() != "date"])

    all_stats = build_stats_table(df, currencies)
    subset_upper = [c.upper() for c in args.subset]
    subset_stats = build_stats_table(df, subset_upper)

    write_report(
        Path(args.output_all),
        all_stats,
        title=(
            "Distribution statistics of daily log FX changes (all currencies, weekdays only)"
            if weekend_adjusted
            else "Distribution statistics of daily log FX changes (all currencies)"
        ),
    )
    write_report(
        Path(args.output_subset),
        subset_stats,
        title=(
            "Distribution statistics of daily log FX changes (subset, weekdays only)"
            if weekend_adjusted
            else "Distribution statistics of daily log FX changes (subset)"
        ),
    )

    write_density_plots(
        df=df,
        currencies=subset_upper,
        out_dir=Path(args.density_dir),
        weekdays_only=weekend_adjusted,
    )

    write_large_movement_report(
        Path(args.output_movements),
        df=df,
        currencies=subset_upper,
        threshold=args.movement_threshold,
    )

    print(f"Wrote: {args.output_all}")
    print(f"Wrote: {args.output_subset}")
    print(f"Wrote: {args.output_movements}")
    print(f"Wrote density PDFs to: {args.density_dir}")


if __name__ == "__main__":
    main()
