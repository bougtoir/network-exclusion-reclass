#!/usr/bin/env python3
"""Reconstruct external_threat from public historical-polity and conflict data.

Inputs:
- data/geo_and_capital_features.csv (capital_isolation, capital_lat/lon)
- data/polity_geometry_mapping.csv (period)
- data/raw/cliopatria.geojson (Seshat Cliopatria v0.0.1+, optional but recommended)
- data/raw/hced_events.csv (HCED conflict events, optional)

Outputs:
- data/external_threat_reconstructed.csv
- data/all_features.csv (merges geographic, capital, and external-threat features)
"""

import argparse
import csv
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CRS = "EPSG:6933"
BUFFER_KM = 1000
MAJOR_AREA_KM2 = 1_000_000


def parse_period(p: str) -> tuple[float, float] | None:
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
        return float(s)

    try:
        return (_year(parts[0]), _year(parts[1]))
    except ValueError:
        return None


def cliopatria_path() -> Path | None:
    raw = PROJECT_DIR / "data" / "raw"
    candidates = list(raw.rglob("cliopatria.geojson"))
    if candidates:
        return candidates[0]
    if (raw / "cliopatria.geojson").exists():
        return raw / "cliopatria.geojson"
    return None


def load_cliopatria(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    gdf = gdf[gdf["Type"] == "POLITY"].copy()
    gdf = gdf.to_crs(DEFAULT_CRS)
    gdf["key"] = gdf["SeshatID"].fillna(gdf["Name"]).astype(str)
    gdf["Area"] = pd.to_numeric(gdf["Area"], errors="coerce")
    gdf["FromYear"] = pd.to_numeric(gdf["FromYear"], errors="coerce")
    gdf["ToYear"] = pd.to_numeric(gdf["ToYear"], errors="coerce")
    gdf = gdf[gdf["FromYear"].notna() & gdf["ToYear"].notna()].copy()
    return gdf


def count_major_empires(
    gdf: gpd.GeoDataFrame,
    lat: float,
    lon: float,
    period: tuple[float, float],
    buffer_km: int = BUFFER_KM,
    area_threshold: float = MAJOR_AREA_KM2,
) -> float:
    """Mean number of distinct major polities within buffer_km across the period.

    Counts are averaged over ~50 sample years so that empires that existed at
    different times are not summed as if they were simultaneous threats.
    """
    if pd.isna(lat) or pd.isna(lon) or period is None:
        return 0.0
    p4326 = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
    p = p4326.to_crs(DEFAULT_CRS).iloc[0]
    buf = p.buffer(buffer_km * 1000)

    # Temporal filter first (fast)
    cand = gdf[
        (gdf["FromYear"] < period[1]) & (gdf["ToYear"] > period[0])
    ].copy()
    cand = cand[cand["Area"] >= area_threshold]
    if cand.empty:
        return 0.0

    # Spatial index
    hits = list(cand.sindex.intersection(buf.bounds))
    if not hits:
        return 0.0
    cand = cand.iloc[hits].copy()

    # Distance from capital to polygon; keep only external polities
    # (distance > 0 excludes the polity that contains the capital).
    cand["dist"] = cand.distance(p)
    cand = cand[(cand["dist"] > 0) & (cand["dist"] <= buffer_km * 1000)]
    if cand.empty:
        return 0.0

    # Sample up to ~50 years to compute the mean contemporaneous count
    start = math.floor(period[0])
    end = math.ceil(period[1])
    span = end - start
    if span <= 0:
        return 0.0
    step = max(1, span // 50)
    sample_years = list(range(start, end + 1, step))
    if sample_years[-1] != end:
        sample_years.append(end)

    keys = cand["key"].to_numpy()
    from_years = cand["FromYear"].to_numpy()
    to_years = cand["ToYear"].to_numpy()
    years_arr = np.array(sample_years, dtype=float)

    active = (from_years[:, None] <= years_arr) & (to_years[:, None] >= years_arr)
    counts = []
    for i in range(len(sample_years)):
        idx = np.where(active[:, i])[0]
        if len(idx) == 0:
            counts.append(0)
        else:
            counts.append(len(set(keys[idx])))
    return float(np.mean(counts))


def load_hced(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, encoding="utf-8-sig")
    # Flexible column mapping
    year_cols = [c for c in df.columns if c.lower() in {"year", "date", "startyear", "start_year"}]
    lat_cols = [c for c in df.columns if c.lower() in {"lat", "latitude"}]
    lon_cols = [c for c in df.columns if c.lower() in {"lon", "long", "longitude"}]
    if not (year_cols and lat_cols and lon_cols):
        print(
            f"Warning: HCED file {path} missing expected year/lat/lon columns",
            file=sys.stderr,
        )
        return None
    df["hced_year"] = pd.to_numeric(df[year_cols[0]], errors="coerce")
    df["hced_lat"] = pd.to_numeric(df[lat_cols[0]], errors="coerce")
    df["hced_lon"] = pd.to_numeric(df[lon_cols[0]], errors="coerce")
    df = df[df["hced_year"].notna() & df["hced_lat"].notna() & df["hced_lon"].notna()].copy()
    return df


def hced_conflict_threat(
    df: pd.DataFrame,
    lat: float,
    lon: float,
    period: tuple[float, float],
    buffer_km: int = BUFFER_KM,
) -> float:
    if pd.isna(lat) or pd.isna(lon):
        return 0.0
    p4326 = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
    p = p4326.to_crs(DEFAULT_CRS).iloc[0]
    buf = p.buffer(buffer_km * 1000)

    sub = df[(df["hced_year"] >= period[0]) & (df["hced_year"] <= period[1])].copy()
    if sub.empty:
        return 0.0
    pts = gpd.GeoDataFrame(
        sub, geometry=gpd.points_from_xy(sub["hced_lon"], sub["hced_lat"]), crs="EPSG:4326"
    ).to_crs(DEFAULT_CRS)
    pts["dist"] = pts.distance(p)
    n_events = int((pts["dist"] <= buffer_km * 1000).sum())
    period_length = max(1.0, period[1] - period[0])
    events_per_100yr = n_events / period_length * 100.0
    return float(1.0 - math.exp(-events_per_100yr / 2.0))


def compute_external_threat(
    features: pd.DataFrame,
    periods: dict[str, tuple[float, float]],
    clio_gdf: gpd.GeoDataFrame | None,
    hced_df: pd.DataFrame | None,
    buffer_km: int = BUFFER_KM,
    area_threshold: float = MAJOR_AREA_KM2,
) -> pd.DataFrame:
    rows = []
    for _, row in features.iterrows():
        entity = row["entity"]
        period = periods.get(entity)
        lat = row.get("capital_lat")
        lon = row.get("capital_lon")
        cap_iso = row.get("capital_isolation")

        capital_prox = 1.0 - cap_iso if pd.notna(cap_iso) else None

        major_count = 0
        major_threat = 0.0
        if clio_gdf is not None and period is not None and pd.notna(lat) and pd.notna(lon):
            major_count = count_major_empires(
                clio_gdf, lat, lon, period, buffer_km, area_threshold
            )
            major_threat = 1.0 - math.exp(-major_count / 2.0)

        hced_threat_val = None
        if hced_df is not None and period is not None and pd.notna(lat) and pd.notna(lon):
            hced_threat_val = hced_conflict_threat(hced_df, lat, lon, period, buffer_km)

        components = []
        if capital_prox is not None:
            components.append(capital_prox)
        if major_threat:
            components.append(major_threat)
        if hced_threat_val is not None:
            components.append(hced_threat_val)

        if components:
            external = 1.0 - math.prod([1.0 - c for c in components])
        else:
            external = None

        rows.append(
            {
                "entity": entity,
                "capital_proximity_threat": round(capital_prox, 4) if capital_prox is not None else None,
                "n_major_empires_1000km": round(major_count, 4),
                "major_empire_threat": round(major_threat, 4),
                "hced_conflict_threat": round(hced_threat_val, 4) if hced_threat_val is not None else None,
                "external_threat": round(external, 4) if external is not None else None,
            }
        )
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--features",
        default=str(PROJECT_DIR / "data" / "geo_and_capital_features.csv"),
    )
    parser.add_argument(
        "--capitals",
        default=str(PROJECT_DIR / "data" / "capitals.csv"),
        help="Capital coordinates (must contain capital_lat and capital_lon)",
    )
    parser.add_argument(
        "--mapping",
        default=str(PROJECT_DIR / "data" / "polity_geometry_mapping.csv"),
    )
    parser.add_argument(
        "--cliopatria",
        default=None,
        help="Path to cliopatria.geojson (defaults to data/raw/**/cliopatria.geojson)",
    )
    parser.add_argument(
        "--hced",
        default=str(PROJECT_DIR / "data" / "raw" / "hced_events.csv"),
    )
    parser.add_argument(
        "--buffer-km",
        type=int,
        default=BUFFER_KM,
    )
    parser.add_argument(
        "--major-area-km2",
        type=float,
        default=MAJOR_AREA_KM2,
    )
    parser.add_argument(
        "--output-external",
        default=str(PROJECT_DIR / "data" / "external_threat_reconstructed.csv"),
    )
    parser.add_argument(
        "--output-all",
        default=str(PROJECT_DIR / "data" / "all_features.csv"),
    )
    args = parser.parse_args()

    features_path = Path(args.features)
    if not features_path.exists():
        print(f"Error: features file not found: {features_path}", file=sys.stderr)
        sys.exit(1)
    features = pd.read_csv(features_path, encoding="utf-8-sig")

    capitals_path = Path(args.capitals)
    if not capitals_path.exists():
        print(f"Error: capitals file not found: {capitals_path}", file=sys.stderr)
        sys.exit(1)
    capitals = pd.read_csv(capitals_path, encoding="utf-8-sig")
    features = features.merge(
        capitals[["entity", "capital_name", "capital_lat", "capital_lon"]],
        on="entity",
        how="left",
    )

    periods = {}
    with open(args.mapping, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            p = parse_period(r["period"])
            if p:
                periods[r["entity"].strip()] = p

    missing_period = set(features["entity"]) - set(periods.keys())
    if missing_period:
        print(f"Warning: no parseable period for {len(missing_period)} entities", file=sys.stderr)

    clio_path = Path(args.cliopatria) if args.cliopatria else cliopatria_path()
    clio_gdf = None
    if clio_path and clio_path.exists():
        print(f"Loading Cliopatria from {clio_path}", file=sys.stderr)
        clio_gdf = load_cliopatria(clio_path)
        print(f"  {len(clio_gdf)} POLITY rows", file=sys.stderr)
    else:
        print(
            "Warning: Cliopatria geojson not found. Major-empire threat will be missing.\n"
            "Download from https://zenodo.org/records/13363121 and unzip into data/raw/",
            file=sys.stderr,
        )

    hced_df = load_hced(Path(args.hced))
    if hced_df is not None:
        print(f"Loaded HCED events: {len(hced_df)} rows", file=sys.stderr)
    else:
        print(
            "Info: HCED events file not found at data/raw/hced_events.csv; "
            "HCED conflict threat omitted.",
            file=sys.stderr,
        )

    external_df = compute_external_threat(
        features,
        periods,
        clio_gdf,
        hced_df,
        buffer_km=args.buffer_km,
        area_threshold=args.major_area_km2,
    )

    external_path = Path(args.output_external)
    external_df.to_csv(external_path, index=False, encoding="utf-8-sig")
    print(f"Wrote {external_path}", file=sys.stderr)

    all_features = features.merge(external_df, on="entity", how="left")
    all_path = Path(args.output_all)
    all_features.to_csv(all_path, index=False, encoding="utf-8-sig")
    print(f"Wrote {all_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
