#!/usr/bin/env python3
"""Apply a set of historically-informed corrections to polity_geometry_mapping.csv.

These corrections reduce the most obvious modern-country overestimates for empires
and city-states whose ISO-3 mapping included territories they did not control at
their peak.  The rationales are short; the rows remain flagged `needs_review=1`
where appropriate.  Run this before `reconstruct_relative_pop.py`.
"""

import csv
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
MAPPING_PATH = PROJECT_DIR / "data" / "polity_geometry_mapping.csv"

# Entity -> (iso3_codes, admin1_codes, note_append)
# Empty admin1_codes keeps the existing value; None iso3_codes keeps existing.
CORRECTIONS: dict[str, tuple[str | None, str | None, str]] = {
    # British Empire: remove independent USA / Argentina / Chile
    "大英帝国": (
        "GBR|IRL|CAN|IND|PAK|BGD|LKA|MMR|MYS|SGP|AUS|NZL|ZAF|EGY|SDN|KEN|TZA|UGA|GHA|NGA|JOR|IRQ|ISR|PSX|LBN|KWT|QAT|BHR|ARE|OMN|YEM|GUY|JAM|TTO|BHS|FJI|PNG|VUT|SLB",
        None,
        "Removed USA, ARG, CHL (not British territory at 1920).",
    ),
    # Imperial Preference is a trade policy, not territory; use UK+Irish core
    "英国帝国特恵制度": (
        "GBR|IRL",
        None,
        "Trade bloc, not territory; population proxy reduced to UK and Ireland.",
    ),
    # 1930s Japanese sphere: replace full China/Mongolia with Manchukuo proxy
    "1930s日本（大東亜共栄圏）": (
        "JPN|KOR|PRK|TWN|VNM|LAO|KHM|THA|MYS|IDN|PHL|MMR|CHN",
        "CHN:Liaoning|CHN:Jilin|CHN:Heilongjiang|CHN:Inner Mongolia",
        "Replaced full CHN/MNG with Manchuria (Manchukuo) proxy. Occupation elsewhere not captured.",
    ),
    # Timurid Empire did not hold India or modern Pakistan long-term
    "ティムール朝": (
        "UZB|AFG|IRN|IRQ|SYR|TUR|ARM|GEO|AZE|KAZ|KGZ|TJK|TKM",
        None,
        "Removed IND/PAK; Timurid core was Persia/Central Asia/Mesopotamia.",
    ),
    # Kushan: northern India only, no Xinjiang/Kazakhstan
    "クシャーナ朝": (
        "IND|PAK|AFG|UZB|TKM|KGZ|TJK",
        "IND:Punjab|IND:Haryana|IND:Delhi|IND:Rajasthan|IND:Uttar Pradesh|IND:Gujarat|IND:Jammu and Kashmir|IND:Himachal Pradesh|IND:Chandigarh|IND:Uttarakhand",
        "Restricted India to northern/western provinces; removed CHN/KAZ.",
    ),
    # Antigonid Macedon after Alexander: core Balkans/Greece, not Asia/Africa/India
    "マケドニア王国（アレクサンドロス後）": (
        "GRC|MKD|ALB|SRB|HRV|SVN|BIH|MNE|BGR",
        None,
        "Reduced to Antigonid core in Greece/Macedon/Illyria/Thrace.",
    ),
    # Russian Empire: remove full USA (only Alaska); Alaska omitted as tiny population
    "ロシア帝国（ピョータル後）": (
        "RUS|UKR|BLR|MDA|LVA|EST|LTU|GEO|ARM|AZE|KAZ|UZB|TKM|KGZ|TJK|FIN|POL",
        None,
        "Removed USA; Alaska population negligible relative to empire.",
    ),
    # Napoleonic Empire: satellites and annexations, not Eastern Europe/North Africa/Russia
    "ナポレオン帝国": (
        "FRA|BEL|NLD|ITA|ESP|PRT|CHE|POL|HRV|SVN|BIH|MNE",
        None,
        "Removed North Africa, Austria, Hungary, Russia, Balkans beyond Illyria, Greece.",
    ),
    # Swedish Empire: full Germany/Poland/Denmark/Norway were not Swedish core
    "スウェーデン帝国": (
        "SWE|FIN|EST|LVA",
        None,
        "Removed full DEU/POL/DNK/NOR; core is Sweden/Finland/Baltic provinces.",
    ),
    # Austria-Hungary: remove full Italy, Poland, Ukraine, Romania, Albania
    "オーストリア＝ハンガリー帝国": (
        "AUT|HUN|CZE|SVK|HRV|SVN|BIH|SRB|MNE|MKD",
        None,
        "Removed full ITA/POL/UKR/ROU/ALB; core dual monarchy plus Balkan possessions.",
    ),
    # Spanish Empire: remove full Netherlands, Belgium independent by 1600, North Africa enclaves, USA
    "スペイン帝国": (
        "ESP|MEX|COL|PER|BOL|ARG|CHL|ECU|VEN|PRY|URY|CUB|PHL|PRT",
        None,
        "Removed NLD/BEL/ITA (Netherlands independent; only Milan/Naples/Sicily under Spain), North African enclaves, USA; kept Iberian Union and Portuguese crown.",
    ),
    # Seleucid Empire: ceded Indus valley to Maurya after 305 BC
    "セレウコス朝シリア": (
        "SYR|IRQ|LBN|ISR|JOR|TUR|IRN|AFG|UZB|TKM|KGZ|TJK|ARM|GEO|AZE",
        None,
        "Removed PAK (Indus ceded to Maurya).",
    ),
    # Parthian Empire: no Indus, no western Anatolia
    "パルティア": (
        "IRN|IRQ|SYR|LBN|ISR|JOR|ARM|GEO|AZE|TKM|UZB|AFG",
        None,
        "Removed PAK and TUR (Anatolia Roman).",
    ),
    # Sasanian peak c. 620: did not hold Anatolia or most of Arabia; Egypt only briefly
    "ササン朝ペルシア": (
        "IRN|IRQ|SYR|LBN|ISR|JOR|ARM|GEO|AZE|AFG|PAK|TKM|UZB|KGZ|TJK|KAZ",
        None,
        "Removed TUR, EGY, and Arabian peninsula (SAU/YEM/OMN/ARE/QAT/BHR/KWT); core Persia/Mesopotamia/Caucasus/Central Asia.",
    ),
    # Early Abbasid: North Africa west of Tunisia and Anatolia were not under Baghdad
    "アッバース朝（前期）": (
        "IRQ|SYR|LBN|ISR|JOR|EGY|LBY|TUN|SAU|YEM|OMN|QAT|BHR|KWT|IRN|AFG|PAK|AZE|ARM|GEO|TKM|UZB|KGZ|KAZ",
        None,
        "Removed TUR, DZA, MAR; North Africa and Anatolia outside direct Abbasid control; omitted UAE/ARE proxy for uncontrolled interior.",
    ),
    # Early Rome: Armenia/Georgia/Azerbaijan/Iraq not permanent provinces; Mesopotamia only 116-117
    "ローマ共和政〜帝政前期": (
        "ITA|FRA|ESP|PRT|GBR|BEL|CHE|AUT|HUN|ROU|BGR|SRB|HRV|SVN|BIH|MNE|MKD|ALB|GRC|TUR|SYR|LBN|ISR|JOR|EGY|LBY|TUN|DZA|MAR",
        None,
        "Removed IRQ, GEO, AZE, ARM, MDA (not permanent provinces).",
    ),
    # Achaemenid Persia: add Bactria/Sogdia/Armenia/Caucasus/Cyprus/Cyrenaica
    "アケメネス朝ペルシア": (
        "IRN|IRQ|TUR|SYR|EGY|AFG|PAK|UZB|TKM|KGZ|TJK|ARM|GEO|AZE|CYP|LBY",
        None,
        "Added Central Asia (UZB/TKM/KGZ/TJK), Caucasus (ARM/GEO/AZE), Cyprus and Cyrenaica (LBY/CYP).",
    ),
    # Khmer Empire: remove Malaysia/Indonesia/Myanmar (Malay/Malay influence only)
    "クメール帝国（アンコール）": (
        "KHM|THA|LAO|VNM",
        None,
        "Removed MMR/MYS/IDN; core mainland Southeast Asia.",
    ),
    # Srivijaya: Sumatra/Malay Peninsula, not Thailand/Philippines
    "シュリーヴィジャヤ": (
        "IDN|MYS|SGP",
        "IDN:Aceh|IDN:North Sumatra|IDN:West Sumatra|IDN:South Sumatra|IDN:Bengkulu|IDN:Jambi|IDN:Riau|IDN:Riau Islands|IDN:Lampung|IDN:Bangka Belitung Islands|MYS:Kedah|MYS:Perlis|MYS:Penang|MYS:Perak|MYS:Selangor|MYS:Negeri Sembilan|MYS:Melaka|MYS:Johor|MYS:Pahang|MYS:Terengganu|MYS:Kelantan|MYS:Kuala Lumpur|MYS:Putrajaya|MYS:Labuan",
        "Restricted to Sumatra and the Malay Peninsula; removed THA/PHL.",
    ),
    # Majapahit: core Java/Bali, not Philippines/Brunei/Malaysia
    "マジャパヒト王国": (
        "IDN",
        "IDN:East Java|IDN:Central Java|IDN:West Java|IDN:Banten|IDN:Yogyakarta|IDN:Bali",
        "Restricted to Java and Bali; removed MYS/PHL/TLS/BRN.",
    ),
    # Ottoman: remove full Iran and reduce Arabian proxy; Anatolia/Balkans/Levant/N Africa/Iraq core
    "オスマン帝国（前期）": (
        "TUR|GRC|BGR|SRB|HRV|BIH|MNE|MKD|ALB|ROU|MDA|HUN|AUT|SYR|LBN|ISR|JOR|EGY|LBY|TUN|DZA|IRQ|AZE|ARM|GEO",
        None,
        "Removed IRN and Arabian peninsula interior (SAU/YEM/OMN/ARE/QAT/BHR/KWT); Persian mainland never under Ottoman rule.",
    ),
    "オスマン帝国（後期）": (
        "TUR|GRC|BGR|SRB|HRV|BIH|MNE|MKD|ALB|ROU|MDA|HUN|AUT|SYR|LBN|ISR|JOR|EGY|LBY|TUN|DZA|IRQ",
        None,
        "Removed IRN and Arabian peninsula interior (SAU/YEM/OMN/ARE/QAT/BHR/KWT); core Ottoman territories in the Balkans, Anatolia, Levant and North Africa.",
    ),
    # Byzantium late: remove Egypt/Syria/Levant lost to Arabs by 1025
    "ビザンツ帝国（後期）": (
        "TUR|GRC|BGR|SRB|HRV|BIH|MNE|MKD|ALB|ROU|MDA|ITA|CYP",
        None,
        "Removed SYR/LBN/ISR/JOR/EGY/LBY/TUN/DZA; Anatolian/Balkan/Italian core c. AD 1025.",
    ),
    # Carthage: Phoenician-Punic sphere in North Africa and western Mediterranean; not peninsular Italy
    "カルタゴ": (
        "TUN|DZA|LBY|ESP|PRT",
        None,
        "Removed ITA (mainland Italy was not Carthaginian); kept Iberian/North African sphere as proxy.",
    ),
    # Meiji Japan: Taiwan acquired in 1895, Korea not annexed until 1910
    "明治〜大正日本": (
        "JPN|TWN",
        None,
        "Removed KOR/PRK; Korea was independent until 1910.",
    ),
    # Mamluk Sultanate: Egypt/Syria/Hejaz, not full Arabia or North Africa west of Egypt
    "マムルーク朝エジプト": (
        "EGY|SYR|LBN|ISR|JOR|SAU|YEM",
        None,
        "Removed LBY/TUN and interior Arabia proxy; Mamluk core was Egypt, Syria and the Hejaz.",
    ),
}


def main():
    if not MAPPING_PATH.exists():
        print(f"Error: {MAPPING_PATH} not found", file=sys.stderr)
        sys.exit(1)

    rows: list[dict] = []
    with MAPPING_PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            entity = row["entity"].strip()
            if entity in CORRECTIONS:
                new_iso, new_admin1, note_append = CORRECTIONS[entity]
                if new_iso is not None:
                    row["iso3_codes"] = new_iso
                if new_admin1 is not None:
                    row["admin1_codes"] = new_admin1
                row["notes"] = f"{row.get('notes','').strip()}; {note_append}".strip("; ")
                # Keep needs_review flagged because these are still approximations
                row["needs_review"] = "1"
                print(f"Updated {entity}", file=sys.stderr)
            rows.append(row)

    with MAPPING_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {MAPPING_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
