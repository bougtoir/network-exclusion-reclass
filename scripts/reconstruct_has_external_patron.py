#!/usr/bin/env python3
"""Reconstruct has_external_patron from a source-anchored manual coding table.

COW Alliance Data (v4.1) records mutual defense pacts, not hierarchical
patron-client relationships, so it cannot determine patronage on its own.
Instead, this script reads a curated CSV of public-source evidence and merges
it into all_features.csv.

Inputs:
- data/all_features.csv
- data/has_external_patron_sources.csv

Outputs:
- data/has_external_patron_reconstructed.csv
- data/all_features.csv (with has_external_patron, patron_entity, patron_source_url, patron_source_ref, patron_needs_review)
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Reconstruct has_external_patron from source table")
    parser.add_argument(
        "--input",
        default=str(PROJECT_DIR / "data" / "all_features.csv"),
        help="Input all_features CSV",
    )
    parser.add_argument(
        "--sources",
        default=str(PROJECT_DIR / "data" / "has_external_patron_sources.csv"),
        help="CSV with source-anchored has_external_patron coding",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_DIR / "data" / "has_external_patron_reconstructed.csv"),
        help="Output CSV",
    )
    parser.add_argument(
        "--all-features-out",
        default=str(PROJECT_DIR / "data" / "all_features.csv"),
        help="CSV to update",
    )
    args = parser.parse_args()

    features = pd.read_csv(args.input, encoding="utf-8-sig")
    sources = pd.read_csv(args.sources, encoding="utf-8-sig", dtype=str)

    # Ensure expected columns
    required = {"entity", "has_external_patron", "patron_entity", "source_url", "source_ref", "needs_review", "notes"}
    missing = required - set(sources.columns)
    if missing:
        raise ValueError(f"Missing columns in {args.sources}: {missing}")

    sources["has_external_patron"] = pd.to_numeric(sources["has_external_patron"], errors="coerce").fillna(0).astype(int)
    sources["needs_review"] = pd.to_numeric(sources["needs_review"], errors="coerce").fillna(0).astype(int)

    # Drop any old patron columns from features to avoid duplicates
    for col in [
        "has_external_patron",
        "patron_entity",
        "patron_source_url",
        "patron_source_ref",
        "patron_needs_review",
        "patron_notes",
    ]:
        if col in features.columns:
            features = features.drop(columns=[col])

    merged = sources.rename(
        columns={
            "source_url": "patron_source_url",
            "source_ref": "patron_source_ref",
            "needs_review": "patron_needs_review",
            "notes": "patron_notes",
        }
    )
    out = features.merge(merged, on="entity", how="left")
    out["has_external_patron"] = out["has_external_patron"].fillna(0).astype(int)
    out["patron_needs_review"] = out["patron_needs_review"].fillna(0).astype(int)

    # Write output
    out[[
        "entity",
        "has_external_patron",
        "patron_entity",
        "patron_source_url",
        "patron_source_ref",
        "patron_needs_review",
        "patron_notes",
    ]].to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Wrote {args.output}", file=sys.stderr)

    # Update all_features
    out.to_csv(args.all_features_out, index=False, encoding="utf-8-sig")
    print(f"Updated {args.all_features_out}", file=sys.stderr)

    # Summary
    positive = out["has_external_patron"].sum()
    flagged = out["patron_needs_review"].sum()
    print(f"Positive cases: {int(positive)}", file=sys.stderr)
    print(f"Flagged for review: {int(flagged)}", file=sys.stderr)


if __name__ == "__main__":
    main()
