#!/usr/bin/env python3
"""Baseline Firth-penalized logistic regression on the 77-case analysis sample.

Predicts polity collapse (overtaken or disrupted = 1, survived = 0) from the
reconstructed continuous variables. Firth's bias reduction is used because some
sub-groups of the small cross-sectional sample are separated or quasi-separated.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from firthmodels import FirthLogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score

PROJECT_DIR = Path(__file__).resolve().parent.parent
FEATURES = [
    "geo_barrier",
    "external_threat",
    "relative_pop",
    "regime_duration_yrs",
    "has_external_patron",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=PROJECT_DIR / "data" / "analysis_sample.csv")
    parser.add_argument("--output", default=PROJECT_DIR / "data" / "baseline_logistic_results.csv")
    args = parser.parse_args()

    df = pd.read_csv(args.input, encoding="utf-8-sig")
    df["collapsed"] = df["outcome"].isin(["overtaken", "disrupted"]).astype(int)

    X = df[FEATURES].astype(float)
    y = df["collapsed"]

    if X.shape[0] == 0:
        raise ValueError("No valid rows for regression")

    model = FirthLogisticRegression(max_iter=200)
    model.fit(X.values, y.values)
    pred = model.predict_proba(X.values)[:, 1]
    pred_label = (pred >= 0.5).astype(int)

    n_features = len(FEATURES)
    coef = model.coef_
    se = model.bse_[:n_features]
    pvals = model.pvalues_[:n_features]
    ors = np.exp(coef)
    ci_low = np.exp(coef - 1.96 * se)
    ci_high = np.exp(coef + 1.96 * se)

    rows = []
    for f, c, o, l, h, p in zip(FEATURES, coef, ors, ci_low, ci_high, pvals):
        rows.append(
            {
                "feature": f,
                "coef": round(float(c), 3),
                "OR": round(float(o), 3),
                "CI_lower": round(float(l), 3),
                "CI_upper": round(float(h), 3),
                "p": round(float(p), 3),
            }
        )

    auc = roc_auc_score(y, pred)
    acc = accuracy_score(y, pred_label)
    rows.append({"feature": "n", "coef": len(y), "OR": np.nan, "CI_lower": np.nan, "CI_upper": np.nan, "p": np.nan})
    rows.append({"feature": "collapsed", "coef": int(y.sum()), "OR": np.nan, "CI_lower": np.nan, "CI_upper": np.nan, "p": np.nan})
    rows.append({"feature": "survived", "coef": int((y == 0).sum()), "OR": np.nan, "CI_lower": np.nan, "CI_upper": np.nan, "p": np.nan})
    rows.append({"feature": "AUC", "coef": round(auc, 3), "OR": np.nan, "CI_lower": np.nan, "CI_upper": np.nan, "p": np.nan})
    rows.append({"feature": "accuracy", "coef": round(acc, 3), "OR": np.nan, "CI_lower": np.nan, "CI_upper": np.nan, "p": np.nan})

    out = pd.DataFrame(rows)
    out.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"Wrote {args.output}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
