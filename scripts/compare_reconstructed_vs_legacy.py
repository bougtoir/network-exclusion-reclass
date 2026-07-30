#!/usr/bin/env python3
"""Compare reconstructed continuous variables with the legacy (data.py) scores.

Outputs a CSV with per-variable correlations and mean absolute differences, and
prints a short summary for the 77-case non-ongoing analysis sample.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_DIR = Path(__file__).resolve().parent.parent

VARIABLES = [
    ("geo_barrier", "geo_barrier"),
    ("external_threat", "external_threat"),
    ("relative_pop", "relative_pop"),
    ("regime_duration_yrs", "regime_duration_yrs"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--analysis-sample",
        default=PROJECT_DIR / "data" / "analysis_sample.csv",
    )
    parser.add_argument(
        "--template",
        default=PROJECT_DIR / "data" / "classification_template.csv",
    )
    parser.add_argument(
        "--output",
        default=PROJECT_DIR / "data" / "reconstruction_comparison.csv",
    )
    args = parser.parse_args()

    sample = pd.read_csv(args.analysis_sample, encoding="utf-8-sig")
    template = pd.read_csv(args.template, encoding="utf-8-sig")

    merged = sample.merge(
        template[["entity"] + [v[1] for v in VARIABLES]],
        on="entity",
        how="left",
        suffixes=("_new", "_legacy"),
    )

    rows = []
    for new_col, legacy_col in VARIABLES:
        pair = merged[[f"{new_col}_new", f"{new_col}_legacy"]].dropna()
        if len(pair) < 5:
            continue
        spearman = pair[f"{new_col}_new"].corr(pair[f"{new_col}_legacy"], method="spearman")
        pearson = pair[f"{new_col}_new"].corr(pair[f"{new_col}_legacy"], method="pearson")
        mae = np.mean(np.abs(pair[f"{new_col}_new"] - pair[f"{new_col}_legacy"]))
        rmse = np.sqrt(np.mean((pair[f"{new_col}_new"] - pair[f"{new_col}_legacy"]) ** 2))
        rows.append(
            {
                "variable": new_col,
                "n": len(pair),
                "spearman": round(spearman, 3) if pd.notna(spearman) else None,
                "pearson": round(pearson, 3) if pd.notna(pearson) else None,
                "mae": round(mae, 4),
                "rmse": round(rmse, 4),
            }
        )
        print(
            f"{new_col}: n={len(pair)}, Spearman={spearman:.3f}, "
            f"Pearson={pearson:.3f}, MAE={mae:.4f}, RMSE={rmse:.4f}"
        )

    out = pd.DataFrame(rows)
    out.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
