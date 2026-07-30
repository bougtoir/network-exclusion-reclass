#!/usr/bin/env python3
"""Small-sample robustness methods for the network-exclusion analysis.

Because the 77-case cross-section is small and some closure categories are sparse,
this script provides:
1. Permutation (randomization) p-values for the baseline and closure-type models.
2. Propensity-score weighting for closure-type treatment effects.
3. Discrete-time survival expansion using peak-year/duration.

All outputs are written to data/sensitivity/.
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from firthmodels import FirthLogisticRegression
from scipy.stats import fisher_exact
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from statsmodels.api import Logit, add_constant

warnings.filterwarnings("ignore")

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUT_DIR = DATA_DIR / "sensitivity"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_FEATURES = ["geo_barrier", "external_threat", "relative_pop", "regime_duration_yrs", "has_external_patron"]
CLOSURE_OPEN = "open"


def load_data():
    sample = pd.read_csv(DATA_DIR / "analysis_sample.csv", encoding="utf-8-sig")
    draft = pd.read_csv(DATA_DIR / "classification_template_draft.csv", encoding="utf-8-sig")
    if "rater_closure_type" not in sample.columns or sample["rater_closure_type"].isna().all():
        if "rater_closure_type" in sample.columns:
            sample = sample.drop(columns=["rater_closure_type"])
        sample = sample.merge(draft[["entity", "rater_closure_type"]], on="entity", how="left")
    sample["collapsed"] = sample["outcome"].isin(["overtaken", "disrupted"]).astype(int)
    return sample


def round_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = df[c].round(3)
    return df


def firth_or_p(X: pd.DataFrame, y: pd.Series) -> dict[str, float]:
    """Fit Firth logistic and return ORs and p-values for each feature."""
    model = FirthLogisticRegression(max_iter=200)
    model.fit(X.values, y.values)
    features = X.columns.tolist()
    coef = model.coef_
    se = model.bse_[: len(features)]
    pvals = model.pvalues_[: len(features)]
    return {
        "coef": pd.Series(coef, index=features),
        "or": pd.Series(np.exp(coef), index=features),
        "p": pd.Series(pvals, index=features),
        "se": pd.Series(se, index=features),
    }


def permutation_pvalues(df: pd.DataFrame, features: list[str], y_col: str = "collapsed", n_perm: int = 500, seed: int = 123) -> pd.DataFrame:
    """Exact-style permutation p-values by re-fitting after shuffling the outcome."""
    rng = np.random.default_rng(seed)
    X = df[features].astype(float).dropna()
    y = df.loc[X.index, y_col].astype(int)

    obs = firth_or_p(X, y)
    observed_or = obs["or"]
    observed_log = np.log(observed_or)

    perm_stats: dict[str, list[float]] = {f: [] for f in X.columns}
    for _ in range(n_perm):
        y_perm = pd.Series(rng.permutation(y.values), index=y.index)
        try:
            res = firth_or_p(X, y_perm)
        except Exception:
            continue
        for f in X.columns:
            if f in res["or"] and pd.notna(res["or"][f]) and res["or"][f] > 0:
                perm_stats[f].append(abs(np.log(res["or"][f])))

    rows = []
    for f in X.columns:
        vals = np.array(perm_stats[f])
        obs_abs = abs(observed_log[f])
        p = float((vals >= obs_abs).mean()) if len(vals) > 0 else np.nan
        rows.append(
            {
                "variable": f,
                "observed_or": float(observed_or[f]),
                "n_perm": len(vals),
                "perm_p": p,
            }
        )
    return round_cols(pd.DataFrame(rows), ["observed_or", "perm_p"])


def propensity_weighting(df: pd.DataFrame, closure_type: str, controls: list[str] | None = None) -> dict | None:
    """Estimate a propensity-score weighted effect of a closure type vs open."""
    controls = controls or BASE_FEATURES
    sub = df[df["rater_closure_type"].isin([closure_type, CLOSURE_OPEN])].copy()
    sub = sub.dropna(subset=controls + ["collapsed"])
    if len(sub) < 10 or sub["collapsed"].nunique() < 2:
        return None

    Xc = sub[controls].copy()
    # add era/region dummies if available
    for col in ["era", "region"]:
        if col in sub.columns:
            Xc = pd.concat([Xc, pd.get_dummies(sub[col], prefix=col, drop_first=True)], axis=1)
    Xc = Xc.astype(float)
    Xc_scaled = StandardScaler().fit_transform(Xc)
    treat = (sub["rater_closure_type"] == closure_type).astype(int)

    try:
        ps_model = LogisticRegression(max_iter=2000, C=1.0, solver="lbfgs")
        ps_model.fit(Xc_scaled, treat)
        pscore = ps_model.predict_proba(Xc_scaled)[:, 1]
    except Exception:
        return None

    # Truncate extreme propensities and compute IPW weights
    pscore = np.clip(pscore, 0.05, 0.95)
    weights = np.where(treat == 1, 1.0 / pscore, 1.0 / (1.0 - pscore))
    # Truncate at 95th percentile
    cap = np.percentile(weights, 95)
    weights = np.clip(weights, 0, cap)

    # Weighted collapse rates (ATE-like contrast)
    treat_mask = treat == 1
    weighted_treat = float(np.average(sub.loc[treat_mask, "collapsed"], weights=weights[treat_mask]))
    weighted_ctrl = float(np.average(sub.loc[~treat_mask, "collapsed"], weights=weights[~treat_mask]))

    # Weighted outcome model (closure vs open) with controls
    X = Xc.copy()
    X["treat"] = treat
    Xw = add_constant(X)
    y = sub["collapsed"].astype(int)
    try:
        wmodel = Logit(y, Xw)
        wres = wmodel.fit(disp=0, maxiter=200)
        treat_coef = wres.params["treat"]
        treat_se = wres.bse["treat"]
        treat_or = float(np.exp(treat_coef))
        ci_low = float(np.exp(treat_coef - 1.96 * treat_se))
        ci_high = float(np.exp(treat_coef + 1.96 * treat_se))
        p = float(wres.pvalues["treat"])
    except Exception:
        treat_or = ci_low = ci_high = p = np.nan

    return {
        "closure_type": closure_type,
        "n": int(len(sub)),
        "n_treat": int(treat.sum()),
        "n_open": int((~treat_mask).sum()),
        "weighted_rate_treat": weighted_treat,
        "weighted_rate_open": weighted_ctrl,
        "weighted_diff": weighted_treat - weighted_ctrl,
        "ate_or": treat_or,
        "ate_ci_lower": ci_low,
        "ate_ci_upper": ci_high,
        "ate_p": p,
    }


def propensity_all(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    closures = sorted(c for c in df["rater_closure_type"].dropna().unique() if c not in (CLOSURE_OPEN, "uncertain", ""))
    for c in closures:
        res = propensity_weighting(df, c)
        if res:
            rows.append(res)
    return round_cols(pd.DataFrame(rows), ["weighted_rate_treat", "weighted_rate_open", "weighted_diff", "ate_or", "ate_ci_lower", "ate_ci_upper", "ate_p"])


def period_to_years(period: str) -> tuple[int, int] | None:
    """Parse period strings like 'BC550-BC330' or 'AD1804-AD1815' to years."""
    if not isinstance(period, str):
        return None
    m = pd.Series([period]).str.extract(r"(?P<era1>BC|AD)?(?P<y1>\d+)\s*[-–]\s*(?P<era2>BC|AD)?(?P<y2>\d+)")
    if m.isna().any(axis=None):
        return None
    row = m.iloc[0]
    y1 = int(row["y1"])
    y2 = int(row["y2"])
    if (row["era1"] == "BC") or (pd.isna(row["era1"]) and "BC" in period):
        y1 = -y1
    if (row["era2"] == "BC") or (pd.isna(row["era2"]) and "BC" in period):
        y2 = -y2
    if y1 > y2:
        y1, y2 = y2, y1
    return y1, y2


def discrete_time_panel(df: pd.DataFrame, interval: int = 50) -> pd.DataFrame:
    """Expand each polity into discrete time intervals for survival-style analysis."""
    rows = []
    for _, row in df.iterrows():
        years = period_to_years(str(row["period"]))
        if not years:
            continue
        start, end = years
        outcome = str(row["outcome"])
        collapsed = outcome in ("overtaken", "disrupted")
        # Build intervals; event indicator is 1 in final interval if collapsed
        times = list(range(start, end, interval)) + [end]
        for i, t in enumerate(times[:-1]):
            next_t = times[i + 1]
            is_last = (i == len(times) - 2)
            event = 1 if (is_last and collapsed) else 0
            r = {
                "entity": row["entity"],
                "interval_start": t,
                "interval_end": next_t,
                "time": i,
                "event": event,
                "collapsed_final": int(collapsed),
                "outcome": outcome,
                "era": row.get("era"),
                "region": row.get("region"),
                "rater_closure_type": row.get("rater_closure_type"),
            }
            for f in BASE_FEATURES:
                r[f] = row.get(f)
            rows.append(r)
    return pd.DataFrame(rows)


def discrete_time_logit(panel: pd.DataFrame) -> pd.DataFrame:
    """Fit a discrete-time logistic model on the expanded panel."""
    # Exclude regime_duration_yrs because it is the total survival time; time dummies capture duration dependence.
    dt_features = [f for f in BASE_FEATURES if f != "regime_duration_yrs"]
    features = ["time"] + dt_features
    # add closure-type dummies, with open as reference
    if "rater_closure_type" in panel.columns:
        panel = panel[panel["rater_closure_type"].notna() & (panel["rater_closure_type"] != "")].copy()
        panel = panel[panel["rater_closure_type"] != "uncertain"].copy()
        dummies = pd.get_dummies(panel["rater_closure_type"], prefix="closure", drop_first=False)
        if "closure_open" in dummies.columns:
            dummies = dummies.drop(columns=["closure_open"])
        panel = pd.concat([panel.reset_index(drop=True), dummies.reset_index(drop=True)], axis=1)
        features += dummies.columns.tolist()
    if "era" in panel.columns:
        panel = pd.get_dummies(panel, columns=["era"], prefix="era", drop_first=True)
        features += [c for c in panel.columns if c.startswith("era_")]
    X = panel[features].astype(float).dropna()
    y = panel.loc[X.index, "event"].astype(int)
    X = add_constant(X)
    try:
        model = Logit(y, X).fit(disp=0, maxiter=200)
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]})
    summary = pd.DataFrame(
        {
            "variable": X.columns,
            "coef": model.params,
            "or": np.exp(model.params),
            "p": model.pvalues,
            "se": model.bse,
        }
    )
    return round_cols(summary, ["coef", "or", "p", "se"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-perm", type=int, default=500)
    args = parser.parse_args()

    df = load_data()
    df = df[df["rater_closure_type"].notna() & (df["rater_closure_type"] != "")].copy()
    df = df[df["rater_closure_type"] != "uncertain"].copy()

    # 1. Permutation p-values for baseline features
    perm_base = permutation_pvalues(df, BASE_FEATURES, n_perm=args.n_perm)
    perm_base.to_csv(OUT_DIR / "permutation_baseline.csv", index=False, encoding="utf-8-sig")

    # 2. Permutation p-values for closure-type model
    dummies = pd.get_dummies(df["rater_closure_type"], prefix="closure", drop_first=False)
    if "closure_open" in dummies.columns:
        dummies = dummies.drop(columns=["closure_open"])
    Xc = pd.concat([dummies, df[["relative_pop", "regime_duration_yrs"]].reset_index(drop=True)], axis=1)
    Xc = Xc.astype(float)
    yc = df["collapsed"].reset_index(drop=True).astype(int)
    # remove constants/empty columns
    Xc = Xc.loc[:, Xc.std() > 0]
    perm_cl = permutation_pvalues(pd.concat([Xc, yc.rename("collapsed")], axis=1), Xc.columns.tolist(), n_perm=min(args.n_perm, 300))
    perm_cl.to_csv(OUT_DIR / "permutation_closure.csv", index=False, encoding="utf-8-sig")

    # 3. Propensity-score weighted effects
    prop = propensity_all(df)
    prop.to_csv(OUT_DIR / "propensity_weighted.csv", index=False, encoding="utf-8-sig")

    # 4. Discrete-time survival / panel expansion
    panel = discrete_time_panel(df, interval=50)
    panel.to_csv(OUT_DIR / "discrete_time_panel.csv", index=False, encoding="utf-8-sig")
    dt_logit = discrete_time_logit(panel)
    dt_logit.to_csv(OUT_DIR / "discrete_time_logit.csv", index=False, encoding="utf-8-sig")

    print("Small-sample methods outputs written to", OUT_DIR)
    print("Permutation baseline:", perm_base.to_string(index=False))
    print("Permutation closure:", perm_cl.to_string(index=False))
    print("Propensity weighted:", prop.to_string(index=False))
    print("Discrete-time logit:", dt_logit.to_string(index=False))


if __name__ == "__main__":
    main()
