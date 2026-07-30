#!/usr/bin/env python3
"""Fetch Wikipedia full-text extracts for low-confidence closure-type cases and
populate rater_source_url, rater_source_ref, and rater_source_quote.

For cases already assigned to a non-uncertain category, the script searches the
Wikipedia article for a sentence that supports the assigned category. For
'uncertain' cases, it attempts to infer a category from the article and, if a
clear match is found, upgrades confidence to medium; otherwise it leaves the
category as uncertain with a generic source note.
"""

import html
import re
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
TEMPLATE_PATH = DATA_DIR / "classification_template_draft.csv"
MAPPING_PATH = DATA_DIR / "cliopatria_mapping.csv"
OUT_PATH = DATA_DIR / "classification_template_draft.csv"

USER_AGENT = "network-exclusion-reclass/1.0 (devin@example.com)"
WIKI_API = "https://en.wikipedia.org/w/api.php"

# Some Cliopatria names map poorly to a Wikipedia article. Override to a more
# useful article title for sourcing the classification.
ENTITY_TITLE_OVERRIDE = {
    "アテネ（ペロポネソス戦争後）": "Classical Athens",
    "ズールー王国": "Zulu Kingdom",
    "カルタゴ": "Punic Wars",
    "宋朝中国": "Song dynasty",
    "マムルーク朝エジプト": "Mamluk Sultanate",
    "ヴェネツィア共和国": "Republic of Venice",
    "プトレマイオス朝エジプト": "Ptolemaic Kingdom",
    "高麗": "Goryeo",
    "シュリーヴィジャヤ": "Srivijaya",
    "マジャパヒト王国": "Majapahit",
    "キエフ大公国": "Kievan Rus'",
    "ジェノヴァ共和国": "Republic of Genoa",
    "ビルマ（コンバウン朝）": "Konbaung dynasty",
    "ポーランド・リトアニア共和国": "Polish-Lithuanian Commonwealth",
    "スウェーデン帝国": "Swedish Empire",
    "ローマ帝政後期（西）": "Crisis of the Third Century",
    "ビザンツ帝国（後期）": "Byzantine Empire under the Palaiologos dynasty",
    "オスマン帝国（後期）": "Decline and modernization of the Ottoman Empire",
    "ウマイヤ朝": "Umayyad Caliphate",
    "モンゴル帝国": "Mongol Empire",
    "アケメネス朝ペルシア": "Achaemenid Empire",
    "ローマ共和政〜帝政前期": "Roman Empire",
    "アッバース朝（前期）": "Abbasid Caliphate",
    "アッバース朝（後期）": "Abbasid Caliphate",
    "ポルトガル帝国": "Portuguese Empire",
    "オランダ共和国": "Dutch Republic",
    "ティムール朝": "Timurid Empire",
    "セレウコス朝シリア": "Seleucid Empire",
    "パルティア": "Parthian Empire",
    "ササン朝ペルシア": "Sasanian Empire",
    "クシャーナ朝": "Kushan Empire",
    "クメール帝国（アンコール）": "Khmer Empire",
    "スペイン帝国": "Spanish Empire",
    "大英帝国": "British Empire",
    "ロシア帝国（ピョートル後）": "Russian Empire",
    "唐朝中国": "Tang dynasty",
    "元朝中国": "Yuan dynasty",
    "オスマン帝国（前期）": "Ottoman Empire",
    "ムガル帝国（前期）": "Mughal Empire",
    "ムガル帝国（後期）": "Mughal Empire",
    "漢朝（前漢〜後漢）": "Han dynasty",
    "ビザンツ帝国（前期）": "Byzantine Empire",
    "インカ帝国": "Inca Empire",
    "アステカ帝国": "Aztec Empire",
    "グプタ朝インド": "Gupta Empire",
    "エチオピア帝国": "Ethiopian Empire",
    "マリ帝国": "Mali Empire",
    "シャム（タイ）": "Rattanakosin Kingdom",
    "マケドニア王国（アレクサンドロス後）": "Antigonid Macedonia",
    "明治〜大正日本": "Empire of Japan",
    "米国（モンロー主義期）": "United States",
    "米国（戦後〜冷戦期）": "United States",
    "戦後日本（高度成長期）": "Post-war economic miracle",
}


def fetch_full_text(title: str) -> tuple[str, str, str] | None:
    """Return (clean_text, resolved_title, url) for a Wikipedia article.

    Uses the MediaWiki parse API to retrieve the full rendered HTML, strips
    style/script tags and wikitext, and returns plain text.
    """
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "redirects": "1",
        "format": "json",
    }
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(WIKI_API, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "parse" not in data:
            return None
        raw_html = data["parse"]["text"]["*"]
        resolved_title = data["parse"]["title"]
        # Remove inline styles and scripts
        cleaned = re.sub(r"<style[^>]*>.*?</style>", "", raw_html, flags=re.DOTALL)
        cleaned = re.sub(r"<script[^>]*>.*?</script>", "", cleaned, flags=re.DOTALL)
        text = html.unescape(re.sub(r"<[^>]+>", " ", cleaned))
        text = re.sub(r"\s+", " ", text).strip()
        url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(resolved_title.replace(" ", "_"), safe=",-'()")
        return text, resolved_title, url
    except Exception as e:
        print(f"Error fetching {title}: {e}")
        return None


def split_sentences(text: str) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sents if s.strip() and len(s.strip()) > 15]


def score_sentence(sentence: str, category: str) -> float:
    s = sentence.lower()
    if category == "open":
        pos = [
            "trade", "trading", "route", "silk road", "royal road", "maritime",
            "commerce", "merchant", "connected", "network", "exchange",
            "mediterranean", "indian ocean", "trans-saharan", "caravan",
            "cosmopolitan", "port", "dominant", "hub", "global",
            "integrated into", "pax mongolica", " Pax ", "world system",
            "hegemony", "leading", "major power",
        ]
        neg = ["isolated", "isolation", "cut off", "excluded", "decline", "collapsed"]
        return sum(2 if " " in p else 1 for p in pos if p in s) - 0.5 * sum(1 for n in neg if n in s)
    if category == "tech_network_exclusion":
        pos = [
            "isolated", "peripheral", "cut off", "excluded", "bypassed",
            "behind", "decline", "collapsed", "disintegrated", "conquered",
            "defeated", "rival", "competition", "limited", "pressure",
            "vulnerable", "weakened", "lost", "periphery", "buffer",
            "marginalized", "overshadowed", "bypass", "lost access",
            "eclipsed", "obsolete", "replaced by",
        ]
        return sum(2 if " " in p else 1 for p in pos if p in s)
    if category == "land_isolation":
        pos = [
            "landlocked", "sahara", "sahel", "highland", "highlands",
            "mountain", "mountains", "desert", "interior", "andean",
            "ethiopian highlands", "geographically isolated", "no access",
            "jungle", "rainforest", "remote", "inland", "plateau",
            "limited contact", "cut off from", "no maritime",
            "surrounded by", "isolated from",
        ]
        return sum(2 if " " in p else 1 for p in pos if p in s)
    if category == "maritime_ban":
        pos = [
            "sakoku", "haijin", "maritime prohibition", "closed country",
            "isolationist", "forbade", "ban on", "overseas trade",
            "expulsion", "seclusion", "naval", "shipbuilding",
        ]
        return sum(1 for p in pos if p in s)
    if category == "bloc":
        pos = [
            "bloc", "alliance", "warsaw pact", "nato", "cold war",
            "non-aligned", "tito", "soviet", "socialist", "satellite",
            "yugoslavia", "warsaw treaty",
        ]
        return sum(1 for p in pos if p in s)
    if category == "patron_open":
        pos = [
            "protectorate", "patron", "client state", "dependent", "puppet",
            "sponsored", "backed by", "alliance with", "aid from", "supported by",
            "guaranteed by", "sphere of influence",
        ]
        return sum(1 for p in pos if p in s)
    return 0.0


def infer_category(sentence: str) -> str | None:
    cats = ["maritime_ban", "bloc", "patron_open", "land_isolation", "tech_network_exclusion", "open"]
    scores = {c: score_sentence(sentence, c) for c in cats}
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return None


def best_sentence(sentences: list[str], category: str) -> tuple[str, float] | None:
    best = None
    best_score = -1.0
    for sent in sentences:
        sc = score_sentence(sent, category)
        if sc > best_score:
            best_score = sc
            best = sent
    if best and best_score > 0:
        return best, best_score
    return None


def title_for(entity: str, clio_name: str) -> str:
    if entity in ENTITY_TITLE_OVERRIDE:
        return ENTITY_TITLE_OVERRIDE[entity]
    if isinstance(clio_name, str):
        return clio_name.split("/")[0].strip()
    return entity


def main():
    df = pd.read_csv(TEMPLATE_PATH, encoding="utf-8-sig")
    mapping = pd.read_csv(MAPPING_PATH, encoding="utf-8-sig")[["entity", "clio_name"]].drop_duplicates()
    df = df.merge(mapping, on="entity", how="left")

    low_mask = df["rater_confidence"].isin(["low"]) | df["rater_closure_type"].isna()
    to_update = df[low_mask & df["clio_name"].notna()].copy()
    print(f"Filling sources for {len(to_update)} low-confidence cases.")

    updated = 0
    for idx, row in to_update.iterrows():
        title = title_for(row["entity"], row["clio_name"])
        print(f"  {row['entity']} -> {title}")
        res = fetch_full_text(title)
        time.sleep(0.5)
        if res is None:
            print(f"    No full text for {title}")
            continue
        text, resolved_title, url = res
        ref = f"Wikipedia, {resolved_title}"
        sentences = split_sentences(text)

        current_cat = row["rater_closure_type"]
        if current_cat == "uncertain":
            # Prefer a sentence that yields a high score for any category
            best_sent = None
            best_score = -1
            best_cat = None
            for sent in sentences:
                cat = infer_category(sent)
                if cat:
                    sc = score_sentence(sent, cat)
                    if sc > best_score:
                        best_score = sc
                        best_sent = sent
                        best_cat = cat
            if best_cat and best_score > 1:
                current_cat = best_cat
                quote = best_sent[:500]
                confidence = "medium"
            elif sentences:
                quote = sentences[0][:500]
                confidence = "low"
            else:
                quote = ""
                confidence = "low"
        else:
            candidate = best_sentence(sentences, str(current_cat))
            if candidate:
                quote, _ = candidate
                confidence = "medium"
            elif sentences:
                # Try any category as a fallback
                alt = None
                alt_score = -1
                for sent in sentences:
                    cat = infer_category(sent)
                    if cat:
                        sc = score_sentence(sent, cat)
                        if sc > alt_score:
                            alt_score = sc
                            alt = (sent, cat)
                if alt and alt_score > 1:
                    quote, fallback_cat = alt
                    current_cat = fallback_cat
                    confidence = "medium"
                else:
                    quote = sentences[0][:500]
                    confidence = "low"
            else:
                quote = ""
                confidence = "low"

        df.at[idx, "rater_closure_type"] = current_cat
        df.at[idx, "rater_source_url"] = url
        df.at[idx, "rater_source_ref"] = ref
        df.at[idx, "rater_source_quote"] = quote[:500]
        df.at[idx, "rater_notes"] = "Source from Wikipedia; review with a specialized historical source before submission."
        if confidence == "medium" and (pd.isna(df.at[idx, "rater_confidence"]) or df.at[idx, "rater_confidence"] == "low"):
            df.at[idx, "rater_confidence"] = confidence
        updated += 1

    df = df.drop(columns=["clio_name"], errors="ignore")
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Updated {updated} rows. Saved to {OUT_PATH}")
    print(df["rater_confidence"].value_counts(dropna=False).to_string())
    print(df["rater_closure_type"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
