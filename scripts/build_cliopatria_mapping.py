#!/usr/bin/env python3
"""Build improved polity-territory mapping from the Cliopatria historical GIS dataset.

Cliopatria (Seshat Global History Databank) provides worldwide polity polygons
with year ranges. This script maps each of our 79 non-ongoing polities to the
best-matching Cliopatria record at the polity's peak_year, intersects the
Cliopatria polygon with Natural Earth 1:10m admin-1 provinces, and writes a new
polity_geometry_mapping.csv with ISO3/admin-1 codes restricted to the actually
occupied provinces.

Inputs:
- data/polity_geometry_mapping.csv (for entity list, period, peak_year)
- data/raw/cliopatria.geojson (Seshat Cliopatria v0.0.1+)
- Natural Earth admin-1 provinces (downloaded/cached by reconstruct_geo_barrier)

Outputs:
- data/polity_geometry_mapping.csv (updated)
- data/cliopatria_mapping.csv (audit trail)
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CRS = "EPSG:6933"

# Curated mapping from our Japanese entity names to Cliopatria "Name" values.
# None means no suitable Cliopatria match; existing ISO/admin-1 mapping is kept.
CLIOPATRIA_NAMES: dict[str, str | None] = {
    "アケメネス朝ペルシア": "Achaemenid Empire",
    "アテネ（ペロポネソス戦争後）": "Second Athenian League",
    "スパルタ": None,
    "カルタゴ": "Carthage",
    "ローマ共和政〜帝政前期": "Roman Empire",
    "ローマ帝政後期（西）": "Western Roman Empire",
    "プトレマイオス朝エジプト": "Ptolemaic Kingdom",
    "漢朝（前漢〜後漢）": "Han Dynasty",
    "ビザンツ帝国（前期）": "Byzantine Empire",
    "ビザンツ帝国（後期）": "Byzantine Empire",
    "アッバース朝（前期）": "Abbasid Caliphate",
    "アッバース朝（後期）": "Abbasid Caliphate",
    "宋朝中国": "Northern Song",
    "モンゴル帝国": "Mongol Empire",
    "マムルーク朝エジプト": "Mamluk Sultanate",
    "ヴェネツィア共和国": "Republic of Venice",
    "ハンザ同盟": None,
    "オスマン帝国（前期）": "Ottoman Empire",
    "オスマン帝国（後期）": "Ottoman Empire",
    "明朝中国": "Ming Dynasty",
    "清朝中国（前期）": "Qing Dynasty",
    "清朝中国（後期）": "Qing Dynasty",
    "李朝朝鮮": "Joseon",
    "徳川日本": "Tokugawa Shogunate",
    "ムガル帝国（後期）": "Mughal Empire",
    "サファヴィー朝ペルシア": "Safavid Dynasty",
    "インカ帝国": "Inca Empire",
    "アステカ帝国": "Aztec Triple Alliance",
    "ポルトガル帝国": "Portuguese Empire",
    "オランダ共和国": "Dutch Republic",
    "スペイン帝国": "Spanish Empire",
    "ムガル帝国（前期）": "Mughal Empire",
    "大英帝国": "British Colonial Empire",
    "米国（モンロー主義期）": "United States of America",
    "明治〜大正日本": "Empire of Japan",
    "エチオピア帝国": "Ethiopian Empire",
    "シャム（タイ）": "Rattanakosin Kingdom",
    "1930s日本（大東亜共栄圏）": "Empire of Japan",
    "ナチスドイツ": "Nazi Germany",
    "ファシストイタリア": "Kingdom of Italy",
    "ソ連": "Union of Soviet Socialist Republics",
    "東ドイツ": "German Democratic Republic",
    "ユーゴスラビア": "Socialist Federal Republic of Yugoslavia",
    "英国帝国特恵制度": None,
    "米国（戦後〜冷戦期）": "United States of America",
    "戦後日本（高度成長期）": "Japan",
    "マケドニア王国（アレクサンドロス後）": "Antigonid Macedonia",
    "セレウコス朝シリア": "Seleucid Empire",
    "パルティア": "Parthian Empire",
    "ササン朝ペルシア": "Sasanian Empire",
    "クシャーナ朝": "Kushan Empire",
    "グプタ朝インド": "Gupta Empire",
    "唐朝中国": "Tang Dynasty",
    "ウマイヤ朝": "Umayyad Caliphate",
    "高麗": "Goryeo",
    "クメール帝国（アンコール）": "Khmer Empire",
    "シュリーヴィジャヤ": "Srivijaya",
    "マジャパヒト王国": "Majapahit",
    "キエフ大公国": "Kievan Rus'",
    "ジェノヴァ共和国": "Republic of Genoa",
    "マリ帝国": "Mali Empire",
    "元朝中国": "Yuan Dynasty",
    "ティムール朝": "Timurid Empire",
    "琉球王国": None,
    "ポーランド・リトアニア共和国": "Polish-Lithuanian Commonwealth",
    "スウェーデン帝国": "Swedish Empire",
    "ロシア帝国（ピョートル後）": "Russian Empire",
    "清朝中国（中期・交易拡大期）": "Qing Dynasty",
    "ハワイ王国": None,
    "ズールー王国": "Zululand",
    "ビルマ（コンバウン朝）": "Konbaung Dynasty",
    "オーストリア＝ハンガリー帝国": "Austria-Hungary",
    "ナポレオン帝国": "First French Empire",
    "大韓帝国": "Korean Empire",
    "満州国": None,
    "南ベトナム": "Republic of Vietnam",
    "チェコスロバキア（共産期）": "Czechoslovakia",
    "ポーランド（共産期）": "Republic of Poland",
    "ルーマニア（共産期）": "Socialist Republic of Romania",
}


def load_admin1() -> gpd.GeoDataFrame:
    """Import admin-1 loader from reconstruct_geo_barrier to ensure consistency."""
    sys.path.insert(0, str(PROJECT_DIR / "scripts"))
    import reconstruct_geo_barrier as rgb

    return rgb.load_admin1()


def load_cliopatria(path: Path) -> gpd.GeoDataFrame:
    print("Loading Cliopatria; this may take a moment...", file=sys.stderr)
    gdf = gpd.read_file(path)
    gdf = gdf[gdf["Type"] == "POLITY"].copy()
    gdf["FromYear"] = pd.to_numeric(gdf["FromYear"], errors="coerce")
    gdf["ToYear"] = pd.to_numeric(gdf["ToYear"], errors="coerce")
    gdf["Area"] = pd.to_numeric(gdf["Area"], errors="coerce")
    gdf = gdf[gdf["FromYear"].notna() & gdf["ToYear"].notna()].copy()
    gdf = gdf.to_crs(DEFAULT_CRS)
    gdf["geometry"] = gdf.geometry.apply(make_valid)
    print(f"  Loaded {len(gdf)} Cliopatria POLITY records", file=sys.stderr)
    return gdf


def select_cliopatria_record(
    clio: gpd.GeoDataFrame, name: str, peak_year: float
) -> gpd.GeoSeries | None:
    """Pick the best Cliopatria record for (name, peak_year).

    Prefer a record whose interval contains peak_year and has the largest Area.
    If none overlap, pick the record whose interval is closest to peak_year,
    breaking ties by area.
    """
    sub = clio[clio["Name"] == name].copy()
    if sub.empty:
        return None
    sub["overlap"] = (sub["FromYear"] <= peak_year) & (sub["ToYear"] >= peak_year)
    overlapping = sub[sub["overlap"]].copy()
    if not overlapping.empty:
        return overlapping.loc[overlapping["Area"].idxmax()]
    # No overlap; choose nearest interval.
    sub["dist_start"] = (sub["FromYear"] - peak_year).abs()
    sub["dist_end"] = (sub["ToYear"] - peak_year).abs()
    sub["dist"] = sub[["dist_start", "dist_end"]].min(axis=1)
    return sub.loc[sub["dist"].idxmin()]


def intersect_with_admin1(
    clio_poly,
    admin1_gdf: gpd.GeoDataFrame,
    area_share_threshold: float = 0.05,
    min_area_km2: float = 20000.0,
) -> tuple[set[str], list[str], float]:
    """Return (iso3_set, admin1_tokens, total_intersection_area_km2).

    An admin-1 province is included if either:
      - intersection_area / province_area >= area_share_threshold, or
      - intersection_area >= min_area_km2.
    """
    if clio_poly is None or clio_poly.is_empty:
        return set(), [], 0.0

    # Use spatial index to get candidate admin-1 rows.
    bounds = clio_poly.bounds
    hits = list(admin1_gdf.sindex.intersection(bounds))
    if not hits:
        return set(), [], 0.0
    candidates = admin1_gdf.iloc[hits].copy()

    # Clip candidates to the Cliopatria polygon.
    clipped = gpd.clip(candidates, clio_poly)
    if clipped.empty:
        return set(), [], 0.0

    clipped["intersection_area"] = clipped.geometry.area
    # Admin-1 total area is the original polygon area.
    clipped["province_area"] = candidates.loc[clipped.index, "geometry"].area.values
    clipped["share"] = clipped["intersection_area"] / clipped["province_area"]
    selected = clipped[
        (clipped["share"] >= area_share_threshold)
        | (clipped["intersection_area"] >= min_area_km2)
    ].copy()
    if selected.empty:
        return set(), [], 0.0

    iso3_set = set(selected["adm0_a3"].str.upper().tolist())
    # Build admin-1 tokens as COUNTRY:ProvinceName using the name column.
    tokens = []
    for _, row in selected.iterrows():
        country = str(row["adm0_a3"]).upper()
        name = str(row["name"]).strip()
        if not name:
            name = str(row["name_en"]).strip()
        if name:
            tokens.append(f"{country}:{name}")
    total_area = float(selected["intersection_area"].sum())
    return iso3_set, sorted(set(tokens)), total_area


def main():
    parser = argparse.ArgumentParser(description="Build Cliopatria-based mapping")
    parser.add_argument(
        "--mapping",
        default=str(PROJECT_DIR / "data" / "polity_geometry_mapping.csv"),
        help="Input/output polity_geometry_mapping.csv",
    )
    parser.add_argument(
        "--cliopatria",
        default=str(PROJECT_DIR / "data" / "raw" / "cliopatria.geojson"),
        help="Cliopatria geojson path",
    )
    parser.add_argument(
        "--output-audit",
        default=str(PROJECT_DIR / "data" / "cliopatria_mapping.csv"),
        help="Audit CSV output",
    )
    args = parser.parse_args()

    mapping_path = Path(args.mapping)
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig", dtype=str)
    mapping["peak_year"] = pd.to_numeric(mapping["peak_year"], errors="coerce")

    admin1_gdf = load_admin1()
    admin1_gdf["geometry"] = admin1_gdf.geometry.apply(make_valid)

    clio = load_cliopatria(Path(args.cliopatria))

    audit_rows: list[dict] = []

    for i, row in mapping.iterrows():
        entity = row["entity"]
        peak_year = float(row["peak_year"])
        clio_name = CLIOPATRIA_NAMES.get(entity)

        if not clio_name:
            audit_rows.append(
                {
                    "entity": entity,
                    "clio_name": "",
                    "clio_from_year": np.nan,
                    "clio_to_year": np.nan,
                    "clio_area_km2": np.nan,
                    "matched_year": np.nan,
                    "intersection_area_km2": np.nan,
                    "n_admin1": 0,
                    "iso3_codes": row.get("iso3_codes", ""),
                    "admin1_codes": row.get("admin1_codes", ""),
                    "needs_review": 1,
                    "notes": "No Cliopatria match; existing mapping retained",
                }
            )
            continue

        rec = select_cliopatria_record(clio, clio_name, peak_year)
        if rec is None:
            audit_rows.append(
                {
                    "entity": entity,
                    "clio_name": clio_name,
                    "clio_from_year": np.nan,
                    "clio_to_year": np.nan,
                    "clio_area_km2": np.nan,
                    "matched_year": np.nan,
                    "intersection_area_km2": np.nan,
                    "n_admin1": 0,
                    "iso3_codes": row.get("iso3_codes", ""),
                    "admin1_codes": row.get("admin1_codes", ""),
                    "needs_review": 1,
                    "notes": f"Cliopatria name '{clio_name}' not found; existing mapping retained",
                }
            )
            continue

        geom = rec.geometry
        if not geom.is_valid or geom.is_empty:
            geom = make_valid(geom)

        iso3_set, admin1_tokens, inter_area = intersect_with_admin1(geom, admin1_gdf)

        iso3_str = "|".join(sorted(iso3_set))
        admin1_str = "|".join(admin1_tokens) if admin1_tokens else ""

        # Decide if the new mapping is good enough to clear needs_review.
        # We keep needs_review=0 only if at least one admin-1 province matched.
        needs_review = 0 if admin1_tokens else 1
        note = (
            f"Cliopatria source: {clio_name} ({int(rec['FromYear'])} to {int(rec['ToYear'])}, "
            f"area {float(rec['Area']):.0f} km2); intersection area {inter_area:.0f} km2, "
            f"{len(admin1_tokens)} admin-1 matches"
        )

        mapping.at[i, "iso3_codes"] = iso3_str if iso3_str else row.get("iso3_codes", "")
        mapping.at[i, "admin1_codes"] = admin1_str
        mapping.at[i, "needs_review"] = needs_review
        mapping.at[i, "notes"] = note

        audit_rows.append(
            {
                "entity": entity,
                "clio_name": clio_name,
                "clio_from_year": int(rec["FromYear"]),
                "clio_to_year": int(rec["ToYear"]),
                "clio_area_km2": float(rec["Area"]),
                "matched_year": peak_year,
                "intersection_area_km2": inter_area,
                "n_admin1": len(admin1_tokens),
                "iso3_codes": iso3_str,
                "admin1_codes": admin1_str,
                "needs_review": needs_review,
                "notes": note,
            }
        )

    # Save updated mapping.
    mapping.to_csv(mapping_path, index=False, encoding="utf-8-sig")
    print(f"Wrote {mapping_path}", file=sys.stderr)

    audit = pd.DataFrame(audit_rows)
    audit.to_csv(args.output_audit, index=False, encoding="utf-8-sig")
    print(f"Wrote {args.output_audit}", file=sys.stderr)

    print(
        f"Summary: {int((audit['needs_review']==0).sum())} matched, "
        f"{int((audit['needs_review']==1).sum())} still flagged",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
