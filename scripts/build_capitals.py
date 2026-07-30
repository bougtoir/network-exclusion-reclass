#!/usr/bin/env python3
"""Build a starter capital-coordinates table for the 79 non-ongoing polities.

Capital coordinates are taken from GeoNames cities1000 where possible, and
from Wikipedia/authoritative historical atlas coordinates for ancient or
small capitals not in the GeoNames database.  Rows marked needs_review=1
should be checked by a historian.
"""

import argparse
import sys
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_DIR / "data" / "raw"

CITIES_URL = "https://download.geonames.org/export/dump/cities1000.zip"

# Manual coordinates for capitals not reliably found in cities1000, or where
# the historical capital differs from the modern place-name in the database.
# Sources are generally Wikipedia / GeoNames populated-place records.
MANUAL = {
    "Persepolis": (29.9355, 52.8917, "Wikipedia: Persepolis"),
    "Pella": (40.7617, 22.5250, "Wikipedia: Pella, Greece"),
    "Ctesiphon": (33.0938, 44.5806, "Wikipedia: Ctesiphon"),
    "Pataliputra": (25.5941, 85.1376, "Wikipedia: Patna (Pataliputra)"),
    "Karakorum": (47.1965, 102.8246, "Wikipedia: Karakorum"),
    "Angkor": (13.4125, 103.8670, "Wikipedia: Angkor"),
    "Trowulan": (-7.5398, 112.7009, "Wikipedia: Trowulan (Majapahit capital)"),
    "Ulundi": (-28.3355, 31.4166, "Wikipedia: Ulundi"),
    "Kaesong": (37.9703, 126.5542, "Wikipedia: Kaesong"),
    "Hangzhou": (30.2741, 120.1551, "GeoNames: Hangzhou"),
    "Kaifeng": (34.7970, 114.3444, "GeoNames: Kaifeng"),
    "Changchun": (43.8171, 125.3235, "GeoNames: Changchun"),
    "Saigon": (10.8231, 106.6297, "GeoNames: Ho Chi Minh City (Saigon)"),
    "Cusco": (-13.52264, -71.96734, "Wikipedia: Cusco"),
}

# Entity -> (capital_name, country_iso2, notes)
# Country code is the modern country where the historical capital was located.
CAPITAL_INFO = {
    "アケメネス朝ペルシア": ("Persepolis", "IR", "Achaemenid royal centre; multiple capitals existed."),
    "アテネ（ペロポネソス戦争後）": ("Athens", "GR", ""),
    "スパルタ": ("Sparta", "GR", ""),
    "カルタゴ": ("Carthage", "TN", "Ancient city near modern Tunis."),
    "ローマ共和政〜帝政前期": ("Rome", "IT", ""),
    "ローマ帝政後期（西）": ("Rome", "IT", ""),
    "プトレマイオス朝エジプト": ("Alexandria", "EG", ""),
    "漢朝（前漢〜後漢）": ("Xi'an", "CN", "Chang'an, modern Xi'an."),
    "ビザンツ帝国（前期）": ("Istanbul", "TR", "Constantinople."),
    "ビザンツ帝国（後期）": ("Istanbul", "TR", "Constantinople."),
    "アッバース朝（前期）": ("Baghdad", "IQ", ""),
    "アッバース朝（後期）": ("Baghdad", "IQ", ""),
    "宋朝中国": ("Kaifeng", "CN", "Northern Song capital; Southern Song later moved to Hangzhou."),
    "モンゴル帝国": ("Karakorum", "MN", "Nomadic capital; later also Khanbaliq/Beijing."),
    "マムルーク朝エジプト": ("Cairo", "EG", ""),
    "ヴェネツィア共和国": ("Venice", "IT", ""),
    "ハンザ同盟": ("Lübeck", "DE", "De facto capital of the Hanseatic League."),
    "オスマン帝国（前期）": ("Edirne", "TR", "Early Ottoman capital before Constantinople fell in 1453."),
    "オスマン帝国（後期）": ("Istanbul", "TR", ""),
    "明朝中国": ("Beijing", "CN", ""),
    "清朝中国（前期）": ("Beijing", "CN", ""),
    "清朝中国（後期）": ("Beijing", "CN", ""),
    "李朝朝鮮": ("Seoul", "KR", "Hanyang."),
    "徳川日本": ("Tokyo", "JP", "Edo."),
    "ムガル帝国（後期）": ("Delhi", "IN", "Shahjahanabad."),
    "サファヴィー朝ペルシア": ("Isfahan", "IR", ""),
    "インカ帝国": ("Cusco", "PE", ""),
    "アステカ帝国": ("Mexico City", "MX", "Tenochtitlan."),
    "ポルトガル帝国": ("Lisbon", "PT", ""),
    "オランダ共和国": ("Amsterdam", "NL", ""),
    "スペイン帝国": ("Madrid", "ES", ""),
    "ムガル帝国（前期）": ("Agra", "IN", "Early Mughal capital before Delhi."),
    "大英帝国": ("London", "GB", ""),
    "米国（モンロー主義期）": ("Washington", "US", ""),
    "明治〜大正日本": ("Tokyo", "JP", ""),
    "エチオピア帝国": ("Addis Ababa", "ET", ""),
    "シャム（タイ）": ("Bangkok", "TH", ""),
    "1930s日本（大東亜共栄圏）": ("Tokyo", "JP", ""),
    "ナチスドイツ": ("Berlin", "DE", ""),
    "ファシストイタリア": ("Rome", "IT", ""),
    "ソ連": ("Moscow", "RU", ""),
    "東ドイツ": ("Berlin", "DE", "East Berlin."),
    "ユーゴスラビア": ("Belgrade", "RS", ""),
    "英国帝国特恵制度": ("London", "GB", "Imperial Preference trade bloc; capital of the UK."),
    "米国（戦後〜冷戦期）": ("Washington", "US", ""),
    "戦後日本（高度成長期）": ("Tokyo", "JP", ""),
    "マケドニア王国（アレクサンドロス後）": ("Pella", "GR", "Antigonid Macedonian capital."),
    "セレウコス朝シリア": ("Antakya", "TR", "Ancient Antioch, modern Antakya."),
    "パルティア": ("Ctesiphon", "IQ", "Near modern Salman Pak."),
    "ササン朝ペルシア": ("Ctesiphon", "IQ", ""),
    "クシャーナ朝": ("Peshawar", "PK", "One of several Kushan capitals."),
    "グプタ朝インド": ("Pataliputra", "IN", "Modern Patna."),
    "唐朝中国": ("Xi'an", "CN", "Chang'an."),
    "ウマイヤ朝": ("Damascus", "SY", ""),
    "高麗": ("Kaesong", "KP", ""),
    "クメール帝国（アンコール）": ("Angkor", "KH", "Near Siem Reap."),
    "シュリーヴィジャヤ": ("Palembang", "ID", ""),
    "マジャパヒト王国": ("Trowulan", "ID", "Capital near Mojokerto/Surabaya."),
    "キエフ大公国": ("Kyiv", "UA", ""),
    "ジェノヴァ共和国": ("Genoa", "IT", ""),
    "マリ帝国": ("Timbuktu", "ML", "Major imperial city; capital Niani is of uncertain location."),
    "元朝中国": ("Beijing", "CN", "Khanbaliq."),
    "ティムール朝": ("Samarkand", "UZ", ""),
    "琉球王国": ("Naha", "JP", "Shuri."),
    "ポーランド・リトアニア共和国": ("Warsaw", "PL", ""),
    "スウェーデン帝国": ("Stockholm", "SE", ""),
    "ロシア帝国（ピョートル後）": ("Saint Petersburg", "RU", ""),
    "清朝中国（中期・交易拡大期）": ("Beijing", "CN", ""),
    "ハワイ王国": ("Honolulu", "US", ""),
    "ズールー王国": ("Ulundi", "ZA", ""),
    "ビルマ（コンバウン朝）": ("Mandalay", "MM", ""),
    "オーストリア＝ハンガリー帝国": ("Vienna", "AT", ""),
    "ナポレオン帝国": ("Paris", "FR", ""),
    "大韓帝国": ("Seoul", "KR", "Hanseong."),
    "満州国": ("Changchun", "CN", "Xinjing, modern Changchun."),
    "南ベトナム": ("Saigon", "VN", ""),
    "チェコスロバキア（共産期）": ("Prague", "CZ", ""),
    "ポーランド（共産期）": ("Warsaw", "PL", ""),
    "ルーマニア（共産期）": ("Bucharest", "RO", ""),
}


def load_cities() -> pd.DataFrame:
    zip_path = RAW_DIR / "cities1000.zip"
    if not zip_path.exists():
        print(f"Downloading {CITIES_URL} ...", file=sys.stderr)
        import urllib.request

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(CITIES_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("cities1000.txt") as f:
            df = pd.read_csv(
                f,
                sep="\t",
                header=None,
                encoding="utf-8",
                usecols=[1, 2, 4, 5, 8],
                names=["name", "asciiname", "lat", "lon", "country"],
            )
    df["name"] = df["name"].astype(str).str.strip()
    df["asciiname"] = df["asciiname"].astype(str).str.strip()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    return df


def lookup(df: pd.DataFrame, name: str, country: str):
    """Find the first GeoNames record matching name (case-insensitive) and country.

    Returns (lat, lon, source, partial).  ``partial`` is True when the match was
    a substring fallback rather than an exact name/asciiname match, so the
    caller can flag the coordinate for review.
    """
    exact = df[
        ((df["name"].str.lower() == name.lower())
         | (df["asciiname"].str.lower() == name.lower()))
        & (df["country"].str.upper() == country.upper())
    ]
    if not exact.empty:
        row = exact.iloc[0]
        return float(row["lat"]), float(row["lon"]), "GeoNames cities1000", False

    # fallback: match asciiname contains; mark as needing review
    sub = df[
        (df["asciiname"].str.lower().str.contains(name.lower(), na=False))
        & (df["country"].str.upper() == country.upper())
    ]
    if not sub.empty:
        row = sub.iloc[0]
        return float(row["lat"]), float(row["lon"]), "GeoNames cities1000 (partial match)", True
    return None, None, None, False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=PROJECT_DIR / "data" / "capitals.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    df = load_cities()
    rows = []
    for entity, (name, country, notes) in CAPITAL_INFO.items():
        if name in MANUAL:
            lat, lon, source = MANUAL[name]
            needs_review = 1 if "Wikipedia" in source else 0
        else:
            lat, lon, source, partial = lookup(df, name, country)
            needs_review = 1 if partial else 0
            if lat is None:
                print(f"  Not found in GeoNames: {name} ({country}) for {entity}", file=sys.stderr)
                lat = lon = None
                source = "NOT FOUND"
                needs_review = 1
        rows.append(
            {
                "entity": entity,
                "capital_name": name,
                "capital_lat": lat,
                "capital_lon": lon,
                "source_ref": source,
                "needs_review": needs_review,
                "notes": notes,
            }
        )

    out = pd.DataFrame(rows)
    out_path = Path(args.output)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
