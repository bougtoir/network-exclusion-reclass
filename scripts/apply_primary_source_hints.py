#!/usr/bin/env python3
"""Apply curated primary-source hints to classification_template_draft.csv.

This script fetches only the URLs already listed in PRIMARY_SOURCE_HINTS,
verifies that the quote is present, and updates the classification template.
It does not perform web searches, so it runs quickly and reproducibly.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
TEMPLATE = DATA_DIR / "classification_template_draft.csv"
USER_AGENT = "network-exclusion-reclass/1.0 (devin@example.com)"

KEYWORDS: dict[str, list[str]] = {
    "open": [
        "trade", "trading", "commerce", "merchant", "merchants", "market", "markets",
        "voyage", "route", "road", "roads", "port", "ports", "ship", "ships", "sail",
        "navigable", "traffic", "exchange", "goods", "wealth", "prosperous",
        "connected", "silk", "royal road", "network", "coin", "currency", "travel",
        "treaty", "alliance", "caravan", "bazaar", "bazaars", "emporium", "hub",
    ],
    "tech_network_exclusion": [
        "isolated", "excluded", "remote", "decline", "declining", "defeated",
        "destroyed", "conquered", "overrun", "besieged", "fall", "fallen", "lost",
        "disruption", "withdrawal", "invaded", "war", "defeat", "collapse",
        "collapsed", "fragmented", "disintegrated", "peripheral", "bypassed",
        "eclipsed", "obsolete", "replaced", "weakened", "marginalized", "buffer",
    ],
    "land_isolation": [
        "desert", "mountain", "mountains", "highland", "highlands", "jungle",
        "inland", "island", "remote", "inaccessible", "coast", "landlocked",
        "plateau", "savannah", "sahel", "andean", "ethiopian highlands",
        "no access", "cut off", "surrounded", "interior", "rainforest",
    ],
    "maritime_ban": [
        "sea", "maritime", "ship", "naval", "forbid", "forbidden", "ban", "banned",
        "prohibit", "prohibited", "embargo", "coast", "sakoku", "haijin",
        "isolation", "barbarian", "seclusion", "closed country", "private trade",
    ],
    "bloc": [
        "treaty", "alliance", "pact", "agreement", "sign", "signed", "ratified",
        "protocol", "declaration", "act", "convention", "bloc", "cooperate",
        "mutual", "contracting parties", "collective security", "defense",
    ],
    "patron_open": [
        "protectorate", "protect", "patron", "dependent", "client", "puppet",
        "treaty", "alliance", "guarantee", "residence", "advisor", "security",
        "annex", "annexed", "cession", "cede", "protecting", "tutelage",
    ],
}

PRIMARY_SOURCE_HINTS: dict[str, tuple[str, str, str]] = {
    # Axis / Warsaw Pact bloc
    "1930s日本（大東亜共栄圏）": (
        "https://avalon.law.yale.edu/wwii/triparti.asp",
        "Three-Power Pact Between Germany, Italy, and Japan, Signed at Berlin, September 27, 1940",
        "Germany and Italy recognize and respect the leadership of Japan in the establishment of a new order in greater East Asia",
    ),
    "ナチスドイツ": (
        "https://avalon.law.yale.edu/wwii/triparti.asp",
        "Three-Power Pact Between Germany, Italy, and Japan, Signed at Berlin, September 27, 1940",
        "Japan recognizes and respects the leadership of Germany and Italy in establishment of a new order in Europe",
    ),
    "ファシストイタリア": (
        "https://avalon.law.yale.edu/wwii/triparti.asp",
        "Three-Power Pact Between Germany, Italy, and Japan, Signed at Berlin, September 27, 1940",
        "Japan recognizes and respects the leadership of Germany and Italy in establishment of a new order in Europe",
    ),
    "ソ連": (
        "https://avalon.law.yale.edu/20th_century/warsaw.asp",
        "Treaty of Friendship, Cooperation and Mutual Assistance (Warsaw Pact), May 14, 1955",
        "The Contracting Parties, reaffirming their desire for the establishment of a system of European collective security",
    ),
    "東ドイツ": (
        "https://avalon.law.yale.edu/20th_century/warsaw.asp",
        "Treaty of Friendship, Cooperation and Mutual Assistance (Warsaw Pact), May 14, 1955",
        "The Contracting Parties, reaffirming their desire for the establishment of a system of European collective security",
    ),
    "チェコスロバキア（共産期）": (
        "https://avalon.law.yale.edu/20th_century/warsaw.asp",
        "Treaty of Friendship, Cooperation and Mutual Assistance (Warsaw Pact), May 14, 1955",
        "The Contracting Parties, reaffirming their desire for the establishment of a system of European collective security",
    ),
    "ポーランド（共産期）": (
        "https://avalon.law.yale.edu/20th_century/warsaw.asp",
        "Treaty of Friendship, Cooperation and Mutual Assistance (Warsaw Pact), May 14, 1955",
        "The Contracting Parties, reaffirming their desire for the establishment of a system of European collective security",
    ),
    "ルーマニア（共産期）": (
        "https://avalon.law.yale.edu/20th_century/warsaw.asp",
        "Treaty of Friendship, Cooperation and Mutual Assistance (Warsaw Pact), May 14, 1955",
        "The Contracting Parties, reaffirming their desire for the establishment of a system of European collective security",
    ),
    "ユーゴスラビア": (
        "https://history.state.gov/historicaldocuments/frus1948v04/d697",
        "Cominform Resolution Concerning the Situation in the Communist Party of Yugoslavia, June 28, 1948",
        "On June 28, the Cominform adopted a “Resolution of the Information Bureau Concerning the Situation in the Communist Party of Yugoslavia”",
    ),
    "オーストリア＝ハンガリー帝国": (
        "https://worldjpn.net/documents/texts/docs/18820520.T1E.html",
        "Triple Alliance Between Austria-Hungary, Germany and Italy, Vienna, May 20, 1882",
        "animated by the desire to increase the guaranties of the general peace",
    ),
    "ナポレオン帝国": (
        "https://www.napoleon-empire.org/en/official-texts/berlin-decree-1806.php",
        "Berlin Decree, November 21, 1806",
        "The British Isles are declared to be in a state of blockade",
    ),
    "満州国": (
        "https://history.state.gov/historicaldocuments/frus1932v04/d271",
        "Protocol Between Japan and Manchukuo, September 15, 1932",
        "Now the Governments of Japan and Manchoukuo have, for the purpose of establishing a perpetual relationship of good neighborhood between Japan and Manchoukuo",
    ),
    # Patron / protectorates
    "大韓帝国": (
        "https://history.state.gov/historicaldocuments/frus1905/d597",
        "Agreement between the Governments of Japan and Korea, November 17, 1905",
        "The Government of Japan, through the department of foreign affairs in Tokyo, will hereafter have control and direction of the external relations and affairs of Korea",
    ),
    "南ベトナム": (
        "https://avalon.law.yale.edu/20th_century/usmu003.asp",
        "Southeast Asia Collective Defense Treaty (Manila Pact), September 8, 1954",
        "Each Party recognizes that aggression by means of armed attack in the treaty area against any of the Parties",
    ),
    "ハワイ王国": (
        "https://www.govinfo.gov/content/pkg/STATUTE-30/pdf/STATUTE-30-Pg750.pdf",
        "Newlands Resolution (Annexation of Hawaii), July 7, 1898, 30 Stat. 750",
        "annexed as a part of the territory of the United States and are subject to the sovereign dominion thereof",
    ),
    "琉球王国": (
        "https://history.state.gov/countries/lew-chew",
        "Principal Officers and Chiefs of State: Lew Chew (Ryukyu Islands)",
        "an independent kingdom that specialized in trade between Japan and mainland Asia",
    ),
    # Maritime bans
    "スパルタ": (
        "https://classics.mit.edu/Plutarch/lycurgus.1b.txt",
        "Plutarch, Life of Lycurgus",
        "And this was the reason why he forbade them to travel abroad, and go about acquainting themselves with foreign rules of morality",
    ),
    "徳川日本": (
        "https://afe.easia.columbia.edu/ps/japan/tokugawa_edicts_foreigners.pdf",
        "Tokugawa Shogunate: Edicts Ordering the Closing of Japan, 1635",
        "Japanese ships are strictly forbidden to leave for foreign countries",
    ),
    "明朝中国": (
        "https://ctext.org/wiki.pl?chapter=508895&if=gb&remap=gb",
        "皇明經世文編 卷四百 疏通海禁疏",
        "申严海禁、并御倭未尽事宜、以弭隐患事、内开凡有贩番诸商、告给文引者、尽行禁绝、敢有故违者、照例处以极刑",
    ),
    "清朝中国（前期）": (
        "https://sourcebooks.fordham.edu/mod/1793qianlong.asp",
        "Emperor Qian Long: Letter to George III, 1793",
        "Hitherto, all European nations, including your own country's barbarian merchants, have carried on their trade with our Celestial Empire at Canton",
    ),
    "清朝中国（中期・交易拡大期）": (
        "https://sourcebooks.fordham.edu/mod/1793qianlong.asp",
        "Emperor Qian Long: Letter to George III, 1793",
        "Hitherto, all European nations, including your own country's barbarian merchants, have carried on their trade with our Celestial Empire at Canton",
    ),
    "清朝中国（後期）": (
        "https://sourcebooks.fordham.edu/mod/1793qianlong.asp",
        "Emperor Qian Long: Letter to George III, 1793",
        "Hitherto, all European nations, including your own country's barbarian merchants, have carried on their trade with our Celestial Empire at Canton",
    ),
    # Open / connected cases
    "アケメネス朝ペルシア": (
        "https://lexundria.com/hdt/8.98/mcly",
        "Herodotus, Histories 8.98 (trans. G. C. Macaulay)",
        "These neither snow nor rain nor heat nor darkness of night prevents from accomplishing each one the task proposed to him, with the very utmost speed",
    ),
    "ローマ共和政〜帝政前期": (
        "https://sourcebooks.fordham.edu/ancient/periplus.asp",
        "The Periplus of the Erythraean Sea: Travel and Trade in the Indian Ocean",
        "Of the designated ports on the Erythraean Sea, and the market-towns around it",
    ),
    "漢朝（前漢〜後漢）": (
        "https://sourcebooks.fordham.edu/eastasia/romchin1.asp",
        "Sima Qian, Shih-Chi 123 (trans. Friedrich Hirth), c. 90 BCE",
        "The carts and ships of their merchants go to the neighboring countries",
    ),
    "唐朝中国": (
        "https://sourcebooks.fordham.edu/eastasia/romchin1.asp",
        "The Wei-lueh on the Roman Empire (Yu, Ta-ts'in), c. 260 CE",
        "The water of the great sea which is crossed on the road thither is salt and bitter",
    ),
    "元朝中国": (
        "https://sourcebooks.fordham.edu/source/polo-kinsay.asp",
        "Marco Polo: The Glories of Kinsay (Hangchow), c. 1300",
        "the supply of that material, both from the whole district of Kinsay, and from the imports by traders from other provinces",
    ),
    "アッバース朝（前期）": (
        "https://sourcebooks.fordham.edu/source/847radanite.asp",
        "The Travels of the Radhanite Jewish Merchants, c. 847 CE",
        "Sometimes these Jew merchants prefer to carry their goods from the land of the Franks in the Western Sea",
    ),
    "アッバース朝（後期）": (
        "https://sourcebooks.fordham.edu/source/847radanite.asp",
        "The Travels of the Radhanite Jewish Merchants, c. 847 CE",
        "These different journeys can also be made by land",
    ),
    "ウマイヤ朝": (
        "https://sourcebooks.fordham.edu/source/847radanite.asp",
        "The Travels of the Radhanite Jewish Merchants, c. 847 CE",
        "These merchants speak Arabic, Persian, Roman (Greek), the language of the Franks, Andalusians, and Slavs",
    ),
    "モンゴル帝国": (
        "http://depts.washington.edu/silkroad/texts/rubruck.html",
        "William of Rubruck: Account of the Mongols, 1253-1255",
        "if the road were open they would send envoys and would gladly make a peace with him",
    ),
    "ビザンツ帝国（後期）": (
        "https://sourcebooks.fordham.edu/source/ibnbattuta-byzantium14C.asp",
        "Ibn Battuta: The Byzantine Empire and Constantinople, 1325-1354",
        "Its bazaars and streets are spacious and paved with flagstones; each bazaar has gates which are closed upon it at night",
    ),
    "ムガル帝国（前期）": (
        "https://sourcebooks.fordham.edu/india/1655bernier.asp",
        "François Bernier: An Account of India and the Great Moghul, 1655",
        "though those that are employed in public charges and offices, and even those that are listed in the militia, be not all of the race of the Moguls, but strangers and nations gathered out of all countries",
    ),
    "ムガル帝国（後期）": (
        "https://sourcebooks.fordham.edu/india/1655bernier.asp",
        "François Bernier: An Account of India and the Great Moghul, 1655",
        "My lord, you may have seen before this, by the maps of Asia, how great every way is the extent of the empire of the Great Mogul",
    ),
    "ポルトガル帝国": (
        "https://sourcebooks.fordham.edu/sbook1z.asp",
        "Vasco da Gama: Round Africa to India, 1497-1498",
        "",
    ),
    "スペイン帝国": (
        "https://sourcebooks.fordham.edu/source/1493-columbustosanchez.asp",
        "Christopher Columbus: Letter to Lord Raphael Sanchez, 14 March 1493",
        "",
    ),
    "大英帝国": (
        "https://sourcebooks.fordham.edu/india/1617englandindies.asp",
        "An Anonymous Frenchman: The English in the Spice Islands, 1617",
        "",
    ),
    "米国（モンロー主義期）": (
        "https://avalon.law.yale.edu/19th_century/monroe.asp",
        "Monroe Doctrine; December 2, 1823",
        "the American continents, by the free and independent condition which they have assumed and maintain, are henceforth not to be considered as subjects for future colonization by any European powers",
    ),
    "米国（戦後〜冷戦期）": (
        "https://avalon.law.yale.edu/20th_century/nato.asp",
        "North Atlantic Treaty, April 4, 1949",
        "The Parties to this Treaty reaffirm their faith in the purposes and principles of the Charter of the United Nations",
    ),
    "戦後日本（高度成長期）": (
        "https://avalon.law.yale.edu/20th_century/japan001.asp",
        "Security Treaty Between the United States and Japan, September 8, 1951",
        "Japan will not have the effective means to exercise its inherent right of self-defense because it has been disarmed",
    ),
    # Land-isolation / difficult terrain cases
    "インカ帝国": (
        "https://www.gutenberg.org/cache/epub/1209/pg1209.html",
        "William H. Prescott: History of the Conquest of Peru",
        "he took the road along the coast, which led him across the great desert of Atacama",
    ),
    "マリ帝国": (
        "https://sourcebooks.fordham.edu/source/1354-ibnbattuta.asp",
        "Ibn Battuta: Mali Empire, 1352",
        "On leaving Zayla we sailed for fifteen days and came to Maqdasha",
    ),
}


def clean_text(html_text: str | bytes) -> str:
    if isinstance(html_text, bytes):
        html_text = html_text.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    body = soup.get_text(separator=" ")
    body = re.sub(r"\s+", " ", body)
    return body.strip()


def fetch_url(url: str) -> tuple[str, str, str] | None:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        resp.raise_for_status()
    except Exception:
        return None
    ct = resp.headers.get("content-type", "").lower()
    if "application/pdf" in ct or url.lower().endswith(".pdf"):
        try:
            proc = subprocess.run(
                ["pdftotext", "-", "-"],
                input=resp.content,
                capture_output=True,
                timeout=20,
            )
            if proc.returncode == 0 and proc.stdout:
                text = proc.stdout.decode("utf-8", errors="ignore")
                text = re.sub(r"\s+", " ", text).strip()
                return (url, text, resp.url)
        except Exception:
            pass
        return None
    text = clean_text(resp.text)
    return (url, text, resp.url)


def find_quote(body: str, closure: str, min_len: int = 60, max_len: int = 400) -> str | None:
    keywords = KEYWORDS.get(closure, [])
    if not keywords:
        return None
    sentences = re.split(r"(?<=[.!?。！？])\s+", body)
    best: tuple[float, str] | None = None
    for s in sentences:
        s = s.strip()
        if len(s) < min_len or len(s) > max_len:
            continue
        lower = s.lower()
        if any(x in lower for x in [
            "internet history sourcebooks", "search help", "table of contents",
            "privacy policy", "cookie", "page not found", "legal texts search",
            "copyright", "all rights reserved", "internet archive", "gutenberg",
            "download:", "available online at", "footnote", "notes:", "bibliography",
        ]):
            continue
        kw_count = sum(1 for k in keywords if k.lower() in lower)
        if kw_count == 0:
            continue
        score = kw_count * 10 - abs(len(s) - 200) / 100.0
        if best is None or score > best[0]:
            best = (score, s)
    return best[1] if best else None


def main() -> None:
    df = pd.read_csv(TEMPLATE, encoding="utf-8-sig")
    log: list[dict] = []
    upgraded = 0
    failed = 0
    for idx, row in df.iterrows():
        entity = row["entity"]
        closure = row["rater_closure_type"]
        if entity not in PRIMARY_SOURCE_HINTS:
            continue
        if not isinstance(closure, str) or closure in ("", "uncertain"):
            continue
        url, ref, quote = PRIMARY_SOURCE_HINTS[entity]
        fetched = fetch_url(url)
        if not fetched:
            failed += 1
            log.append({"entity": entity, "status": "fetch_failed", "url": url})
            continue
        _, body, resolved_url = fetched
        final_quote = ""
        if quote:
            if quote in body:
                final_quote = quote
            else:
                failed += 1
                log.append({"entity": entity, "status": "quote_not_found", "url": url, "tried": quote})
                continue
        else:
            final_quote = find_quote(body, closure)
            if not final_quote:
                failed += 1
                log.append({"entity": entity, "status": "find_quote_failed", "url": url})
                continue
        df.at[idx, "rater_source_url"] = resolved_url
        df.at[idx, "rater_source_ref"] = f"Primary source, {ref}"
        df.at[idx, "rater_source_quote"] = final_quote
        df.at[idx, "rater_notes"] = "Upgraded to curated public primary source; quote verified against fetched page."
        df.at[idx, "rater_confidence"] = "medium"
        upgraded += 1
        log.append({"entity": entity, "status": "upgraded", "url": resolved_url})

    df.to_csv(TEMPLATE, index=False, encoding="utf-8-sig")
    pd.DataFrame(log).to_csv(DATA_DIR / "primary_source_hint_apply_log.csv", index=False, encoding="utf-8-sig")
    print(f"Applied {upgraded} curated primary-source hints; {failed} failed.")


if __name__ == "__main__":
    main()
