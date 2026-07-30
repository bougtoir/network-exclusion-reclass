#!/usr/bin/env python3
"""Reconstruct geo_barrier from public geographic data.

Uses:
- Natural Earth 1:10m admin-0 countries for boundary/geometry
- Natural Earth 1:10m admin-1 provinces for subnational territory proxies
- Nunn-Puga (2012) country-level terrain ruggedness for ruggedness

For each polity, the mapping CSV specifies one or more ISO 3166-1 alpha-3
codes and/or admin-1 codes (COUNTRY:ProvinceName or ISO_3166-2) that
approximate the polity's peak territory. Admin-1 codes override the ISO
codes when a more precise subnational proxy is available (e.g. Manchukuo,
East Germany, Hawaii, Ryukyu, Zulu kingdom, South Vietnam).

The script computes:
- coastline_share: share of the union boundary that is coastline (not shared
  with another modern country or province)
- rugged_norm: area-weighted Nunn-Puga ruggedness, normalized to [0, 1]
- geo_barrier: 1 - (1 - coastline_share) * (1 - rugged_norm)

This is a first-pass, source-anchored reconstruction. Empire mappings should
be reviewed.
"""

import argparse
import csv
import sys
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid

PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_DIR / "data" / "raw"
DEFAULT_CRS = "EPSG:6933"  # NSIDC EASE-Grid 2.0 Global, equal area

NE_10M_COUNTRIES_URL = (
    "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip"
)
NE_10M_ADMIN1_URL = (
    "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_1_states_provinces.zip"
)
NUNN_PUGA_URL = "https://diegopuga.org/data/rugged/rugged_data.zip"

ISO_CODE_FIXES = {
    "ROM": "ROU",
    "ZAR": "COD",
    "TAN": "TZA",
    "SUD": "SDN",
    "YUG": "SRB",
    "SCG": "SRB",
    "ESH": "SAH",
    "PSE": "PSX",
    "HKG": "CHN",
    "MAC": "CHN",
    "GRL": "DNK",
    "FRO": "DNK",
}


def cache_file(url: str, filename: str, raw_dir: Path = RAW_DIR) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / filename
    if not path.exists():
        print(f"Downloading {url} ...", file=sys.stderr)
        urllib.request.urlretrieve(url, path)
    return path


def load_countries() -> gpd.GeoDataFrame:
    zip_path = cache_file(NE_10M_COUNTRIES_URL, "ne_10m_admin_0_countries.zip")
    gdf = gpd.read_file(f"zip://{zip_path}")
    # Fix known ISO code issues and drop rows without an ISO code.
    gdf["ADM0_A3"] = gdf["ADM0_A3"].replace({"-99": None})
    gdf = gdf[gdf["ADM0_A3"].notna()].copy()
    gdf = gdf.to_crs(DEFAULT_CRS)
    gdf["geometry"] = gdf.geometry.apply(make_valid)
    return gdf


def load_admin1() -> gpd.GeoDataFrame:
    zip_path = cache_file(NE_10M_ADMIN1_URL, "ne_10m_admin_1_states_provinces.zip")
    gdf = gpd.read_file(f"zip://{zip_path}")
    gdf = gdf.to_crs(DEFAULT_CRS)
    gdf["adm0_a3"] = gdf["adm0_a3"].replace({"-99": None})
    gdf = gdf[gdf["adm0_a3"].notna()].copy()
    gdf["name"] = gdf["name"].fillna("")
    gdf["name_en"] = gdf["name_en"].fillna("")
    gdf["iso_3166_2"] = gdf["iso_3166_2"].fillna("")
    gdf["geometry"] = gdf.geometry.apply(make_valid)
    return gdf


def load_ruggedness() -> tuple[pd.DataFrame, float]:
    zip_path = cache_file(NUNN_PUGA_URL, "rugged_data.zip")
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("rugged_data.csv") as f:
            df = pd.read_csv(f, encoding="latin1")
    df["iso3"] = df["isocode"].replace(ISO_CODE_FIXES)
    # Nunn-Puga area is in 1,000 sq km per the documentation.
    df["land_area"] = pd.to_numeric(df["land_area"], errors="coerce")
    # ISO_CODE_FIXES can map multiple original codes (e.g. HKG, MAC -> CHN;
    # GRL, FRO -> DNK) to the same iso3. Aggregate them first so that the
    # country-level ruggedness value is a land_area-weighted average and so
    # that later area-weighted averaging does not double-count rows.
    valid = df[df["land_area"].notna() & df["rugged"].notna()].copy()
    def _weighted(g):
        return pd.Series(
            {
                "rugged": float(np.average(g["rugged"], weights=g["land_area"])),
                "land_area": float(g["land_area"].sum()),
            }
        )
    rugged_df = valid.groupby("iso3", as_index=False).apply(_weighted, include_groups=False)
    # Normalize by the 90th percentile to avoid letting tiny outlier territories
    # (e.g. Gibraltar) dominate the 0-1 scale.
    max_rugged = float(rugged_df["rugged"].quantile(0.90))
    return rugged_df, max_rugged


def parse_codes(codes_str: str) -> list[str]:
    if not codes_str or not str(codes_str).strip():
        return []
    return [c.strip().upper() for c in codes_str.split("|") if c.strip()]


def select_admin1(
    admin1_tokens: list[str],
    admin1_gdf: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Select admin-1 polygons by ISO 3166-2 code or COUNTRY:Name pattern.

    Name matching is exact first (lower-cased full match against name/name_en);
    if there is no exact hit, it falls back to partial/substring matching and
    prints a warning. After concatenating selections from multiple tokens,
    duplicate rows (same Natural Earth feature index) are removed so the same
    province is not counted twice.
    """
    if not admin1_tokens:
        return admin1_gdf.iloc[0:0].copy()

    selected = []
    for token in admin1_tokens:
        token = token.strip()
        if ":" in token:
            country, name = token.split(":", 1)
            country = country.strip().upper()
            name = name.strip()
            country_match = (
                (admin1_gdf["adm0_a3"].str.upper() == country)
                | (admin1_gdf["admin"].str.upper() == country)
                | (admin1_gdf["geonunit"].str.upper() == country)
            )
            exact_name_match = (
                (admin1_gdf["name"].str.lower() == name.lower())
                | (admin1_gdf["name_en"].str.lower() == name.lower())
            )
            sel = admin1_gdf[country_match & exact_name_match].copy()
            if sel.empty:
                partial_name_match = (
                    admin1_gdf["name"].str.contains(name, case=False, na=False)
                    | admin1_gdf["name_en"].str.contains(name, case=False, na=False)
                )
                sel = admin1_gdf[country_match & partial_name_match].copy()
                if not sel.empty:
                    print(
                        f"  Warning: partial admin-1 match for token '{token}'; "
                        f"matched {len(sel)} row(s)",
                        file=sys.stderr,
                    )
        else:
            # Treat as ISO 3166-2 code
            sel = admin1_gdf[admin1_gdf["iso_3166_2"].str.upper() == token].copy()
        if sel.empty:
            print(f"  Warning: admin-1 token not matched: {token}", file=sys.stderr)
        selected.append(sel)

    if not selected:
        return admin1_gdf.iloc[0:0].copy()
    combined = pd.concat(selected, ignore_index=False)
    combined = combined[~combined.index.duplicated(keep="first")]
    return gpd.GeoDataFrame(combined)


def _polygon_area_by_iso(geom, iso: str, area_dict: dict) -> None:
    """Add polygon area to area_dict keyed by ISO, handling multipart geometries."""
    if geom.is_empty:
        return
    area_dict[iso] = area_dict.get(iso, 0.0) + float(geom.area)


def _add_land_border(union, other_geom, land_total: float, tolerance: float = 500.0) -> float:
    """Add shared boundary length between union and a neighbouring geometry.

    A small buffer is applied to the neighbour boundary because make_valid /
    unary_union can introduce sub-metre coordinate rounding; exact line-line
    intersection would then miss valid shared frontiers.  The buffer length is
    negligible compared with continental coastlines, so coastline_share remains
    well-defined.
    """
    other_geom = make_valid(other_geom)
    if other_geom.is_empty:
        return land_total
    # Buffer the neighbour's boundary and intersect with the union's boundary.
    boundary_buf = other_geom.boundary.buffer(tolerance)
    inter = union.boundary.intersection(boundary_buf)
    if not inter.is_empty:
        land_total += float(inter.length)
    return land_total


def compute_one(
    entity: str,
    iso_codes: list[str],
    admin1_tokens: list[str],
    countries: gpd.GeoDataFrame,
    admin1_gdf: gpd.GeoDataFrame,
    rugged_df: pd.DataFrame,
    max_rugged: float,
) -> dict:
    admin1_sel = select_admin1(admin1_tokens, admin1_gdf)
    # Admin-1 selections are used for the host country(ies); full ISO polygons
    # are used for the remaining ISO codes in the same row. This lets a single
    # entry mix fine-grained provinces (e.g. Italian core of Venice) with
    # full-country proxies (e.g. Cyprus).
    host_adm0 = (
        set(admin1_sel["adm0_a3"].str.upper().tolist())
        if not admin1_sel.empty
        else set()
    )
    country_sel = countries[
        countries["ADM0_A3"].isin(set(iso_codes) - host_adm0)
    ].copy()
    missing_iso = set(iso_codes) - host_adm0 - set(country_sel["ADM0_A3"])
    if missing_iso:
        print(
            f"  Warning [{entity}]: ISO codes not in Natural Earth: {missing_iso}",
            file=sys.stderr,
        )

    if admin1_sel.empty and country_sel.empty:
        return {
            "entity": entity,
            "iso_count": 0,
            "admin1_count": 0,
            "total_boundary_km": None,
            "coastline_km": None,
            "land_border_km": None,
            "coastline_share": None,
            "rugged_avg": None,
            "rugged_norm": None,
            "geo_barrier": None,
            "missing_iso": "|".join(sorted(missing_iso)),
        }

    # Build union and per-ISO area weights for ruggedness.
    geometries = []
    area_by_iso: dict[str, float] = {}
    for _, row in country_sel.iterrows():
        geom = make_valid(row.geometry)
        if geom.is_empty:
            continue
        geometries.append(geom)
        _polygon_area_by_iso(geom, row["ADM0_A3"], area_by_iso)
    for _, row in admin1_sel.iterrows():
        geom = make_valid(row.geometry)
        if geom.is_empty:
            continue
        geometries.append(geom)
        _polygon_area_by_iso(geom, row["adm0_a3"].upper(), area_by_iso)

    if len(geometries) == 0:
        return {
            "entity": entity,
            "iso_count": len(country_sel),
            "admin1_count": len(admin1_sel),
            "total_boundary_km": None,
            "coastline_km": None,
            "land_border_km": None,
            "coastline_share": None,
            "rugged_avg": None,
            "rugged_norm": None,
            "geo_barrier": None,
            "missing_iso": "",
        }

    # Robust unary union with a small grid snap to avoid GEOS topology errors
    # from tiny overlaps/gaps between adjacent admin-1 or country polygons.
    from shapely import unary_union

    union = unary_union(geometries, grid_size=0.001)
    if union.is_empty:
        return {
            "entity": entity,
            "iso_count": len(country_sel),
            "admin1_count": len(admin1_sel),
            "total_boundary_km": None,
            "coastline_km": None,
            "land_border_km": None,
            "coastline_share": None,
            "rugged_avg": None,
            "rugged_norm": None,
            "geo_barrier": None,
            "missing_iso": "",
        }
    if union.geom_type not in ("Polygon", "MultiPolygon"):
        union = make_valid(union)
    total = float(union.boundary.length)

    # Compute land border shared with other modern countries/provinces.
    land = 0.0
    # Any ISO code that is represented by an admin-1 selection (host_adm0) or a
    # full country polygon (iso_codes) should not be treated as a land
    # neighbour. For the host country(ies) we also subtract selected admin-1
    # provinces to avoid double-counting internal boundaries.
    host_adm0 = set(admin1_sel["adm0_a3"].str.upper().tolist())
    selected_admin1_ids = set(admin1_sel.index.tolist())

    other_countries = countries[~countries["ADM0_A3"].isin(host_adm0 | set(iso_codes))]
    for geom in other_countries.geometry:
        land = _add_land_border(union, make_valid(geom), land)

    if not admin1_sel.empty:
        other_admin1 = admin1_gdf[
            admin1_gdf["adm0_a3"].str.upper().isin(host_adm0)
            & ~admin1_gdf.index.isin(selected_admin1_ids)
        ]
        for geom in other_admin1.geometry:
            land = _add_land_border(union, make_valid(geom), land)

    coastline = max(0.0, total - land)
    coastline_share = coastline / total if total > 0 else 0.0

    # Area-weighted ruggedness by ISO.
    sub = rugged_df[rugged_df["iso3"].isin(set(area_by_iso.keys()))].copy()
    rugged_avg = None
    if not sub.empty and any(area_by_iso.get(iso, 0) > 0 for iso in sub["iso3"]):
        total_area = 0.0
        weighted = 0.0
        for _, row in sub.iterrows():
            iso = row["iso3"]
            area = area_by_iso.get(iso, 0.0)
            weighted += float(row["rugged"]) * area
            total_area += area
        rugged_avg = weighted / total_area if total_area > 0 else None
    elif not sub.empty:
        rugged_avg = float(sub["rugged"].mean())

    rugged_norm = min(1.0, rugged_avg / max_rugged) if rugged_avg is not None else None

    if rugged_norm is not None:
        geo_barrier = 1.0 - (1.0 - coastline_share) * (1.0 - rugged_norm)
    else:
        geo_barrier = coastline_share

    return {
        "entity": entity,
        "iso_count": len(country_sel),
        "admin1_count": len(admin1_sel),
        "total_boundary_km": round(total / 1000, 2),
        "coastline_km": round(coastline / 1000, 2),
        "land_border_km": round(land / 1000, 2),
        "coastline_share": round(coastline_share, 4),
        "rugged_avg": round(rugged_avg, 4) if rugged_avg is not None else None,
        "rugged_norm": round(rugged_norm, 4) if rugged_norm is not None else None,
        "geo_barrier": round(geo_barrier, 4),
        "missing_iso": "|".join(sorted(missing_iso)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mapping",
        default=PROJECT_DIR / "data" / "polity_geometry_mapping.csv",
        help="CSV mapping entity -> ISO and/or admin-1 codes (pipe-separated)",
    )
    parser.add_argument(
        "--output",
        default=PROJECT_DIR / "data" / "geo_barrier_reconstructed.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    print("Loading Natural Earth 1:10m countries and admin-1 ...", file=sys.stderr)
    countries = load_countries()
    admin1_gdf = load_admin1()
    print("Loading Nunn-Puga ruggedness data ...", file=sys.stderr)
    rugged_df, max_rugged = load_ruggedness()

    mapping_path = Path(args.mapping)
    if not mapping_path.exists():
        print(f"Error: mapping file not found: {mapping_path}", file=sys.stderr)
        sys.exit(1)

    results = []
    with mapping_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entity = row["entity"].strip()
            iso_codes = parse_codes(row.get("iso3_codes", ""))
            admin1_tokens = parse_codes(row.get("admin1_codes", ""))
            print(f"Processing {entity} ...", file=sys.stderr)
            res = compute_one(
                entity,
                iso_codes,
                admin1_tokens,
                countries,
                admin1_gdf,
                rugged_df,
                max_rugged,
            )
            # Keep metadata columns from mapping
            for key in ["period", "peak_year", "needs_review", "notes", "admin1_codes"]:
                res[key] = row.get(key, "").strip()
            results.append(res)

    out = pd.DataFrame(results)
    out_path = Path(args.output)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
