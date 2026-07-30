#!/usr/bin/env python3
"""Trace Wikipedia references for primary-source URLs and upgrade classification.

This script scans the references of the remaining Wikipedia-sourced cases in the
classification template, extracts external links and citation templates, and tries
to upgrade each case to a public primary source.  It verifies the chosen quote is a
substring of the fetched page.  No fabricated quotes are written.
"""
from __future__ import annotations

import re
import sys
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from upgrade_to_primary_sources import (
    PRIMARY_DOMAINS,
    BLACKLIST_DOMAINS,
    KEYWORDS,
    entity_keywords,
    find_quote,
    is_primary_url,
    fetch_page,
    extract_heading_ref,
    clean_text,
    TEMPLATE as UP_TEMPLATE,
    LOG_PATH as UP_LOG_PATH,
    USER_AGENT,
    is_wikipedia_source,
)

TEMPLATE = REPO / "data" / "classification_template_draft.csv"
LOG_PATH = REPO / "data" / "wikipedia_trace_log.csv"


def wikitext(page: str) -> str:
    r = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "parse", "page": page, "prop": "wikitext", "format": "json"},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("parse", {}).get("wikitext", {}).get("*", "")


def split_top_level_pipes(s: str) -> list[str]:
    brace = 0
    start_i = 0
    pieces: list[str] = []
    for i, ch in enumerate(s):
        if ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
        elif ch == "|" and brace == 0:
            pieces.append(s[start_i:i])
            start_i = i + 1
    pieces.append(s[start_i:])
    return pieces


def extract_cite_templates(text: str) -> list[dict[str, str]]:
    """Return a list of parsed {{cite web|...}} / {{cite book|...}} templates."""
    results: list[dict[str, str]] = []
    # Simple brace-balanced extractor for cite templates
    for m in re.finditer(r"\{\{\s*(?:cite\s+(?:web|book|news|journal)|citation)\b", text, re.IGNORECASE):
        start = m.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    raw = text[start : i + 1]
                    break
        else:
            continue
        fields: dict[str, str] = {}
        # split on pipes, respecting nested braces
        parts = split_top_level_pipes(raw[2:-2])
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                fields[k.strip().lower()] = v.strip()
        results.append(fields)
    return results


def candidates_from_wikitext(text: str) -> list[tuple[str, str]]:
    """Yield (url, title_or_ref) candidates from wikitext."""
    seen: set[str] = set()
    # raw external links
    for m in re.finditer(r"https?://\S+", text):
        url = m.group(0).rstrip("|}")
        if url not in seen:
            seen.add(url)
            yield url, ""
    # cite templates
    for fields in extract_cite_templates(text):
        url = fields.get("url", "")
        title = fields.get("title", "")
        work = fields.get("work", "")
        if url:
            yield url, title or work
        else:
            # Build a searchable title string
            label = title or work or ""
            if label:
                yield "", label


def extract_references(page: str) -> list[tuple[str, str]]:
    try:
        wt = wikitext(page)
    except Exception:
        return []
    return list(candidates_from_wikitext(wt))


def primary_candidate_urls(candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url, title in candidates:
        if url and url not in seen:
            if is_primary_url(url):
                seen.add(url)
                out.append((url, title))
    return out


def title_to_primary_url(title: str, entity: str, closure: str, title_override: str) -> tuple[str, str] | None:
    """Try a few targeted web searches for public-domain primary sources."""
    # clean title of wikimarkup
    title = re.sub(r"\[|\]|\{|\}|\|", "", title)
    if len(title) < 5:
        return None
    sites = {
        "bloc": ["avalon.law.yale.edu", "history.state.gov", "worldjpn.net"],
        "patron_open": ["avalon.law.yale.edu", "history.state.gov", "mofa.go.jp"],
        "maritime_ban": ["sourcebooks.fordham.edu", "ctext.org", "classics.mit.edu"],
        "land_isolation": ["sourcebooks.fordham.edu", "gutenberg.org", "sacred-texts.com"],
        "open": ["sourcebooks.fordham.edu", "gutenberg.org", "depts.washington.edu", "penelope.uchicago.edu"],
        "tech_network_exclusion": ["sourcebooks.fordham.edu", "gutenberg.org", "classics.mit.edu", "perseus.tufts.edu"],
    }.get(closure, ["sourcebooks.fordham.edu", "gutenberg.org", "en.wikisource.org"])

    for site in sites:
        q = f'site:{site} "{title}"'
        try:
            from devin_tools import call_tool_sync
            res = call_tool_sync("web_search", {"query": q, "num_results": 3})
        except Exception:
            continue
        if not isinstance(res, str):
            continue
        for m in re.finditer(r"URL:\s*(https?://\S+)", res):
            url = m.group(1)
            if is_primary_url(url):
                return url, title
        time.sleep(0.2)
    return None


def trace_row(idx: int, row: pd.Series, title: str, closure: str) -> dict:
    entity = row["entity"]
    result = {
        "index": idx, "entity": entity, "closure": closure,
        "status": "no_action", "url": "", "ref": "", "quote": "",
        "notes": "",
    }

    candidates = extract_references(title)
    primary = primary_candidate_urls(candidates)

    # First try direct primary URLs from the article references
    for url, ref_title in primary:
        fetched = fetch_page(url)
        if not fetched:
            continue
        page_title, body, resolved_url = fetched
        quote = find_quote(body, closure, entity, title)
        if quote:
            result.update({
                "status": "upgraded",
                "url": resolved_url,
                "ref": ref_title or extract_heading_ref(body, page_title),
                "quote": quote,
                "notes": "Upgraded from a Wikipedia reference link; quote verified.",
            })
            return result

    # Try a title-based search for public-domain versions
    for url, ref_title in primary:
        if ref_title:
            found = title_to_primary_url(ref_title, entity, closure, title)
            if found:
                purl, ptitle = found
                fetched = fetch_page(purl)
                if fetched:
                    page_title, body, resolved_url = fetched
                    quote = find_quote(body, closure, entity, title)
                    if quote:
                        result.update({
                            "status": "upgraded",
                            "url": resolved_url,
                            "ref": ptitle or extract_heading_ref(body, page_title),
                            "quote": quote,
                            "notes": "Upgraded from Wikipedia reference title matched to public primary source; quote verified.",
                        })
                        return result

    result["status"] = "failed_no_verified_primary"
    result["notes"] = "No verified public primary source found in Wikipedia references."
    return result


def main() -> None:
    from upgrade_to_primary_sources import title_for
    df = pd.read_csv(TEMPLATE, encoding="utf-8-sig")
    clio = pd.read_csv(REPO / "data" / "cliopatria_mapping.csv", encoding="utf-8-sig") if (REPO / "data" / "cliopatria_mapping.csv").exists() else None

    rows_to_check: list[tuple[int, pd.Series]] = []
    for idx, row in df.iterrows():
        if not isinstance(row.get("rater_closure_type"), str) or row["rater_closure_type"] in ("", "uncertain"):
            continue
        if str(row.get("rater_source_ref", "")).startswith("Primary source,"):
            continue
        if not is_wikipedia_source(row):
            continue
        rows_to_check.append((idx, row))

    log_rows: list[dict] = []
    upgraded = 0
    failed = 0

    for idx, row in rows_to_check:
        entity = row["entity"]
        clio_name = row.get("clio_name", "")
        title = title_for(entity, clio_name)
        closure = row["rater_closure_type"]
        res = trace_row(idx, row, title, closure)
        log_rows.append(res)
        if res["status"] == "upgraded":
            upgraded += 1
            df.at[idx, "rater_source_url"] = res["url"]
            df.at[idx, "rater_source_ref"] = f"Primary source, {res['ref']}"
            df.at[idx, "rater_source_quote"] = res["quote"]
            df.at[idx, "rater_notes"] = res["notes"]
            df.at[idx, "rater_confidence"] = "medium"
        else:
            failed += 1
            df.at[idx, "rater_confidence"] = "low"
            df.at[idx, "rater_notes"] = "Primary source not yet located; Wikipedia citation retained as placeholder."

    df.to_csv(TEMPLATE, index=False, encoding="utf-8-sig")
    pd.DataFrame(log_rows).to_csv(LOG_PATH, index=False, encoding="utf-8-sig")
    print(f"Rows checked: {len(rows_to_check)}")
    print(f"Upgraded: {upgraded}")
    print(f"Failed / retained Wikipedia: {failed}")
    print(f"Log written to {LOG_PATH}")


if __name__ == "__main__":
    main()
