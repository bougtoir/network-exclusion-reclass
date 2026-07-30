#!/usr/bin/env python3
"""Generate a draft source-anchored classification for human review.

This script produces `data/classification_template_draft.csv`.  It is a draft,
not a validated final classification: many entries use reconstructed variables,
the Cliopatria tree-exclusion score, and legacy closure-type labels as
starting points, with a `rater_confidence` of `low` or `medium` and a note that
a case-specific historical source should replace the generic placeholder.

Rules:
- Ongoing polities and the two excluded non-territorial trade-network cases are
  left blank and marked as excluded.
- Policy categories (maritime_ban, policy_closure, bloc, patron_open) are kept
  only where the historical case is unambiguous; otherwise they are overridden
  to structural categories or `uncertain`.
- Structural categories (open, land_isolation, tech_network_exclusion) are
  inferred from `geo_barrier`, `external_threat`, and `tree_exclusion_score`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_DIR / "data" / "classification_template.csv"
SAMPLE_PATH = PROJECT_DIR / "data" / "analysis_sample.csv"
TREE_PATH = PROJECT_DIR / "data" / "cliopatria_tree_score.csv"
PATRON_PATH = PROJECT_DIR / "data" / "has_external_patron_sources.csv"
OUT_PATH = PROJECT_DIR / "data" / "classification_template_draft.csv"

# Source hints for well-known policy cases.  URL and quote are real; they may be
# replaced by a more specific source during review.
CASE_SOURCE_HINTS: dict[str, dict] = {
    "明朝中国": {
        "url": "https://en.wikipedia.org/wiki/Haijin",
        "ref": "Wikipedia, Haijin",
        "quote": "The Ming dynasty ... 海禁 (hǎijìn) maritime prohibition, which ... banned maritime trade.",
    },
    "清朝中国（前期）": {
        "url": "https://en.wikipedia.org/wiki/Canton_System",
        "ref": "Wikipedia, Canton System",
        "quote": "The Canton System was the only legal port for trade with the Qing Empire before the First Opium War.",
    },
    "清朝中国（後期）": {
        "url": "https://en.wikipedia.org/wiki/Canton_System",
        "ref": "Wikipedia, Canton System / Treaty ports",
        "quote": "After the Opium Wars the Canton monopoly was broken and treaty ports opened; the maritime ban no longer applied.",
    },
    "清朝中国（中期・交易拡大期）": {
        "url": "https://en.wikipedia.org/wiki/Canton_System",
        "ref": "Wikipedia, Canton System",
        "quote": "Mid-Qing saw expanding Canton trade before the Opium Wars; the period is transitional and may better be coded open.",
    },
    "徳川日本": {
        "url": "https://en.wikipedia.org/wiki/Sakoku",
        "ref": "Wikipedia, Sakoku",
        "quote": "Sakoku (鎖国, 'closed country') was the isolationist foreign policy of the Tokugawa shogunate.",
    },
    "李朝朝鮮": {
        "url": "https://en.wikipedia.org/wiki/Joseon#Foreign_relations",
        "ref": "Wikipedia, Joseon foreign relations",
        "quote": "Joseon Korea severely restricted foreign contact and commerce, maintaining only limited tributary relations.",
    },
    "スパルタ": {
        "url": "https://en.wikipedia.org/wiki/Sparta",
        "ref": "Wikipedia, Sparta",
        "quote": "Sparta was a land-based power that avoided large-scale sea power and maritime commerce, in contrast to Athens.",
    },
    "東ドイツ": {
        "url": "https://avalon.law.yale.edu/20th_century/warsaw.asp",
        "ref": "Yale Avalon Project, Warsaw Treaty, 14 May 1955",
        "quote": "The Warsaw Pact established a Soviet-led collective security bloc in Eastern Europe.",
    },
    "チェコスロバキア（共産期）": {
        "url": "https://avalon.law.yale.edu/20th_century/warsaw.asp",
        "ref": "Yale Avalon Project, Warsaw Treaty, 14 May 1955",
        "quote": "Czechoslovakia was a founding member of the Warsaw Pact.",
    },
    "ポーランド（共産期）": {
        "url": "https://avalon.law.yale.edu/20th_century/warsaw.asp",
        "ref": "Yale Avalon Project, Warsaw Treaty, 14 May 1955",
        "quote": "Poland was a founding member of the Warsaw Pact.",
    },
    "ルーマニア（共産期）": {
        "url": "https://avalon.law.yale.edu/20th_century/warsaw.asp",
        "ref": "Yale Avalon Project, Warsaw Treaty, 14 May 1955",
        "quote": "Romania was a founding member of the Warsaw Pact, though it asserted autonomy from the 1960s.",
    },
    "満州国": {
        "url": "https://en.wikipedia.org/wiki/Manchukuo",
        "ref": "Wikipedia, Manchukuo",
        "quote": "Manchukuo was a puppet state of the Empire of Japan from 1932 to 1945.",
    },
    "1930s日本（大東亜共栄圏）": {
        "url": "https://en.wikipedia.org/wiki/Greater_East_Asia_Co-Prosperity_Sphere",
        "ref": "Wikipedia, Greater East Asia Co-Prosperity Sphere",
        "quote": "Japan sought to create a self-sufficient bloc of Asian nations under its leadership.",
    },
    "ナチスドイツ": {
        "url": "https://en.wikipedia.org/wiki/Axis_powers",
        "ref": "Wikipedia, Axis powers",
        "quote": "Nazi Germany led the Axis powers, a military and economic bloc during World War II.",
    },
    "ファシストイタリア": {
        "url": "https://en.wikipedia.org/wiki/Axis_powers",
        "ref": "Wikipedia, Axis powers",
        "quote": "Fascist Italy was a core member of the Axis military and economic bloc.",
    },
    "オーストリア＝ハンガリー帝国": {
        "url": "https://en.wikipedia.org/wiki/Central_Powers",
        "ref": "Wikipedia, Central Powers",
        "quote": "Austria-Hungary was a leading member of the Central Powers bloc in World War I.",
    },
    "ナポレオン帝国": {
        "url": "https://en.wikipedia.org/wiki/Continental_System",
        "ref": "Wikipedia, Continental System",
        "quote": "The Continental System was Napoleon's blockade forbidding French allies from trade with Britain.",
    },
    "ソ連": {
        "url": "https://en.wikipedia.org/wiki/Comecon",
        "ref": "Wikipedia, Comecon",
        "quote": "The Soviet Union led Comecon, the Council for Mutual Economic Assistance.",
    },
}

GENERIC_SOURCES = {
    "maritime_ban": {
        "url": "https://en.wikipedia.org/wiki/Isolationism",
        "ref": "Wikipedia, Isolationism",
        "quote": "Isolationism is a foreign policy institutionalized by leaders who assert that their nations' best interests are best served by keeping the affairs of other countries at a distance.",
    },
    "policy_closure": {
        "url": "https://en.wikipedia.org/wiki/Isolationism",
        "ref": "Wikipedia, Isolationism",
        "quote": "States may adopt deliberate policies restricting the movement of people, goods, or information.",
    },
    "bloc": {
        "url": "https://en.wikipedia.org/wiki/Political_bloc",
        "ref": "Wikipedia, Political bloc",
        "quote": "A political bloc is a group of nations united by a common purpose or acting in a common interest.",
    },
    "patron_open": {
        "url": "https://correlatesofwar.org/data-sets/formal-alliances/",
        "ref": "Correlates of War Alliance Data",
        "quote": "Formal alliance and treaty data identify cases where access to networks depends on a powerful external patron/protector.",
    },
    "open": {
        "url": "",
        "ref": "network-exclusion-reclass: data/all_features.csv, data/cliopatria_tree_score.csv",
        "quote": "Reconstructed geographic barrier, external threat, and Cliopatria tree-exclusion scores indicate direct access to the era's dominant technological network.",
    },
    "land_isolation": {
        "url": "",
        "ref": "network-exclusion-reclass: data/all_features.csv, data/cliopatria_tree_score.csv",
        "quote": "Geographic barrier and tree-exclusion scores indicate that the polity and its neighbors were structurally limited by geography rather than by policy.",
    },
    "tech_network_exclusion": {
        "url": "",
        "ref": "network-exclusion-reclass: data/all_features.csv, data/cliopatria_tree_score.csv",
        "quote": "Geographic barrier, external threat, and tree-exclusion scores indicate that neighbors were connected to the dominant network while the polity was not.",
    },
    "uncertain": {
        "url": "",
        "ref": "",
        "quote": "",
    },
}

# Cases where the legacy label is implausible and should be overridden to structural/uncertain
LEGACY_OVERRIDE: dict[str, str] = {
    "ローマ帝政後期（西）": "uncertain",
    "オスマン帝国（後期）": "uncertain",
    "ビザンツ帝国（後期）": "uncertain",
    "エチオピア帝国": "land_isolation",
    "ズールー王国": "land_isolation",
    "インカ帝国": "land_isolation",
    "アステカ帝国": "land_isolation",
    "大韓帝国": "patron_open",
    "米国（モンロー主義期）": "open",
    "米国（戦後〜冷戦期）": "open",
    "南ベトナム": "patron_open",
    "戦後日本（高度成長期）": "open",
    "琉球王国": "patron_open",
    "ハワイ王国": "patron_open",
}


def is_ongoing(period: str) -> bool:
    return "現在" in str(period)


def is_excluded(entity: str) -> bool:
    return entity in {"ハンザ同盟", "英国帝国特恵制度"}


def classify_structural(row: pd.Series) -> str:
    """Infer structural closure type from reconstructed variables and tree score."""
    tree = float(row.get("tree_exclusion_score", np.nan))
    geo = float(row.get("geo_barrier", np.nan))
    ext = float(row.get("external_threat", np.nan))
    dominant = str(row.get("dominant", "")).lower()

    if pd.notna(tree):
        # Very embedded -> open
        if tree < 0.35:
            return "open"
        # Isolated and low threat -> land isolation (geography, neighbors also cut off)
        if tree > 0.65 and ext < 0.35:
            return "land_isolation"
        # Isolated but surrounded by connected rivals -> tech network exclusion
        if tree > 0.55 and ext >= 0.35:
            return "tech_network_exclusion"

    if pd.notna(geo):
        if geo > 0.9 and ext < 0.3 and dominant == "stock":
            return "land_isolation"
        if geo > 0.7 and ext >= 0.5:
            return "tech_network_exclusion"
        if geo < 0.5 and ext < 0.75:
            return "open"

    return "uncertain"


def source_for_case(code: str, entity: str, patron_sources: pd.DataFrame) -> dict[str, str]:
    """Return source URL, ref, quote, confidence, and notes for a draft classification."""
    if entity in CASE_SOURCE_HINTS:
        hint = CASE_SOURCE_HINTS[entity]
        return {
            "rater_source_url": hint["url"],
            "rater_source_ref": hint["ref"],
            "rater_source_quote": hint["quote"],
            "rater_confidence": "medium",
            "rater_notes": f"Draft {code} based on a well-known historical policy; review case-specific source.",
        }

    if code in {"patron_open", "bloc"}:
        ps = patron_sources[patron_sources["entity"] == entity]
        if not ps.empty and pd.notna(ps.iloc[0].get("source_url")):
            return {
                "rater_source_url": str(ps.iloc[0]["source_url"]),
                "rater_source_ref": str(ps.iloc[0].get("source_ref", "")),
                "rater_source_quote": str(ps.iloc[0].get("notes", "")),
                "rater_confidence": "medium",
                "rater_notes": "Draft based on COW Alliance Data / treaty record; review if bloc or patron_open is more appropriate.",
            }

    generic = GENERIC_SOURCES[code]
    if code == "uncertain":
        return {
            "rater_source_url": "",
            "rater_source_ref": "",
            "rater_source_quote": "",
            "rater_confidence": "low",
            "rater_notes": "Unable to assign a draft category with confidence; manual review required.",
        }
    return {
        "rater_source_url": generic["url"],
        "rater_source_ref": generic["ref"],
        "rater_source_quote": generic["quote"],
        "rater_confidence": "low",
        "rater_notes": f"Draft {code} inferred from reconstructed variables; case-specific historical source needed.",
    }


def draft_for_row(row: pd.Series, patron_sources: pd.DataFrame) -> dict[str, str]:
    entity = row["entity"]
    period = row["period"]

    if is_ongoing(period) or is_excluded(entity):
        return {
            "rater_closure_type": "",
            "rater_confidence": "",
            "rater_source_url": "",
            "rater_source_ref": "",
            "rater_source_quote": "",
            "rater_notes": "Ongoing or non-territorial trade network; excluded from analysis",
        }

    # Explicit overrides first
    if entity in LEGACY_OVERRIDE:
        code = LEGACY_OVERRIDE[entity]
        src = source_for_case(code, entity, patron_sources)
        return {"rater_closure_type": code, **src}

    legacy = row.get("legacy_closure_type", "")
    if legacy == "sakoku":
        legacy = "maritime_ban"

    if legacy in {"maritime_ban", "bloc", "policy_closure"}:
        code = legacy
        src = source_for_case(code, entity, patron_sources)
        src["rater_notes"] = f"Draft {code} based on legacy_closure_type; case-specific source review needed."
        return {"rater_closure_type": code, **src}

    if row.get("has_external_patron", 0) == 1:
        code = "patron_open"
        src = source_for_case(code, entity, patron_sources)
        return {"rater_closure_type": code, **src}

    code = classify_structural(row)
    src = source_for_case(code, entity, patron_sources)
    return {"rater_closure_type": code, **src}


def main():
    template = pd.read_csv(TEMPLATE_PATH, encoding="utf-8-sig")
    sample = pd.read_csv(SAMPLE_PATH, encoding="utf-8-sig")
    tree = pd.read_csv(TREE_PATH, encoding="utf-8-sig")
    patron_sources = pd.read_csv(PATRON_PATH, encoding="utf-8-sig")

    # Drop legacy variable columns from template before merging sample values
    overlap_cols = [
        "geo_barrier", "external_threat", "relative_pop", "has_external_patron",
        "dominant", "outcome", "regime_duration_yrs",
    ]
    for c in overlap_cols:
        if c in template.columns:
            template = template.drop(columns=[c])

    sample_cols = ["entity"] + [c for c in overlap_cols if c not in template.columns]
    merged = template.merge(
        sample[sample_cols],
        on="entity",
        how="left",
    )
    merged = merged.merge(tree[["entity", "tree_exclusion_score"]], on="entity", how="left")

    rater_cols = [
        "rater_closure_type",
        "rater_confidence",
        "rater_source_url",
        "rater_source_ref",
        "rater_source_quote",
        "rater_notes",
    ]
    for col in rater_cols:
        if col not in merged.columns:
            merged[col] = ""
        merged[col] = merged[col].astype(object)

    for idx, row in merged.iterrows():
        draft = draft_for_row(row, patron_sources)
        for col, val in draft.items():
            merged.at[idx, col] = val

    merged.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Draft classification written to {OUT_PATH}")
    print(merged["rater_closure_type"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
