#!/usr/bin/env python3
"""Compute inter-capital distance metrics for contemporaneous polities.

Reads:
- data/capitals.csv (entity, capital_name, capital_lat, capital_lon)
- data/polity_geometry_mapping.csv (entity, period)

Produces:
- data/capital_distance_metrics.csv with, for each polity:
    * n_contemporary_polities
    * min_neighbor_capital_distance_km
    * mean_neighbor_capital_distance_km
    * median_neighbor_capital_distance_km
    * n_neighbors within 500/1000/1500/2000 km
    * capital_isolation (1 - exp(-min_distance / 1000))

Optionally merges these columns into geo_barrier_reconstructed.csv and writes
a combined data/geo_and_capital_features.csv.

Great-circle distances use the haversine formula with the mean Earth radius
(6,371 km).
"""

import argparse
import csv
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
EARTH_RADIUS_KM = 6371.0


def parse_period(p: str) -> tuple[float, float] | None:
    """Convert 'BC550-BC330' or 'AD200-AD476' to numeric year range.

    BC years are negative and AD years are positive; there is no year 0.
    """
    if not p or not str(p).strip():
        return None
    p = str(p).strip()
    parts = p.split("-")
    if len(parts) != 2:
        return None

    def _year(s: str) -> float:
        s = s.strip()
        if s.startswith("BC"):
            return -float(s[2:])
        if s.startswith("AD"):
            return float(s[2:])
        # Fallback: plain number interpreted as AD
        return float(s)

    try:
        start = _year(parts[0])
        end = _year(parts[1])
    except ValueError:
        return None
    return (start, end)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def compute_metrics(
    capitals_df: pd.DataFrame, periods: dict[str, tuple[float, float]]
) -> pd.DataFrame:
    """Compute distance metrics for each polity against its contemporaries."""
    records = capitals_df.to_dict(orient="records")

    metrics = []
    for i, row in enumerate(records):
        entity = row["entity"]
        lat_i = row["capital_lat"]
        lon_i = row["capital_lon"]
        period_i = periods.get(entity)

        distances = []
        for j, other in enumerate(records):
            if i == j:
                continue
            period_j = periods.get(other["entity"])
            if period_i is None or period_j is None:
                continue
            # Contemporaneous if intervals overlap with positive duration
            if max(period_i[0], period_j[0]) >= min(period_i[1], period_j[1]):
                continue
            # Skip pairs that share the exact same capital; this avoids
            # split-period duplicates and non-rival same-city observations
            # (e.g. British Empire and Imperial Preference, both London).
            if (row["capital_name"], lat_i, lon_i) == (
                other["capital_name"],
                other["capital_lat"],
                other["capital_lon"],
            ):
                continue
            # Skip if either coordinate is missing
            if pd.isna(lat_i) or pd.isna(lon_i) or pd.isna(other["capital_lat"]) or pd.isna(other["capital_lon"]):
                continue
            d = haversine(lat_i, lon_i, other["capital_lat"], other["capital_lon"])
            distances.append(d)

        if not distances:
            metrics.append(
                {
                    "entity": entity,
                    "n_contemporary_polities": 0,
                    "min_neighbor_capital_distance_km": None,
                    "mean_neighbor_capital_distance_km": None,
                    "median_neighbor_capital_distance_km": None,
                    "n_neighbors_500km": 0,
                    "n_neighbors_1000km": 0,
                    "n_neighbors_1500km": 0,
                    "n_neighbors_2000km": 0,
                    "capital_isolation": None,
                }
            )
            continue

        distances.sort()
        n = len(distances)
        mean_d = sum(distances) / n
        median_d = distances[n // 2] if n % 2 == 1 else (distances[n // 2 - 1] + distances[n // 2]) / 2
        min_d = distances[0]
        isolation = 1.0 - math.exp(-min_d / 1000.0)
        metrics.append(
            {
                "entity": entity,
                "n_contemporary_polities": n,
                "min_neighbor_capital_distance_km": round(min_d, 2),
                "mean_neighbor_capital_distance_km": round(mean_d, 2),
                "median_neighbor_capital_distance_km": round(median_d, 2),
                "n_neighbors_500km": sum(1 for d in distances if d <= 500),
                "n_neighbors_1000km": sum(1 for d in distances if d <= 1000),
                "n_neighbors_1500km": sum(1 for d in distances if d <= 1500),
                "n_neighbors_2000km": sum(1 for d in distances if d <= 2000),
                "capital_isolation": round(isolation, 4),
            }
        )

    return pd.DataFrame(metrics)


def load_periods(mapping_path: Path) -> dict[str, tuple[float, float]]:
    periods: dict[str, tuple[float, float]] = {}
    with mapping_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entity = row["entity"].strip()
            parsed = parse_period(row.get("period", ""))
            if parsed is not None:
                periods[entity] = parsed
    return periods


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--capitals",
        default=PROJECT_DIR / "data" / "capitals.csv",
        help="Capital coordinates CSV",
    )
    parser.add_argument(
        "--mapping",
        default=PROJECT_DIR / "data" / "polity_geometry_mapping.csv",
        help="CSV with entity -> period",
    )
    parser.add_argument(
        "--geo",
        default=PROJECT_DIR / "data" / "geo_barrier_reconstructed.csv",
        help="Geo barrier CSV to merge with (optional)",
    )
    parser.add_argument(
        "--output-metrics",
        default=PROJECT_DIR / "data" / "capital_distance_metrics.csv",
        help="Output CSV for capital distance metrics",
    )
    parser.add_argument(
        "--output-merged",
        default=PROJECT_DIR / "data" / "geo_and_capital_features.csv",
        help="Merged output CSV (geo + capital)",
    )
    args = parser.parse_args()

    capitals_path = Path(args.capitals)
    if not capitals_path.exists():
        print(f"Error: capitals file not found: {capitals_path}", file=sys.stderr)
        sys.exit(1)

    capitals_df = pd.read_csv(capitals_path, encoding="utf-8-sig")
    if "capital_lat" not in capitals_df.columns or "capital_lon" not in capitals_df.columns:
        print("Error: capitals.csv must contain capital_lat and capital_lon", file=sys.stderr)
        sys.exit(1)

    mapping_path = Path(args.mapping)
    if not mapping_path.exists():
        print(f"Error: mapping file not found: {mapping_path}", file=sys.stderr)
        sys.exit(1)

    periods = load_periods(mapping_path)
    print(f"Loaded {len(periods)} period records", file=sys.stderr)

    metrics_df = compute_metrics(capitals_df, periods)

    out_metrics = Path(args.output_metrics)
    metrics_df.to_csv(out_metrics, index=False, encoding="utf-8-sig")
    print(f"Wrote {out_metrics}", file=sys.stderr)

    geo_path = Path(args.geo)
    if geo_path.exists():
        geo_df = pd.read_csv(geo_path, encoding="utf-8-sig")
        merged = geo_df.merge(metrics_df, on="entity", how="left")

        # Composite geographic + capital-isolation barriers
        if "geo_barrier" in merged.columns and "capital_isolation" in merged.columns:
            g = merged["geo_barrier"]
            c = merged["capital_isolation"]
            # combined_barrier is intentionally omitted because its form
            # (1 - (1-g)(1-c)) overlaps conceptually with external threat.
            merged["weighted_barrier"] = 0.5 * g + 0.5 * c
            merged["geometric_barrier"] = np.sqrt(g * c)
            merged["harmonic_barrier"] = np.where(
                (g + c) > 0,
                2.0 * g * c / (g + c),
                np.where((g + c) == 0, 0.0, np.nan),
            )
            # Round to keep CSV tidy
            for col in ["weighted_barrier", "geometric_barrier", "harmonic_barrier"]:
                merged[col] = merged[col].round(4)

        merged_path = Path(args.output_merged)
        merged.to_csv(merged_path, index=False, encoding="utf-8-sig")
        print(f"Wrote {merged_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
