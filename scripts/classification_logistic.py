#!/usr/bin/env python3
"""Logistic regression of polity collapse on closure-type classification.

Tests the central theoretical claim: closure type (source-anchored rubric)
predicts state collapse.  Firth's bias-reduced logistic regression is used to
handle the small sample and quasi-complete separation in some closure categories.

- Outcome: collapsed = outcome in ('overtaken', 'disrupted')
- Exposure: rater_closure_type dummies (open = reference)
- Controls (optional): relative_pop, regime_duration_yrs
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from firthmodels import FirthLogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score

PROJECT_DIR = Path(__file__).resolve().parent.parent
SAMPLE_PATH = PROJECT_DIR / "data" / "analysis_sample.csv"
DRAFT_PATH = PROJECT_DIR / "data" / "classification_template_draft.csv"
OUT_PATH = PROJECT_DIR / "data" / "classification_logistic_results.csv"


def fit_model(df: pd.DataFrame, controls: list[str] | None = None) -> dict:
    df = df[df["rater_closure_type"].notna() & (df["rater_closure_type"] != "")].copy()
    df = df[df["rater_closure_type"] != "uncertain"].copy()

    dummies = pd.get_dummies(df["rater_closure_type"], prefix="closure", drop_first=False)
    if "closure_open" in dummies.columns:
        dummies = dummies.drop(columns=["closure_open"])

    X = dummies.copy().astype(float)
    if controls:
        for c in controls:
            if c in df.columns:
                X[c] = df[c].astype(float)
    y = df["outcome"].isin(["overtaken", "disrupted"]).astype(int)

    if y.nunique() < 2 or X.shape[1] == 0:
        return {"error": "insufficient variation"}

    model = FirthLogisticRegression(max_iter=100)
    model.fit(X.values, y.values)
    pred = model.predict_proba(X.values)[:, 1]
    auc = roc_auc_score(y, pred)
    acc = accuracy_score(y, (pred >= 0.5).astype(int))

    coef = model.coef_
    # bse_ and pvalues_ include the intercept at the last position
    n_features = len(X.columns)
    se = model.bse_[:n_features]
    pvals = model.pvalues_[:n_features]
    ors = np.exp(coef)
    ci_low = np.exp(coef - 1.96 * se)
    ci_high = np.exp(coef + 1.96 * se)

    result = pd.DataFrame({
        "feature": X.columns,
        "coef": coef,
        "OR": ors,
        "CI_lower": ci_low,
        "CI_upper": ci_high,
        "p": pvals,
    })
    # Round all reported numbers to 3 decimal places for consistency.
    numeric_cols = ["coef", "OR", "CI_lower", "CI_upper", "p", "AUC", "accuracy"]
    for col in numeric_cols:
        if col in result.columns:
            result[col] = result[col].round(3)
    result["n"] = len(df)
    result["collapsed"] = int(y.sum())
    result["survived"] = int(len(df) - y.sum())
    result["AUC"] = round(auc, 3)
    result["accuracy"] = round(acc, 3)
    return {"result": result, "n": len(df), "auc": round(auc, 3), "accuracy": round(acc, 3)}


def collapse_rates(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["rater_closure_type"].notna() & (df["rater_closure_type"] != "")].copy()
    df["collapsed"] = df["outcome"].isin(["overtaken", "disrupted"]).astype(int)
    rates = (
        df.groupby("rater_closure_type")["collapsed"]
        .agg(["count", "sum", "mean"])
        .rename(columns={"count": "n", "sum": "collapsed", "mean": "collapse_rate"})
        .reset_index()
    )
    rates["collapse_rate"] = rates["collapse_rate"].round(3)
    return rates


def main():
    sample = pd.read_csv(SAMPLE_PATH, encoding="utf-8-sig")
    sample = sample.drop(columns=[c for c in sample.columns if c.startswith("rater_")], errors="ignore")
    draft = pd.read_csv(DRAFT_PATH, encoding="utf-8-sig")[["entity", "rater_closure_type", "rater_confidence"]]
    df = sample.merge(draft, on="entity", how="left")

    rates = collapse_rates(df)
    rates.to_csv(PROJECT_DIR / "data" / "closure_collapse_rates.csv", index=False, encoding="utf-8-sig")

    models = {
        "closure_only": fit_model(df),
        "closure_with_controls": fit_model(df, controls=["relative_pop", "regime_duration_yrs"]),
    }

    rows = []
    for name, res in models.items():
        if "error" in res:
            continue
        r = res["result"].copy()
        r["model"] = name
        rows.append(r)
    combined = pd.concat(rows, ignore_index=True)
    combined.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Wrote {OUT_PATH}")
    print("Collapse rates by closure type:")
    print(rates.to_string(index=False))
    print("\nLogistic models:")
    print(combined.to_string(index=False))


if __name__ == "__main__":
    main()
