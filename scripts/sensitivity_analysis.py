#!/usr/bin/env python3
"""Sensitivity and robustness analyses for the 77-case network-exclusion sample.

Outputs CSVs and PNGs used by generate_manuscript.py for the manuscript's
sensitivity section.  All numerical values are produced from public data and
reproducible from the checked-in scripts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from firthmodels import FirthLogisticRegression
from scipy.stats import fisher_exact, spearmanr
from sklearn.metrics import accuracy_score, roc_auc_score
from statsmodels.stats.outliers_influence import variance_inflation_factor

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
FIG_DIR = PROJECT_DIR / "manuscript" / "figures"
OUT_DIR = PROJECT_DIR / "data" / "sensitivity"

BASE_FEATURES = ["geo_barrier", "external_threat", "relative_pop", "regime_duration_yrs", "has_external_patron"]


def ensure_dirs():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def round_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = df[c].round(3)
    return df


def fit_logit(df: pd.DataFrame, y_col: str, features: list[str]) -> dict:
    """Fit a Firth-penalized logistic regression and return summary statistics."""
    X = df[features].astype(float)
    y = df[y_col].astype(int)
    df_idx = X.dropna().index
    X = X.loc[df_idx]
    y = y.loc[df_idx]
    if len(X) == 0 or y.nunique() < 2 or X.shape[1] == 0:
        return {"features": features, "converged": False, "error": "insufficient variation"}
    try:
        model = FirthLogisticRegression(max_iter=200)
        model.fit(X.values, y.values)
        pred = model.predict_proba(X.values)[:, 1]
        auc = roc_auc_score(y, pred)
        acc = accuracy_score(y, (pred >= 0.5).astype(int))
        n_features = len(features)
        coef = model.coef_
        se = model.bse_[:n_features]
        pvals = model.pvalues_[:n_features]
        ors = np.exp(coef)
        ci_low = np.exp(coef - 1.96 * se)
        ci_high = np.exp(coef + 1.96 * se)
        return {
            "features": features,
            "converged": True,
            "auc": round(auc, 3),
            "accuracy": round(acc, 3),
            "params": pd.Series(coef, index=features),
            "ci_lower": pd.Series(ci_low, index=features),
            "ci_upper": pd.Series(ci_high, index=features),
            "pvalues": pd.Series(pvals, index=features),
            "ors": pd.Series(ors, index=features),
            "n": len(y),
        }
    except Exception as e:
        return {"features": features, "converged": False, "error": str(e)}


def outcome_binarization_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    labels = {
        "collapsed_do": "disrupted=overtaken",
        "collapsed_ds": "disrupted=survived",
        "collapsed_oo": "only overtaken",
    }
    df["collapsed_do"] = df["outcome"].isin(["overtaken", "disrupted"]).astype(int)
    df["collapsed_ds"] = (df["outcome"] == "overtaken").astype(int)  # disrupted treated as survived
    df["collapsed_oo"] = (df["outcome"] == "overtaken").astype(int)
    for y_col, desc in labels.items():
        res = fit_logit(df, y_col, BASE_FEATURES)
        if not res["converged"]:
            continue
        for var in BASE_FEATURES:
            rows.append(
                {
                    "outcome_definition": desc,
                    "variable": var,
                    "OR": res["ors"].get(var),
                    "CI_lower": res["ci_lower"].get(var),
                    "CI_upper": res["ci_upper"].get(var),
                    "p": res["pvalues"].get(var),
                    "AUC": res["auc"],
                    "accuracy": res["accuracy"],
                    "n": y_col,
                }
            )
    return pd.DataFrame(rows)


def alternative_specifications(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # geo_barrier alternatives
    geo_alts = ["geo_barrier", "weighted_barrier", "geometric_barrier", "harmonic_barrier"]
    rows_geo = []
    for var in geo_alts:
        features = [var] + [f for f in BASE_FEATURES if f != "geo_barrier"]
        res = fit_logit(df, "collapsed_do", features)
        if not res["converged"]:
            continue
        for v in features:
            rows_geo.append(
                {
                    "geo_barrier_spec": var,
                    "variable": v,
                    "OR": res["ors"].get(v),
                    "CI_lower": res["ci_lower"].get(v),
                    "CI_upper": res["ci_upper"].get(v),
                    "p": res["pvalues"].get(v),
                    "AUC": res["auc"],
                    "accuracy": res["accuracy"],
                }
            )

    # external_threat alternatives
    ext_alts = {
        "external_threat": "external_threat",
        "capital_isolation": "capital_isolation",
        "major_empire_count": "n_major_empires_1000km",
        "capital_proximity_threat": "capital_proximity_threat",
    }
    rows_ext = []
    for label, var in ext_alts.items():
        if var not in df.columns:
            continue
        features = ["geo_barrier", var, "relative_pop", "regime_duration_yrs", "has_external_patron"]
        res = fit_logit(df, "collapsed_do", features)
        if not res["converged"]:
            continue
        for v in features:
            rows_ext.append(
                {
                    "external_threat_spec": label,
                    "variable": v,
                    "OR": res["ors"].get(v),
                    "CI_lower": res["ci_lower"].get(v),
                    "CI_upper": res["ci_upper"].get(v),
                    "p": res["pvalues"].get(v),
                    "AUC": res["auc"],
                    "accuracy": res["accuracy"],
                }
            )
    return pd.DataFrame(rows_geo), pd.DataFrame(rows_ext)


def exclusion_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    """Fit base model on excluded sub-samples."""
    conditions = {
        "exclude_multi_iso (iso_count>1)": df["iso_count"] <= 1,
        "exclude_top25_relative_pop": df["relative_pop"] <= df["relative_pop"].quantile(0.75),
        "exclude_pre_1500 (ancient+medieval)": df["era"].isin(["modern", "early_modern", "20c"]),
        "exclude_post_1500": df["era"].isin(["ancient", "medieval"]),
    }
    rows = []
    for name, mask in conditions.items():
        sub = df[mask].copy()
        if len(sub) < 20:
            continue
        res = fit_logit(sub, "collapsed_do", BASE_FEATURES)
        if not res["converged"]:
            continue
        for var in BASE_FEATURES:
            rows.append(
                {
                    "sample": name,
                    "n": len(sub),
                    "variable": var,
                    "OR": res["ors"].get(var),
                    "CI_lower": res["ci_lower"].get(var),
                    "CI_upper": res["ci_upper"].get(var),
                    "p": res["pvalues"].get(var),
                    "AUC": res["auc"],
                    "accuracy": res["accuracy"],
                }
            )
    return pd.DataFrame(rows)


def era_subgroup_analysis(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for era in df["era"].unique():
        if pd.isna(era):
            continue
        sub = df[df["era"] == era]
        if len(sub) < 10:
            continue
        res = fit_logit(sub, "collapsed_do", BASE_FEATURES)
        if not res["converged"]:
            continue
        for var in BASE_FEATURES:
            rows.append(
                {
                    "era": era,
                    "n": len(sub),
                    "variable": var,
                    "OR": res["ors"].get(var),
                    "CI_lower": res["ci_lower"].get(var),
                    "CI_upper": res["ci_upper"].get(var),
                    "p": res["pvalues"].get(var),
                    "AUC": res["auc"],
                    "accuracy": res["accuracy"],
                }
            )
    return pd.DataFrame(rows)


def leave_one_out(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for idx in df.index:
        sub = df.drop(idx)
        ent = df.loc[idx, "entity"]
        res = fit_logit(sub, "collapsed_do", BASE_FEATURES)
        if not res["converged"]:
            continue
        for var in BASE_FEATURES:
            rows.append({"excluded_entity": ent, "variable": var, "OR": res["ors"].get(var), "AUC": res["auc"]})
    return pd.DataFrame(rows)


def bootstrap_coefficients(df: pd.DataFrame, n_boot: int = 2000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for b in range(n_boot):
        boot = df.sample(n=len(df), replace=True, random_state=rng)
        res = fit_logit(boot, "collapsed_do", BASE_FEATURES)
        if not res["converged"]:
            continue
        for var in BASE_FEATURES:
            rows.append({"boot": b, "variable": var, "OR": res["ors"].get(var), "AUC": res["auc"]})
    return pd.DataFrame(rows)


def bootstrap_summary(boot_df: pd.DataFrame) -> pd.DataFrame:
    """Bootstrap percentile CI and two-sided p-value (H0: OR=1) for each variable."""
    rows = []
    for var in boot_df["variable"].unique():
        vals = boot_df[boot_df["variable"] == var]["OR"].dropna()
        if len(vals) == 0:
            continue
        vals = vals[(vals > np.percentile(vals, 0.5)) & (vals < np.percentile(vals, 99.5))]
        p_lower = (vals <= 1).mean()
        p_upper = (vals >= 1).mean()
        p_value = min(2 * min(p_lower, p_upper), 1.0)
        rows.append(
            {
                "variable": var,
                "n_boot": len(vals),
                "median_or": float(vals.median()),
                "ci_lower": float(np.percentile(vals, 2.5)),
                "ci_upper": float(np.percentile(vals, 97.5)),
                "p_bootstrap": p_value,
                "prop_or_lt1": float(p_lower),
            }
        )
    return round_cols(pd.DataFrame(rows), ["median_or", "ci_lower", "ci_upper", "p_bootstrap", "prop_or_lt1"])


def fisher_exact_by_closure(df: pd.DataFrame) -> pd.DataFrame:
    """Exact 2x2 tests comparing each closure type to the 'open' reference."""
    df = df[df["rater_closure_type"].notna() & (df["rater_closure_type"] != "")].copy()
    df = df[df["rater_closure_type"] != "uncertain"].copy()
    df["collapsed"] = df["outcome"].isin(["overtaken", "disrupted"]).astype(int)
    open_mask = df["rater_closure_type"] == "open"
    if open_mask.sum() == 0:
        return pd.DataFrame()
    open_coll = df.loc[open_mask, "collapsed"].sum()
    open_n = open_mask.sum()
    open_surv = open_n - open_coll
    rows = []
    for ctype in sorted(df["rater_closure_type"].unique()):
        if ctype == "open":
            continue
        mask = df["rater_closure_type"] == ctype
        n = mask.sum()
        coll = df.loc[mask, "collapsed"].sum()
        surv = n - coll
        table = np.array([[coll, surv], [open_coll, open_surv]])
        or_value, p_value = fisher_exact(table, alternative="two-sided")
        rows.append(
            {
                "closure_type": ctype,
                "n": int(n),
                "collapsed": int(coll),
                "survived": int(surv),
                "collapse_rate": round(coll / n, 3),
                "fisher_or": round(or_value, 3),
                "fisher_p": round(p_value, 3),
            }
        )
    return pd.DataFrame(rows)


def vif_table(df: pd.DataFrame) -> pd.DataFrame:
    X = df[BASE_FEATURES].dropna()
    vif = [variance_inflation_factor(X.values, i) for i in range(X.shape[1])]
    return pd.DataFrame({"variable": X.columns, "VIF": [round(v, 3) for v in vif]})


def make_sensitivity_figures(df: pd.DataFrame, boot_df: pd.DataFrame, loo_df: pd.DataFrame, out_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}

    # Figure: bootstrap distribution of key ORs
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, var in zip(axes, ["geo_barrier", "relative_pop"]):
        vals = boot_df[boot_df["variable"] == var]["OR"].dropna()
        vals = vals[(vals > 0) & (vals < np.percentile(vals, 99))]  # trim extreme tails
        ax.hist(vals, bins=40, color="gray", edgecolor="black")
        ax.axvline(x=1, color="red", linestyle="--")
        ax.axvline(x=vals.median(), color="blue", linestyle="-")
        ax.set_title(f"Bootstrap OR distribution: {var}")
        ax.set_xlabel("Odds ratio")
        ax.set_ylabel("Frequency")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.tight_layout()
    p1 = out_dir / "sens_bootstrap_or.png"
    fig.savefig(p1, dpi=300)
    plt.close(fig)
    paths["bootstrap_or"] = p1

    # Figure: leave-one-out coefficient stability
    if not loo_df.empty:
        fig, ax = plt.subplots(figsize=(8, 5))
        summary = loo_df.groupby("variable")["OR"].agg(["min", "median", "max", "std"]).reset_index()
        y_pos = np.arange(len(summary))
        ax.errorbar(summary["median"], y_pos, xerr=[summary["median"] - summary["min"], summary["max"] - summary["median"]], fmt="o", color="black", capsize=4)
        ax.axvline(x=1, color="red", linestyle="--")
        ax.set_yticks(y_pos)
        ax.set_yticklabels(summary["variable"])
        ax.set_xlabel("Odds ratio (min-median-max across leave-one-out fits)")
        ax.set_title("Leave-one-out coefficient stability")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        p2 = out_dir / "sens_loo_stability.png"
        fig.savefig(p2, dpi=300)
        plt.close(fig)
        paths["loo_stability"] = p2

    # Figure: ROC curves for outcome binarizations
    from sklearn.metrics import roc_curve

    fig, ax = plt.subplots(figsize=(6, 5))
    for y_col, label, color in [
        ("collapsed_do", "disrupted=overtaken", "#4c72b0"),
        ("collapsed_ds", "disrupted=survived", "#dd8452"),
        ("collapsed_oo", "only overtaken", "#55a868"),
    ]:
        X = df[BASE_FEATURES].astype(float).dropna()
        y = df.loc[X.index, y_col].astype(int)
        if y.nunique() < 2 or len(X) == 0:
            continue
        model = FirthLogisticRegression(max_iter=200)
        model.fit(X.values, y.values)
        pred = model.predict_proba(X.values)[:, 1]
        fpr, tpr, _ = roc_curve(y, pred)
        auc = roc_auc_score(y, pred)
        ax.plot(fpr, tpr, label=f"{label} (AUC={auc:.3f})", color=color)
    ax.plot([0, 1], [0, 1], "k--")
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("ROC curves by outcome binarization")
    ax.legend(loc="lower right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    p3 = out_dir / "sens_roc_binarization.png"
    fig.savefig(p3, dpi=300)
    plt.close(fig)
    paths["roc_binarization"] = p3

    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=DATA_DIR / "analysis_sample.csv")
    args = parser.parse_args()

    ensure_dirs()
    df = pd.read_csv(args.input, encoding="utf-8-sig")
    # rater_closure_type is not always in analysis_sample; merge from classification template
    if "rater_closure_type" not in df.columns or df["rater_closure_type"].isna().all():
        if "rater_closure_type" in df.columns:
            df = df.drop(columns=["rater_closure_type"])
        draft = pd.read_csv(DATA_DIR / "classification_template_draft.csv", encoding="utf-8-sig")[["entity", "rater_closure_type"]]
        df = df.merge(draft, on="entity", how="left")
    df["collapsed_do"] = df["outcome"].isin(["overtaken", "disrupted"]).astype(int)

    # 1. outcome binarization
    out1 = outcome_binarization_sensitivity(df)
    out1 = round_cols(out1, ["OR", "CI_lower", "CI_upper", "p", "AUC", "accuracy"])
    out1.to_csv(OUT_DIR / "outcome_binarization.csv", index=False, encoding="utf-8-sig")

    # 2. alternative variable specs
    out2a, out2b = alternative_specifications(df)
    out2a = round_cols(out2a, ["OR", "CI_lower", "CI_upper", "p", "AUC", "accuracy"])
    out2b = round_cols(out2b, ["OR", "CI_lower", "CI_upper", "p", "AUC", "accuracy"])
    out2a.to_csv(OUT_DIR / "geo_barrier_specs.csv", index=False, encoding="utf-8-sig")
    out2b.to_csv(OUT_DIR / "external_threat_specs.csv", index=False, encoding="utf-8-sig")

    # 3. exclusion sensitivity
    out3 = exclusion_sensitivity(df)
    out3 = round_cols(out3, ["OR", "CI_lower", "CI_upper", "p", "AUC", "accuracy"])
    out3.to_csv(OUT_DIR / "exclusion_sensitivity.csv", index=False, encoding="utf-8-sig")

    # 4. era subgroups
    out4 = era_subgroup_analysis(df)
    out4 = round_cols(out4, ["OR", "CI_lower", "CI_upper", "p", "AUC", "accuracy"])
    out4.to_csv(OUT_DIR / "era_subgroups.csv", index=False, encoding="utf-8-sig")

    # 5. LOO and bootstrap
    out5 = leave_one_out(df)
    out5 = round_cols(out5, ["OR", "AUC"])
    out5.to_csv(OUT_DIR / "leave_one_out.csv", index=False, encoding="utf-8-sig")
    out6 = bootstrap_coefficients(df)
    out6 = round_cols(out6, ["OR", "AUC"])
    out6.to_csv(OUT_DIR / "bootstrap_coefficients.csv", index=False, encoding="utf-8-sig")
    out8 = bootstrap_summary(out6)
    out8.to_csv(OUT_DIR / "bootstrap_summary.csv", index=False, encoding="utf-8-sig")

    # 6. Fisher exact tests by closure type
    out9 = fisher_exact_by_closure(df)
    out9.to_csv(OUT_DIR / "fisher_exact_by_closure.csv", index=False, encoding="utf-8-sig")

    # 7. VIF
    out7 = vif_table(df)
    out7.to_csv(OUT_DIR / "vif.csv", index=False, encoding="utf-8-sig")

    # figures
    fig_paths = make_sensitivity_figures(df, out6, out5, FIG_DIR)

    print("Sensitivity outputs written to", OUT_DIR)
    print("Figures:", fig_paths)


if __name__ == "__main__":
    main()
