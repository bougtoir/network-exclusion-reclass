#!/usr/bin/env python3
"""Compute a Cliopatria phylogenetic/network embeddedness score.

Uses the `MemberOf` and `Components` fields in the Cliopatria geojson to build a
polity hierarchy.  For each polity matched by `scripts/build_cliopatria_mapping.py`
we compute:

- ancestry_depth: max number of parent levels to a top-level node
- descendant_count: number of descendant components (direct + indirect, capped)
- sibling_count: number of other polities sharing a parent in the same era
- network_size: number of unique Cliopatria nodes reachable within the polity's
  temporal window, capped to avoid tracing to n=1.

An `embeddedness_score` summarises how deeply the polity sits in the global
polity network, and `tree_exclusion_score` = 1 - embeddedness measures
structural isolation from that network.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
CLIO_GEOJSON = PROJECT_DIR / "data" / "raw" / "cliopatria.geojson"
MAPPING_PATH = PROJECT_DIR / "data" / "cliopatria_mapping.csv"
OUT_PATH = PROJECT_DIR / "data" / "cliopatria_tree_score.csv"


def parse_list(value: str | None) -> list[str]:
    if not value or not str(value).strip():
        return []
    items = re.split(r"[;]", str(value))
    out = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        item = re.sub(r"^\(|\)$", "", item)
        item = re.sub(r"^\(|\)$", "", item)
        if item:
            out.append(item)
    return out


def load_cliopatria_graph(path: Path) -> tuple[dict, dict[str, set[str]], dict[str, set[str]]]:
    with open(path, encoding="utf-8") as f:
        fc = json.load(f)
    raw: dict[str, dict] = {}
    for feat in fc["features"]:
        p = feat["properties"]
        name = str(p["Name"]).strip()
        if not name:
            continue
        if name not in raw:
            raw[name] = {
                "from": [],
                "to": [],
                "area": 0.0,
                "members": set(),
                "components": set(),
            }
        fy = p.get("FromYear")
        ty = p.get("ToYear")
        if fy is not None and ty is not None:
            raw[name]["from"].append(int(fy))
            raw[name]["to"].append(int(ty))
        raw[name]["area"] += float(p.get("Area", 0) or 0)
        raw[name]["members"].update(parse_list(p.get("MemberOf")))
        raw[name]["components"].update(parse_list(p.get("Components")))
    nodes: dict[str, dict] = {}
    parent_of: dict[str, set[str]] = defaultdict(set)
    child_of: dict[str, set[str]] = defaultdict(set)
    for name, data in raw.items():
        nodes[name] = {
            "from": min(data["from"]) if data["from"] else 0,
            "to": max(data["to"]) if data["to"] else 0,
            "area": data["area"],
            "members": list(data["members"]),
            "components": list(data["components"]),
        }
    # create edges
    for name, data in nodes.items():
        for parent in data["members"]:
            parent = str(parent).strip()
            if parent and parent in nodes:
                parent_of[name].add(parent)
                child_of[parent].add(name)
        for child in data["components"]:
            child = str(child).strip()
            if child and child in nodes:
                child_of[name].add(child)
                parent_of[child].add(name)
    return nodes, parent_of, child_of


def temporal_overlap(a: dict, b: dict) -> bool:
    return max(a["from"], b["from"]) <= min(a["to"], b["to"])


def ancestry_depth(node: str, parent_of: dict, nodes: dict) -> int:
    visited = set()
    stack = [(node, 0)]
    max_depth = 0
    while stack:
        cur, depth = stack.pop()
        if cur in visited or cur not in nodes:
            continue
        visited.add(cur)
        max_depth = max(max_depth, depth)
        for p in parent_of.get(cur, set()):
            if p not in visited and p in nodes:
                stack.append((p, depth + 1))
    return max_depth


def descendant_count(node: str, child_of: dict, nodes: dict, max_depth: int = 4) -> int:
    # Iterative DFS up to max_depth, counting unique descendants at each level.
    total = 0
    seen = set()
    stack = [(node, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth >= max_depth or cur in seen or cur not in nodes:
            continue
        seen.add(cur)
        if cur != node:
            total += 1
        for c in child_of.get(cur, set()):
            if c not in seen and c in nodes:
                stack.append((c, depth + 1))
    return total


def sibling_count(node: str, parent_of: dict, child_of: dict, nodes: dict) -> int:
    parents = [p for p in parent_of.get(node, set()) if p in nodes]
    if not parents:
        return 0
    sibs = set()
    for p in parents:
        for c in child_of.get(p, set()):
            if c != node and c in nodes:
                sibs.add(c)
    return len(sibs)


def contemporaries_count(node: str, nodes: dict, cap: int = 1000) -> int:
    """Count Cliopatria polities whose temporal span overlaps the target."""
    target = nodes[node]
    count = 0
    for name, data in nodes.items():
        if name == node:
            continue
        if temporal_overlap(target, data):
            count += 1
            if count >= cap:
                break
    return count


def main():
    nodes, parent_of, child_of = load_cliopatria_graph(CLIO_GEOJSON)
    mapping = pd.read_csv(MAPPING_PATH, encoding="utf-8-sig")
    # Keep the first match per entity (largest intersection area)
    mapping = mapping.sort_values("intersection_area_km2", ascending=False).drop_duplicates("entity", keep="first")

    rows = []
    for _, row in mapping.iterrows():
        entity = row["entity"]
        name = row["clio_name"]
        clio_area = float(row["clio_area_km2"]) if pd.notna(row.get("clio_area_km2")) else np.nan
        if pd.isna(name) or name not in nodes:
            rows.append(
                {
                    "entity": entity,
                    "clio_name": name if not pd.isna(name) else "",
                    "clio_area_km2": clio_area,
                    "ancestry_depth": np.nan,
                    "descendant_count": np.nan,
                    "sibling_count": np.nan,
                    "network_size": np.nan,
                    "contemporaries_count": np.nan,
                    "embeddedness_score": np.nan,
                    "tree_exclusion_score": np.nan,
                    "note": "no Cliopatria match",
                }
            )
            continue
        a_depth = ancestry_depth(name, parent_of, nodes)
        d_count = descendant_count(name, child_of, nodes, max_depth=3)
        s_count = sibling_count(name, parent_of, child_of, nodes)
        c_count = contemporaries_count(name, nodes, cap=5000)
        # raw embeddedness: high for large, long-lived, hierarchical, networked polities
        raw_embedded = float(
            np.log1p(float(nodes[name]["area"]) / 1e6)
            + np.log1p(min(c_count, 5000))
            + np.log1p(a_depth)
            + np.log1p(min(d_count, 500))
            + np.log1p(min(s_count, 100))
        )
        rows.append(
            {
                "entity": entity,
                "clio_name": name,
                "clio_area_km2": float(nodes[name]["area"]),
                "ancestry_depth": a_depth,
                "descendant_count": d_count,
                "sibling_count": s_count,
                "network_size": c_count,
                "contemporaries_count": c_count,
                "embeddedness_score": raw_embedded,
                "tree_exclusion_score": np.nan,
                "note": "",
            }
        )

    df = pd.DataFrame(rows)
    valid = df["embeddedness_score"].notna()
    if valid.sum() > 0:
        emin = df.loc[valid, "embeddedness_score"].min()
        emax = df.loc[valid, "embeddedness_score"].max()
        rng = emax - emin if emax > emin else 1.0
        df.loc[valid, "embeddedness_score"] = (df.loc[valid, "embeddedness_score"] - emin) / rng
        df.loc[valid, "tree_exclusion_score"] = 1 - df.loc[valid, "embeddedness_score"]
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Wrote {OUT_PATH} for {valid.sum()} matched polities")
    print(df[valid][["entity", "clio_name", "ancestry_depth", "descendant_count", "network_size", "tree_exclusion_score"]].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
