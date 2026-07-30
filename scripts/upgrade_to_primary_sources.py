#!/usr/bin/env python3
"""Upgrade Wikipedia-sourced closure-type citations to public primary sources.

Run this script inside `scripted_tools` because it calls `web_search` and
`web_get_contents` via `devin_tools.call_tool`.  Page fetching is done with
`requests`/`BeautifulSoup` when possible, with a `web_get_contents` fallback for
hosts that are slow or blocked.  PDFs are converted with `pdftotext`.

No fabricated quotes are written: every new quote is verified to be a substring
of the fetched page text.
"""
from __future__ import annotations

import asyncio
import html
import io
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

try:
    from devin_tools import call_tool_sync  # type: ignore
except Exception:
    def call_tool_sync(name: str, args: dict) -> str:
        raise RuntimeError("call_tool_sync is only available in scripted_tools context")


DATA_DIR = REPO / "data"
TEMPLATE = DATA_DIR / "classification_template_draft.csv"
LOG_PATH = DATA_DIR / "primary_source_upgrade_log.csv"
USER_AGENT = "network-exclusion-reclass/1.0 (devin@example.com)"

ENTITY_TITLE_OVERRIDE = {
    "アテネ（ペロポネソス戦争後）": "Classical Athens",
    "ズールー王国": "Zulu Kingdom",
    "カルタゴ": "Carthage",
    "宋朝中国": "Song dynasty",
    "マムルーク朝エジプト": "Mamluk Sultanate",
    "ヴェネツィア共和国": "Republic of Venice",
    "アッバース朝（前期）": "Abbasid Caliphate",
    "アッバース朝（後期）": "Abbasid Caliphate",
    "アケメネス朝ペルシア": "Achaemenid Empire",
    "アステカ帝国": "Aztec Empire",
    "イギリス帝国": "British Empire",
    "インカ帝国": "Inca Empire",
    "オスマン帝国（前期）": "Ottoman Empire",
    "オスマン帝国（後期）": "Ottoman Empire",
    "グプタ朝インド": "Gupta Empire",
    "クメール帝国（アンコール）": "Khmer Empire",
    "クシャーナ朝": "Kushan Empire",
    "ササン朝ペルシア": "Sasanian Empire",
    "サファヴィー朝ペルシア": "Safavid dynasty",
    "シュリーヴィジャヤ": "Srivijaya",
    "スウェーデン帝国": "Swedish Empire",
    "スペイン帝国": "Spanish Empire",
    "セレウコス朝シリア": "Seleucid Empire",
    "ティムール朝": "Timurid Empire",
    "唐朝中国": "Tang dynasty",
    "ナチスドイツ": "Nazi Germany",
    "ナポレオン帝国": "First French Empire",
    "ポーランド・リトアニア共和国": "Polish-Lithuanian Commonwealth",
    "マケドニア王国（アレクサンドロス後）": "Seleucid Empire",
    "マジャパヒト王国": "Majapahit",
    "モンゴル帝国": "Mongol Empire",
    "ローマ共和政〜帝政前期": "Roman Empire",
    "ローマ帝政後期（西）": "Western Roman Empire",
    "ロシア帝国（ピョートル後）": "Russian Empire",
    "ビザンツ帝国（前期）": "Byzantine Empire",
    "ビザンツ帝国（後期）": "Byzantine Empire",
    "パルティア": "Parthian Empire",
    "ポルトガル帝国": "Portuguese Empire",
    "オランダ共和国": "Dutch Republic",
    "米国（モンロー主義期）": "United States",
    "米国（戦後〜冷戦期）": "United States",
    "戦後日本（高度成長期）": "Post-war Japan",
    "大英帝国": "British Empire",
    "明朝中国": "Ming dynasty",
    "清朝中国（前期）": "Qing dynasty",
    "清朝中国（中期・交易拡大期）": "Qing dynasty",
    "清朝中国（後期）": "Qing dynasty",
    "徳川日本": "Tokugawa shogunate",
    "李朝朝鮮": "Joseon",
    "高麗": "Goryeo",
    "ムガル帝国（前期）": "Mughal Empire",
    "ムガル帝国（後期）": "Mughal Empire",
    "キエフ大公国": "Kievan Rus'",
    "エチオピア帝国": "Ethiopian Empire",
    "シャム（タイ）": "Ayutthaya Kingdom",
    "1930s日本（大東亜共栄圏）": "Empire of Japan",
    "ファシストイタリア": "Fascist Italy",
    "ソ連": "Soviet Union",
    "東ドイツ": "East Germany",
    "ユーゴスラビア": "Yugoslavia",
    "マリ帝国": "Mali Empire",
    "元朝中国": "Yuan dynasty",
    "琉球王国": "Ryukyu Kingdom",
    "ハワイ王国": "Kingdom of Hawaii",
    "大韓帝国": "Korean Empire",
    "満州国": "Manchukuo",
    "南ベトナム": "South Vietnam",
    "チェコスロバキア（共産期）": "Czechoslovak Socialist Republic",
    "ポーランド（共産期）": "Polish People's Republic",
    "ルーマニア（共産期）": "Socialist Republic of Romania",
    "オーストリア＝ハンガリー帝国": "Austria-Hungary",
    "ビルマ（コンバウン朝）": "Konbaung dynasty",
    "ジェノヴァ共和国": "Republic of Genoa",
    "スパルタ": "Sparta",
    "ハンザ同盟": "Hanseatic League",
    "英国帝国特恵制度": "Imperial Preference",
    "漢朝（前漢〜後漢）": "Han dynasty",
    "ウマイヤ朝": "Umayyad Caliphate",
    "明治〜大正日本": "Empire of Japan",
}

PRIMARY_DOMAINS = {
    "sourcebooks.fordham.edu",
    "www.perseus.tufts.edu",
    "en.wikisource.org",
    "zh.wikisource.org",
    "avalon.law.yale.edu",
    "history.state.gov",
    "ctext.org",
    "depts.washington.edu",
    "sacred-texts.com",
    "oll.libertyfund.org",
    "penelope.uchicago.edu",
    "legacy.fordham.edu",
    "www.fordham.edu",
    "classics.mit.edu",
    "www.gutenberg.org",
    "afe.easia.columbia.edu",
    "www.teachingaboutasia.com",
    "users.wfu.edu",
    "mofa.go.jp",
    "worldjpn.net",
    "germanhistorydocs.ghi-dc.org",
    "napoleon-empire.org",
    "napoleon-series.org",
    "documents.law.yale.edu",
    "govinfo.gov",
    "www.jacar.archives.go.jp",
    "waks.aks.ac.kr",
}

BLACKLIST_DOMAINS = {
    "wikipedia.org",
    "wikidata.org",
    "britannica.com",
    "ancient.eu",
    "worldhistory.org",
    "history.com",
    "nationalgeographic.com",
    "pbs.org",
    "youtube.com",
    "quora.com",
    "reddit.com",
    "academia.edu",
    "researchgate.net",
    "jstor.org",
    "cambridge.org",
    "oxford.ac.uk",
    "oup.com",
    "tandfonline.com",
    "sciencedirect.com",
    "springer.com",
    "wiley.com",
    "degruyter.com",
    "brill.com",
    "iranicaonline.org",
    "metmuseum.org",
    "britishmuseum.org",
    "www.britannica.com",
    "meta.wikimedia.org",
    "www.ourworldindata.org",
    "www.gapminder.org",
    "data.worldbank.org",
    "unstats.un.org",
    "www.un.org",
    "doi.org",
    "www.doi.org",
    "hdl.handle.net",
    "www.jstor.org",
    "archive.org",
    "web.archive.org",
    "webcache.googleusercontent.com",
}

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

# Curated primary-source hints (entity -> (url, reference, verified quote or "")).
# When quote is empty, the script fetches the page and uses find_quote with the
# assigned closure type.  When quote is non-empty it must be a substring of the
# fetched page text.
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
        'On June 28, the Cominform adopted a "Resolution of the Information Bureau Concerning the Situation in the Communist Party of Yugoslavia"',
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
    "エチオピア帝国": (
        "https://sourcebooks.fordham.edu/source/1520-presterjohn.asp",
        "Francisco Alvares: The Prester John of the Indies, c. 1520",
        "",
    ),
}


def title_for(entity: str, clio_name: str) -> str:
    if entity in ENTITY_TITLE_OVERRIDE:
        return ENTITY_TITLE_OVERRIDE[entity]
    if pd.notna(clio_name) and clio_name:
        return str(clio_name)
    return entity


def is_primary_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    url_l = url.lower()
    for d in BLACKLIST_DOMAINS:
        if d in url_l:
            return False
    for d in PRIMARY_DOMAINS:
        if d in url_l:
            return True
    return False


def clean_text(html_text: str | bytes) -> str:
    if isinstance(html_text, bytes):
        try:
            html_text = html_text.decode("utf-8", errors="ignore")
        except Exception:
            html_text = html_text.decode("latin-1", errors="ignore")
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    body = soup.get_text(separator=" ")
    body = re.sub(r"\s+", " ", body)
    return body.strip()


def fetch_with_requests(url: str, timeout: int = 25) -> tuple[str, str, str] | None:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return None
    content_type = resp.headers.get("content-type", "").lower()
    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        return pdf_to_text(resp.content, url)
    text = clean_text(resp.text)
    return (resp.url, text, resp.url)


def pdf_to_text(content: bytes, url: str) -> tuple[str, str, str] | None:
    try:
        proc = subprocess.run(
            ["pdftotext", "-", "-"],
            input=content,
            capture_output=True,
            timeout=20,
        )
        if proc.returncode == 0 and proc.stdout:
            text = proc.stdout.decode("utf-8", errors="ignore")
            text = re.sub(r"\s+", " ", text).strip()
            return url, text, url
    except Exception:
        pass
    return None


def fetch_with_web_get_contents(url: str) -> tuple[str, str, str] | None:
    try:
        res = call_tool_sync("web_get_contents", {"urls": [url]})
    except Exception:
        return None
    if not isinstance(res, str) or res.startswith("No content"):
        return None
    title_match = re.match(r"## Page 1:\s*(.+)", res)
    page_title = title_match.group(1).strip() if title_match else "Primary source"
    url_match = re.search(r"\nURL:\s*(https?://\S+?)(?:\n|$)", res)
    resolved_url = url_match.group(1) if url_match else url
    body_match = re.search(r"\nURL:\s*https?://\S+\n(.+)", res, re.DOTALL)
    body = body_match.group(1) if body_match else res
    body = re.sub(r"\s+", " ", body).strip()
    return page_title, body, resolved_url


fetch_cache: dict[str, tuple[str, str, str] | None] = {}


def fetch_page(url: str) -> tuple[str, str, str] | None:
    if url in fetch_cache:
        return fetch_cache[url]
    result = fetch_with_requests(url)
    if result is None:
        result = fetch_with_web_get_contents(url)
    fetch_cache[url] = result
    return result


def entity_keywords(entity: str, title: str) -> list[str]:
    """Generate low-cased keywords to identify the polity in a source text."""
    words: list[str] = []
    for raw in [entity, title]:
        if not raw:
            continue
        # Remove parentheses / non-English annotations
        cleaned = re.sub(r"[\(\)（）]", " ", raw)
        for token in cleaned.split():
            token = token.strip().lower()
            if len(token) > 2 and token.isalpha():
                words.append(token)
    # Specific normalisations
    norm: dict[str, list[str]] = {
        "アケメネス朝ペルシア": ["persia", "persian", "achaemenid"],
        "アッバース朝（前期）": ["abbasid", "bagdad", "baghdad", "radhanite"],
        "アッバース朝（後期）": ["abbasid", "bagdad", "baghdad"],
        "ウマイヤ朝": ["umayyad", "damascus", "spain"],
        "ムガル帝国（前期）": ["mogul", "mughal", "moghul", "indostan"],
        "ムガル帝国（後期）": ["mogul", "mughal", "moghul"],
        "ビザンツ帝国（後期）": ["constantinople", "byzantine", "istambul"],
        "モンゴル帝国": ["mongol", "mongols", "caracarum"],
        "ローマ共和政〜帝政前期": ["rome", "roman", "erythraean"],
        "漢朝（前漢〜後漢）": ["han", "chinese", "sima"],
        "唐朝中国": ["tang", "chinese", "ts'in"],
        "元朝中国": ["yuan", "kinsay", "kublai", "mongol"],
        "ポルトガル帝国": ["portuguese", "portugal", "gama"],
        "スペイン帝国": ["spanish", "spain", "columbus"],
        "大英帝国": ["english", "british", "britain", "india", "spice"],
        "米国（モンロー主義期）": ["america", "united states", "monroe"],
        "米国（戦後〜冷戦期）": ["united states", "america", "nato"],
        "戦後日本（高度成長期）": ["japan", "japanese", "security treaty"],
    }
    extra = norm.get(entity, [])
    all_kw = list(dict.fromkeys(extra + words))
    return all_kw


def find_quote(
    body: str,
    closure: str,
    entity: str,
    title: str,
    min_len: int = 60,
    max_len: int = 400,
) -> str | None:
    """Find a relevant sentence from the page text for the given closure type.

    Scores sentences by the presence of closure-type keywords and entity-specific
    keywords.  The returned sentence is guaranteed to be a substring of `body`.
    """
    keywords = KEYWORDS.get(closure, [])
    if not keywords:
        return None
    ek = entity_keywords(entity, title)
    sentences = re.split(r"(?<=[.!?。！？])\s+", body)
    best: tuple[float, str] | None = None
    for s in sentences:
        s = s.strip()
        if len(s) < min_len or len(s) > max_len:
            continue
        lower = s.lower()
        # Drop boilerplate/navigation
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
        entity_score = sum(0.5 for k in ek if k in lower)
        # Bonus for multi-keyword sentences, slight penalty for very long ones
        score = kw_count * 10 + entity_score - abs(len(s) - 200) / 100.0
        if best is None or score > best[0]:
            best = (score, s)
    return best[1] if best else None


def extract_heading_ref(body: str, page_title: str) -> str:
    m = re.search(r"#\s*([A-Z][^\n]{20,200}?)(?:\n|$)", body)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?:Internet History Sourcebooks?|Avalon Project|Medieval Sourcebook|Modern Sourcebook)\s*[\:\-]?\s*([A-Z][^\n]{20,200}?)(?:\n|$)", body)
    if m:
        return m.group(1).strip()
    return page_title


def build_search_queries(entity: str, title: str, closure: str) -> list[str]:
    queries: list[str] = []
    site_groups = {
        "bloc": ["site:avalon.law.yale.edu", "site:en.wikisource.org", "site:worldjpn.net"],
        "patron_open": ["site:avalon.law.yale.edu", "site:history.state.gov", "site:documents.law.yale.edu"],
        "maritime_ban": ["site:sourcebooks.fordham.edu", "site:en.wikisource.org", "site:classics.mit.edu", "site:ctext.org"],
        "land_isolation": ["site:sourcebooks.fordham.edu", "site:en.wikisource.org", "site:sacred-texts.com", "site:www.gutenberg.org"],
        "open": ["site:sourcebooks.fordham.edu", "site:en.wikisource.org", "site:penelope.uchicago.edu", "site:depts.washington.edu"],
        "tech_network_exclusion": ["site:sourcebooks.fordham.edu", "site:en.wikisource.org", "site:penelope.uchicago.edu", "site:classics.mit.edu"],
    }.get(closure, ["site:sourcebooks.fordham.edu", "site:en.wikisource.org"])

    kw_sample = KEYWORDS.get(closure, [])[:3]
    alt_titles = [title, entity]
    short = title.split()[0] if title else entity
    if short not in alt_titles:
        alt_titles.append(short)

    for site in site_groups:
        for t in alt_titles:
            if kw_sample:
                queries.append(f'{site} "{t}" {" ".join(kw_sample)}')
            else:
                queries.append(f'{site} "{t}"')
    # Generic primary-source search
    if kw_sample:
        queries.append(f'"{title}" {" ".join(kw_sample)} primary source')
    else:
        queries.append(f'"{title}" primary source')
    return queries


def parse_search(text: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    parts = re.split(r"\n##\s+\d+\.\s*", text)
    for part in parts[1:]:
        lines = part.splitlines()
        title = lines[0].strip() if lines else ""
        url = None
        for line in lines:
            m = re.match(r"URL:\s*(https?://\S+)", line)
            if m:
                url = m.group(1)
                break
        if url:
            results.append((title, url))
    return results


def is_wikipedia_source(row: pd.Series) -> bool:
    ref = str(row.get("rater_source_ref", "")).lower()
    url = str(row.get("rater_source_url", "")).lower()
    return "wikipedia" in ref or "wikipedia.org" in url


def try_hint(
    entity: str, closure: str, title: str
) -> tuple[str, str, str] | None:
    if entity not in PRIMARY_SOURCE_HINTS:
        return None
    url, ref, quote = PRIMARY_SOURCE_HINTS[entity]
    fetched = fetch_page(url)
    if not fetched:
        return None
    page_title, body, resolved_url = fetched
    chosen_ref = ref if ref else extract_heading_ref(body, page_title)
    if quote and quote in body:
        return resolved_url, chosen_ref, quote
    alt_quote = find_quote(body, closure, entity, title)
    if alt_quote:
        return resolved_url, chosen_ref, alt_quote
    return None


def discover_candidates(
    entity: str, closure: str, title: str
) -> list[str]:
    candidates: set[str] = set()
    # Wikipedia external links to primary domains
    try:
        params = {
            "action": "parse",
            "page": title,
            "prop": "externallinks",
            "redirects": "1",
            "format": "json",
        }
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        links = data.get("parse", {}).get("externallinks", [])
        for l in links:
            if l.startswith("http") and is_primary_url(l):
                candidates.add(l)
    except Exception:
        pass

    # Web search fallback
    queries = build_search_queries(entity, title, closure)
    for q in queries:
        try:
            search_res = call_tool_sync("web_search", {"query": q, "num_results": 5})
        except Exception:
            time.sleep(0.3)
            continue
        if not isinstance(search_res, str):
            continue
        for _, url in parse_search(search_res):
            if is_primary_url(url):
                candidates.add(url)
        if len(candidates) >= 10:
            break
        time.sleep(0.3)
    return list(candidates)


def upgrade_row(idx: int, row: pd.Series) -> dict:
    entity = row["entity"]
    closure = row["rater_closure_type"]
    clio_name = row.get("clio_name", "")
    title = title_for(entity, clio_name)

    result = {
        "index": idx,
        "entity": entity,
        "closure": closure,
        "title": title,
        "status": "no_action",
        "url": "",
        "ref": "",
        "quote": "",
        "notes": "",
    }

    if not isinstance(closure, str) or closure in ("", "uncertain"):
        result["status"] = "skipped_uncertain"
        return result

    # Curated hint first
    hint = try_hint(entity, closure, title)
    if hint:
        url, ref, quote = hint
        result.update({
            "status": "upgraded",
            "url": url,
            "ref": ref,
            "quote": quote,
            "notes": "Upgraded to curated public primary source; quote verified against fetched page.",
        })
        return result

    # Discovery
    candidates = discover_candidates(entity, closure, title)
    for url in candidates:
        fetched = fetch_page(url)
        if not fetched:
            continue
        page_title, body, resolved_url = fetched
        quote = find_quote(body, closure, entity, title)
        if quote:
            ref = extract_heading_ref(body, page_title)
            result.update({
                "status": "upgraded",
                "url": resolved_url,
                "ref": ref,
                "quote": quote,
                "notes": "Upgraded to public primary source discovered from Wikipedia references or web search; quote verified against fetched page.",
            })
            return result

    result["status"] = "failed_no_verified_primary"
    result["notes"] = "No verified public primary source found; original Wikipedia source retained."
    return result


def main() -> None:
    df = pd.read_csv(TEMPLATE, encoding="utf-8-sig")
    rows_to_check: list[tuple[int, pd.Series]] = []
    for idx, row in df.iterrows():
        if not isinstance(row.get("rater_closure_type"), str) or row["rater_closure_type"] in ("", "uncertain"):
            continue
        if str(row.get("rater_source_ref", "")).startswith("Primary source,"):
            continue
        if not is_wikipedia_source(row):
            # Only re-process if the URL itself already points to a primary domain
            url = str(row.get("rater_source_url", ""))
            if url and is_primary_url(url):
                continue
        rows_to_check.append((idx, row))

    log_rows: list[dict] = []
    upgraded = 0
    failed = 0
    skipped = 0

    for idx, row in rows_to_check:
        res = upgrade_row(idx, row)
        log_rows.append(res)
        if res["status"] == "upgraded":
            upgraded += 1
            df.at[idx, "rater_source_url"] = res["url"]
            df.at[idx, "rater_source_ref"] = f"Primary source, {res['ref']}"
            df.at[idx, "rater_source_quote"] = res["quote"]
            df.at[idx, "rater_notes"] = res["notes"]
            df.at[idx, "rater_confidence"] = "medium"
        elif res["status"].startswith("skipped"):
            skipped += 1
        else:
            failed += 1
            # Downgrade Wikipedia placeholder to low confidence and flag it
            df.at[idx, "rater_confidence"] = "low"
            df.at[idx, "rater_notes"] = "Primary source not yet located; Wikipedia citation retained as placeholder."

    df.to_csv(TEMPLATE, index=False, encoding="utf-8-sig")
    pd.DataFrame(log_rows).to_csv(LOG_PATH, index=False, encoding="utf-8-sig")

    print(f"Rows checked: {len(rows_to_check)}")
    print(f"Upgraded to primary: {upgraded}")
    print(f"Failed / retained Wikipedia: {failed}")
    print(f"Skipped: {skipped}")
    print(f"Log written to {LOG_PATH}")


if __name__ == "__main__":
    main()
