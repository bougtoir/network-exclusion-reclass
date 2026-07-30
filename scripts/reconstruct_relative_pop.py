#!/usr/bin/env python3
"""Reconstruct a public-data based relative_pop index for 79 non-ongoing polities.

Population estimation
---------------------
Primary source:
    Our World in Data (OWID) long-run population dataset
    (https://ourworldindata.org/grapher/population.csv)
    which combines HYDE v3.3 (10,000 BCE-1799), Gapminder v7 (1800-1949),
    UN WPP (1950-), and Gapminder Systema Globalis for former states.

For each polity we:
1. Read its iso3_codes (and optional admin1_codes) from
   data/polity_geometry_mapping.csv.
2. Convert iso3_codes to OWID entities. Special historical states are
   handled explicitly so we do not double-count modern successor countries:
   - CZE + SVK together -> Czechoslovakia (for periods before 1993)
   - DEU in East Germany -> East Germany
   - the Yugoslav republic set (SRB/HRV/SVN/BIH/MNE/MKD/KOS) for the
     Yugoslavia entity -> Yugoslavia
   - KOR + PRK together -> South Korea + North Korea (unified peninsula proxy)
   - PSX -> Palestine (PSE)
3. For each OWID entity, look up the population at the polity's peak_year.
   Missing years are linearly interpolated from the available time series.
4. If admin1_codes restrict the polity to a subnational share of a host
   country (e.g. East Germany's six Länder, Athens' Attica), multiply that
   country's population by the selected admin-1 area / total country area.
   This is a rough uniform-density proxy and is flagged for review.
5. Sum the (possibly scaled) country populations to get population_estimate.

Relative scaling (option 1)
----------------------------
relative_pop = population_estimate /
               max(population_estimate of all polities whose periods overlap)

Output
------
- data/relative_pop_reconstructed.csv
- data/all_features.csv is updated to include the new relative_pop column.
"""

import argparse
import csv
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from reconstruct_geo_barrier import load_admin1, parse_codes, select_admin1
from compute_capital_distances import parse_period

PROJECT_DIR = Path(__file__).resolve().parent.parent
OWID_URL = "https://ourworldindata.org/grapher/population.csv?v=1&csvType=full&useColumnShortNames=false"

# ISO3 codes that correspond to the territory of historical Czechoslovakia
CZECH_CODES = {"CZE", "SVK"}

# ISO3 codes that correspond to the territory of historical Yugoslavia
YUGO_CODES = {"SRB", "HRV", "SVN", "BIH", "MNE", "MKD", "KOS"}


def cache_file(url: str, filename: str) -> Path:
    """Download a public file once and cache it under data/raw."""
    raw_dir = PROJECT_DIR / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / filename
    if not out_path.exists():
        print(f"Downloading {filename} ...", file=sys.stderr)
        import urllib.request

        urllib.request.urlretrieve(url, out_path)
    return out_path


def load_owid_population(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"Code": str})
    # Build a quick code -> primary entity name lookup for unambiguous codes.
    code_to_entity = (
        df.drop_duplicates(subset=["Code"], keep="first")
        .set_index("Code")["Entity"]
        .to_dict()
    )
    return df, code_to_entity


def iso3_to_owid_entities(iso3: str, all_codes: set[str], entity_name: str, year: float) -> list[str]:
    """Map a single ISO3 token to one or more OWID entity names."""
    iso3 = iso3.strip().upper()

    if iso3 == "PSX":
        # Natural Earth uses PSX for Palestine/ West Bank+Gaza.
        return ["Palestine"]

    if iso3 in CZECH_CODES:
        if "CZE" in all_codes or "SVK" in all_codes:
            return ["Czechoslovakia"]
        if iso3 == "CZE":
            return ["Czechia"]
        return ["Slovakia"]

    if iso3 in YUGO_CODES:
        # For the historical Yugoslavia polity itself, use the combined entity.
        if entity_name == "ユーゴスラビア" and 1918 <= year <= 1992:
            return ["Yugoslavia"]
        # Otherwise map to the modern successor entity (or Kosovo if available).
        mapping = {
            "SRB": "Serbia",
            "HRV": "Croatia",
            "SVN": "Slovenia",
            "BIH": "Bosnia and Herzegovina",
            "MNE": "Montenegro",
            "MKD": "North Macedonia",
            "KOS": "Kosovo",
        }
        return [mapping.get(iso3, "Yugoslavia")]

    if iso3 == "DEU":
        if entity_name == "東ドイツ" and 1949 <= year <= 1990:
            return ["East Germany"]
        return ["Germany"]

    if iso3 == "KOR":
        return ["South Korea"]
    if iso3 == "PRK":
        return ["North Korea"]

    # Default: look up by ISO3 Code in OWID.
    if iso3 in _CODE_TO_ENTITY:
        return [_CODE_TO_ENTITY[iso3]]

    print(f"  Warning: no OWID entity for ISO3 {iso3}", file=sys.stderr)
    return []


_owid_df: pd.DataFrame | None = None
_CODE_TO_ENTITY: dict[str, str] = {}


def owid_population(entity_name: str, year: float) -> float | None:
    """Linearly interpolated population for an OWID entity at a given year."""
    series = _owid_df[_owid_df["Entity"] == entity_name].set_index("Year")["Population"].sort_index()
    if series.empty:
        return None
    years = series.index.to_numpy(dtype=float)
    pop = series.to_numpy(dtype=float)
    return float(np.interp(year, years, pop))


def compute_area_share(
    iso3: str,
    admin1_tokens: list[str],
    admin1_gdf: gpd.GeoDataFrame,
    total_country_area: dict[str, float],
) -> float:
    """Return the selected admin-1 area as a share of the host country area."""
    if not admin1_tokens:
        return 1.0
    tokens_for_iso = [t for t in admin1_tokens if t.upper().startswith(f"{iso3}:")]
    if not tokens_for_iso:
        return 1.0
    selected = select_admin1(tokens_for_iso, admin1_gdf)
    if selected.empty:
        return 1.0
    total = total_country_area.get(iso3.upper())
    if not total:
        return 1.0
    return float(selected.geometry.area.sum() / total)


def periods_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return max(a[0], b[0]) < min(a[1], b[1])


def build_sources(
    entity: str,
    peak_year: float,
    iso_codes: list[str],
    admin1_tokens: list[str],
    admin1_gdf: gpd.GeoDataFrame,
    total_country_area: dict[str, float],
) -> tuple[list[tuple[str, float]], bool, str]:
    """Return (list of (owid_entity, area_scale), area_scaled, notes)."""
    all_codes = set(iso_codes)
    sources: list[tuple[str, float]] = []
    seen: set[str] = set()
    notes: list[str] = []
    area_scaled = False

    for iso3 in iso_codes:
        entities = iso3_to_owid_entities(iso3, all_codes, entity, peak_year)
        if not entities:
            notes.append(f"no OWID mapping for {iso3}")
            continue
        for e in entities:
            if e in seen:
                continue
            seen.add(e)
            # Area scaling: if admin1 tokens restrict this ISO3, apply share.
            share = compute_area_share(iso3, admin1_tokens, admin1_gdf, total_country_area)
            if share < 1.0:
                area_scaled = True
                notes.append(f"area-scaled {iso3} ({share:.3f})")
            sources.append((e, share))

    if not sources:
        return [], False, "; ".join(notes) if notes else "no population source"
    return sources, area_scaled, "; ".join(notes) if notes else ""


def population_at_year(sources: list[tuple[str, float]], year: float) -> float | None:
    """Sum OWID populations for the given sources at a given year."""
    total = 0.0
    for entity_name, scale in sources:
        pop = owid_population(entity_name, year)
        if pop is None or np.isnan(pop):
            return None
        total += pop * scale
    return total


def main():
    parser = argparse.ArgumentParser(description="Reconstruct relative_pop from public population data")
    parser.add_argument(
        "--mapping",
        default=str(PROJECT_DIR / "data" / "polity_geometry_mapping.csv"),
        help="CSV mapping entity -> ISO and admin-1 codes",
    )
    parser.add_argument(
        "--owid",
        default=str(PROJECT_DIR / "data" / "raw" / "owid_population.csv"),
        help="OWID population CSV",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_DIR / "data" / "relative_pop_reconstructed.csv"),
        help="Output CSV for relative_pop",
    )
    parser.add_argument(
        "--all-features",
        default=str(PROJECT_DIR / "data" / "all_features.csv"),
        help="Merged feature CSV to update",
    )
    args = parser.parse_args()

    global _owid_df, _CODE_TO_ENTITY
    owid_path = Path(args.owid)
    if not owid_path.exists():
        owid_path = cache_file(OWID_URL, "owid_population.csv")
    _owid_df, _CODE_TO_ENTITY = load_owid_population(owid_path)

    print("Loading Natural Earth admin-1 for area scaling ...", file=sys.stderr)
    admin1_gdf = load_admin1()
    total_country_area = (
        admin1_gdf.groupby(admin1_gdf["adm0_a3"].str.upper())["geometry"]
        .apply(lambda g: float(g.area.sum()))
        .to_dict()
    )

    mapping_path = Path(args.mapping)
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig", dtype=str)
    mapping["peak_year"] = pd.to_numeric(mapping["peak_year"], errors="coerce")

    records: list[dict] = []
    for _, row in mapping.iterrows():
        entity = str(row["entity"]).strip()
        period = parse_period(row.get("period", ""))
        peak_year = row["peak_year"]
        if period is None or pd.isna(peak_year):
            records.append(
                {
                    "entity": entity,
                    "period": row.get("period", ""),
                    "peak_year": peak_year,
                    "population_estimate": None,
                    "owid_entities": "",
                    "area_scaled": False,
                    "contemporaneous_max_pop": None,
                    "relative_pop": None,
                    "needs_review": 1,
                    "notes": "missing period or peak_year",
                }
            )
            continue

        iso_codes = parse_codes(str(row.get("iso3_codes", "")))
        admin1_tokens = parse_codes(str(row.get("admin1_codes", "")))

        sources, area_scaled, notes = build_sources(
            entity,
            float(peak_year),
            iso_codes,
            admin1_tokens,
            admin1_gdf,
            total_country_area,
        )
        pop_estimate = population_at_year(sources, float(peak_year))

        base_needs_review = int(row.get("needs_review", 0))
        if pop_estimate is None or not sources:
            needs_review = 1
            if not notes:
                notes = "population estimate failed"
        else:
            needs_review = base_needs_review

        records.append(
            {
                "entity": entity,
                "period": row.get("period", ""),
                "peak_year": peak_year,
                "population_estimate": pop_estimate,
                "sources": sources,
                "owid_entities": "|".join(sorted({e for e, _ in sources})),
                "area_scaled": area_scaled,
                "contemporaneous_max_pop": None,  # filled after all estimates
                "relative_pop": None,
                "needs_review": needs_review,
                "notes": notes,
            }
        )

    # Compute contemporaneous max and relative_pop.
    # Each polity is mapped to its *peak* territory, so the population estimate
    # is already a snapshot of the regions the polity eventually controlled.  We
    # compare it against the population estimates of all other polities whose
    # lifespan includes the same peak year.  This means we compare the
    # contemporary powers as if they were all measured at the target polity's
    # peak, using the public population series for those regions at that year.
    periods: dict[str, tuple[float, float]] = {}
    sources_by_entity: dict[str, list[tuple[str, float]]] = {}
    for r in records:
        p = parse_period(r["period"])
        if p is not None and r.get("sources"):
            periods[r["entity"]] = p
            sources_by_entity[r["entity"]] = r["sources"]

    for i, r in enumerate(records):
        entity = r["entity"]
        period_i = periods.get(entity)
        sources_i = sources_by_entity.get(entity)
        if period_i is None or not sources_i:
            continue
        year = float(r["peak_year"])
        pop_i = population_at_year(sources_i, year)
        if pop_i is None or np.isnan(pop_i):
            continue
        records[i]["population_estimate"] = pop_i

        max_pop = 0.0
        for other_entity, period_j in periods.items():
            if period_j[0] <= year <= period_j[1]:
                pop_j = population_at_year(sources_by_entity[other_entity], year)
                if pop_j is not None and not np.isnan(pop_j):
                    max_pop = max(max_pop, pop_j)
        if max_pop > 0:
            records[i]["contemporaneous_max_pop"] = max_pop
            records[i]["relative_pop"] = float(pop_i / max_pop)

    # Drop the helper sources column before writing.
    for r in records:
        r.pop("sources", None)

    out = pd.DataFrame(records)
    out_path = Path(args.output)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Wrote {out_path}", file=sys.stderr)

    # Merge into all_features.csv if it exists.
    all_features_path = Path(args.all_features)
    if all_features_path.exists():
        features = pd.read_csv(all_features_path, encoding="utf-8-sig")
        drop_cols = [
            "relative_pop",
            "population_estimate",
            "contemporaneous_max_pop",
            "population_estimate_rel_pop",
            "contemporaneous_max_pop_rel_pop",
        ]
        features = features.drop(columns=[c for c in drop_cols if c in features.columns])
        features = features.merge(
            out[["entity", "relative_pop", "population_estimate", "contemporaneous_max_pop", "needs_review"]],
            on="entity",
            how="left",
            suffixes=("", "_rel_pop"),
        )
        # Propagate any new needs_review flag
        if "needs_review" in features.columns:
            features["needs_review"] = features[["needs_review", "needs_review_rel_pop"]].max(axis=1)
            features = features.drop(columns=["needs_review_rel_pop"])
        features.to_csv(all_features_path, index=False, encoding="utf-8-sig")
        print(f"Updated {all_features_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
