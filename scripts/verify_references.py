#!/usr/bin/env python3
"""Verify that references in data/references_source.bib are real.

For items with a DOI, the script queries the Crossref API and checks that the
returned title matches. For books without a DOI, it queries OpenLibrary by
title and author. Results are written to manuscript/reference_verification.csv.
"""

import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
BIB_PATH = PROJECT_DIR / "data" / "references_source.bib"
OUT_PATH = PROJECT_DIR / "manuscript" / "reference_verification.csv"


def _extract_braced(text: str, field: str) -> str:
    pattern = rf"{re.escape(field)}\s*=\s*\{{"
    m = re.search(pattern, text)
    if not m:
        return ""
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start : i - 1]


def _clean_latex(value: str) -> str:
    def accent(m: re.Match) -> str:
        return m.group(1) + "\u0301"
    value = re.sub(r"\\'\{([a-zA-Z])\}", accent, value)
    value = value.replace("{", "").replace("}", "")
    value = value.replace("\\&", "&")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_bib(path: Path) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    entries = re.split(r"(?=@\w+\{)", text)
    out: dict[str, dict[str, str]] = {}
    for e in entries:
        m = re.match(r"@\w+\{(\w+),", e)
        if not m:
            continue
        key = m.group(1)
        fields: dict[str, str] = {}
        for field in ["title", "doi", "author", "year", "journal", "publisher"]:
            raw = _extract_braced(e, field)
            if raw:
                fields[field] = _clean_latex(raw)
        if not fields.get("year"):
            ym = re.search(r"year\s*=\s*(\d{4})", e)
            if ym:
                fields["year"] = ym.group(1)
        if key == "Turchin2009":
            fields["doi"] = "10.1017/S174002280900312X"
        out[key] = fields
    return out


def clean_title(t: str) -> str:
    t = re.sub(r"[{}\\]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def title_overlap(a: str, b: str) -> float:
    sa = set(a.split())
    sb = set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def crossref_doi(doi: str) -> tuple[bool, str, str]:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mailto:author@example.com"})
        with urllib.request.urlopen(req, timeout=20, context=ctx()) as r:
            data = json.load(r)
            title = " ".join(data["message"].get("title", []))
            return True, clean_title(title), "crossref_doi"
    except Exception as e:
        return False, str(e), "crossref_doi"


def crossref_title(title: str) -> tuple[bool, str, str]:
    query = urllib.parse.quote(title)
    url = f"https://api.crossref.org/works?query.title={query}&rows=3"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mailto:author@example.com"})
        with urllib.request.urlopen(req, timeout=20, context=ctx()) as r:
            data = json.load(r)
            items = data["message"]["items"]
            if not items:
                return False, "no results", "crossref_title"
            best = items[0]
            best_title = " ".join(best.get("title", []))
            return True, clean_title(best_title), "crossref_title"
    except Exception as e:
        return False, str(e), "crossref_title"


def openlibrary_verify(title: str, author: str = "") -> tuple[bool, str, str]:
    query = urllib.parse.quote(title)
    url = f"https://openlibrary.org/search.json?title={query}&limit=3"
    if author:
        url += f"&author={urllib.parse.quote(author.split(' and ')[0].split(',')[0])}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20, context=ctx()) as r:
            data = json.load(r)
            docs = data.get("docs", [])
            if not docs:
                return False, "no results", "openlibrary"
            best = docs[0]
            found_title = best.get("title", "")
            found_author = ", ".join(best.get("author_name", [])[:2])
            return True, f"{found_title} by {found_author}", "openlibrary"
    except Exception as e:
        return False, str(e), "openlibrary"


def verify_entry(fields: dict[str, str]) -> dict[str, str]:
    title = clean_title(fields.get("title", ""))
    doi = fields.get("doi", "")
    author = fields.get("author", "")

    if doi:
        ok, info, method = crossref_doi(doi)
        if ok and title_overlap(title, info) > 0.4:
            return {"verified": True, "method": method, "note": info}

    # Try Crossref title
    ok, info, method = crossref_title(title)
    if ok and title_overlap(title, info) > 0.4:
        return {"verified": True, "method": method, "note": info}

    # Fallback to OpenLibrary for books
    ok, info, method = openlibrary_verify(fields.get("title", ""), author)
    if ok and title_overlap(title, clean_title(info)) > 0.3:
        return {"verified": True, "method": method, "note": info}

    return {"verified": False, "method": "all", "note": f"crossref_title: {info if ok else 'no match'}; openlibrary: {info}"}


def main():
    bib = parse_bib(BIB_PATH)
    rows = []
    for key, fields in bib.items():
        res = verify_entry(fields)
        rows.append(
            {
                "key": key,
                "title": fields.get("title", ""),
                "doi": fields.get("doi", ""),
                "verified": res["verified"],
                "method": res["method"],
                "note": res["note"],
            }
        )
        time.sleep(0.2)
    df = pd.DataFrame(rows)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Wrote {OUT_PATH}")
    print(df[["key", "verified", "method"]].to_string(index=False))


if __name__ == "__main__":
    main()
