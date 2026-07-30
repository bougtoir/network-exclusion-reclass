#!/usr/bin/env python3
"""Reconstruct regime_duration_yrs from the period column.

regime_duration_yrs is the numeric duration of the polity/period in years.
The period string is expected to be of the form:
    BC550-BC330, AD1804-AD1815, BC509-AD200, etc.
For ongoing polities whose period ends with "現在", the duration is computed
from the start year to the current calendar year and is flagged for review.
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent


def parse_year(s: str) -> int:
    s = s.strip()
    if s.startswith("BC"):
        return -int(s[2:])
    if s.startswith("AD"):
        return int(s[2:])
    if s.startswith("現在"):
        return datetime.now().year
    # Fallback for plain integers
    return int(s)


def parse_period(period: str) -> tuple[int | None, int | None]:
    if not period or pd.isna(period):
        return None, None
    period = str(period).strip()
    parts = [p.strip() for p in period.split("-")]
    if len(parts) != 2:
        return None, None
    try:
        return parse_year(parts[0]), parse_year(parts[1])
    except ValueError:
        return None, None


def compute_duration(period: str) -> tuple[int | None, bool]:
    """Return (duration_years, is_ongoing_or_uncertain)."""
    start, end = parse_period(period)
    if start is None or end is None:
        return None, True
    if "現在" in str(period):
        return end - start, True
    return end - start, False


def main():
    parser = argparse.ArgumentParser(description="Reconstruct regime_duration_yrs from period strings")
    parser.add_argument(
        "--input",
        default=str(PROJECT_DIR / "data" / "all_features.csv"),
        help="Input CSV containing a 'period' column",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_DIR / "data" / "regime_duration_reconstructed.csv"),
        help="Output CSV for regime_duration_yrs",
    )
    parser.add_argument(
        "--all-features-out",
        default=str(PROJECT_DIR / "data" / "all_features.csv"),
        help="CSV to update with the new regime_duration_yrs column",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input, encoding="utf-8-sig", dtype=str)
    # Ensure peak_year numeric for reference
    if "peak_year" in df.columns:
        df["peak_year"] = pd.to_numeric(df["peak_year"], errors="coerce")

    durations: list[int | None] = []
    ongoing_flags: list[bool] = []
    for period in df["period"]:
        dur, is_ongoing = compute_duration(period)
        durations.append(dur)
        ongoing_flags.append(is_ongoing)

    out = pd.DataFrame(
        {
            "entity": df["entity"],
            "period": df["period"],
            "peak_year": df.get("peak_year"),
            "regime_duration_yrs": durations,
            "duration_is_ongoing_or_uncertain": ongoing_flags,
        }
    )
    out.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Wrote {args.output}", file=sys.stderr)

    # Merge into the all-features CSV
    all_features_path = Path(args.all_features_out)
    if all_features_path.exists():
        features = pd.read_csv(all_features_path, encoding="utf-8-sig")
        for col in ["regime_duration_yrs", "duration_is_ongoing_or_uncertain"]:
            if col in features.columns:
                features = features.drop(columns=[col])
        features = features.merge(
            out[["entity", "regime_duration_yrs", "duration_is_ongoing_or_uncertain"]],
            on="entity",
            how="left",
        )
        features.to_csv(all_features_path, index=False, encoding="utf-8-sig")
        print(f"Updated {all_features_path}", file=sys.stderr)

    # Basic summary
    valid = out["regime_duration_yrs"].dropna()
    print(f"Duration range: {int(valid.min())} to {int(valid.max())} years", file=sys.stderr)
    print(f"Mean: {valid.mean():.1f}, Median: {valid.median():.1f}", file=sys.stderr)
    print(f"Ongoing/uncertain: {sum(ongoing_flags)}", file=sys.stderr)


if __name__ == "__main__":
    main()
