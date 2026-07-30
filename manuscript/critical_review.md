# Pre-submission critical review — network exclusion manuscript

## 1. Introduction promises vs. Results/Discussion collection

| Introduction claim | Where it is collected | Verdict |
|---|---|---|
| Network exclusion takes multiple forms (maritime bans, land isolation, technology-network exclusion, bloc membership, patron-dependent openness) | Table 3, Table 4, Table 8, Table 9, Table 10 report collapse rates and treatment effects by closure type | Collected |
| Small and/or geographically excluded polities are more likely to collapse | Table 2 baseline model (relative_pop OR ≈ 0.27, p = 0.088; geo_barrier directionally protective OR ≈ 0.05) | Partially collected; significance is borderline |
| Relative population and closure type capture complementary information | Controlled closure-type model AUC rises from 0.752 to 0.794 when relative_pop and duration are added | Collected |
| Modern technological access denial echoes historical network exclusion | Brief speculative paragraph in Discussion; no empirical test of modern cases | Mentioned as illustration only — acceptable if labelled as such |

## 2. Discussion calibration against results

- **Not overstated**: The Discussion repeatedly uses "associated with," "directionally protective," and "suggestive." It does not claim that closure type causes collapse.
- **Not understated**: The main pattern (small/relatively isolated polities and tech-network-excluded or bloc polities collapse more often) is reported clearly.
- **Potential imbalance**: The Abstract says "closure-type analysis shows that technology-network exclusion and bloc membership are associated with higher odds of collapse." This is accurate but readers may miss that the Firth ORs are not individually significant at α = 0.05. The body text already notes imprecision.
- **Discrete-time panel (Table 11)** is framed as exploratory: era and duration baseline hazard dominate, and closure_bloc reaches p = 0.018, but the model is sensitive to interval choice and repeated observations. The Discussion currently does this.

## 3. Remaining fatal / major-revision risks

1. **Wikipedia-sourced closure-type drafts remain in the classification file.**
   - All 77 analysis cases now carry a `rater_source_url`/`ref`/`quote`, but several are still derived from Wikipedia.
   - **Fix before submission**: Replace the most consequential cases (Mongol, Achaemenid, Umayyad, Roman, etc.) with specialized monographs or primary-source citations.

2. **Statistical evidence is suggestive, not conclusive.**
   - Firth logistic ORs for closure types are wide and not conventionally significant.
   - Permutation inference gives `tech_network_exclusion` p = 0.037 and Fisher exact gives `bloc` p = 0.030, which are the strongest small-sample signals.
   - Propensity-score weighted rates are descriptive (no adjusted OR because several treatment groups are perfectly predicted).
   - **Fix**: Keep cautious wording; do not write "closure type significantly increases collapse risk" without qualifying by method.

3. **Causal language must remain qualified.**
   - n = 77, observational, cross-sectional (with an exploratory panel expansion).
   - The manuscript already avoids "cause" and uses "associated with."

4. **Relative population is endogenous.**
   - `relative_pop` is the strongest baseline predictor (OR ≈ 0.27), but population is itself an outcome of economic/network success.
   - The Discussion notes this; keep the caveat.

## 4. High-priority improvements

5. **Empire proxy measurement error.**
   - `relative_pop` and `geo_barrier` are built from modern ISO/admin-1 polygons. Cliopatria refinement reduced `needs_review` to 0, but large empires remain coarse.
   - Sensitivity analysis excluding top 25% of `relative_pop` is reported (Table 6 / exclusion_sensitivity.csv).

6. **Outcome binarization.**
   - Treating "disrupted" as survived shifts results. This is reported in Table 6.

7. **Modern extrapolation.**
   - The Discussion's paragraph on semiconductors/AI is explicitly labelled illustrative and not tested.

## 5. Verification checklist

- [x] Manuscript no longer refers to "legacy," "original dataset," "rebuild," or "旧版" for the empirical analysis.
- [x] All reported numbers rounded to 3 decimal places in tables and text.
- [x] All figures and tables cited in the body in order of appearance (Figure 1-7, Table 1-11).
- [x] References numbered by first appearance (Vancouver style) and verified against Crossref/OpenLibrary (all True).
- [x] All numbers generated from `data/analysis_sample.csv`, public data, and scripts; no hard-coded statistics in the manuscript generator.
- [x] Reproducibility statement in Data Availability with script run order.
- [x] Cover letter states the submission is a de novo resubmission that addresses previous comments and was reconstructed with reproducibility as the central priority.
- [x] New small-sample methods added: Fisher exact (Table 8), permutation p-values (Table 9), propensity-score weighted rates (Table 10), discrete-time survival expansion (Table 11).

## 6. Recommendation

The manuscript is a **credible resubmission package** if the Wikipedia-sourced closure-type citations are replaced or confirmed with scholarly sources before final submission. The statistical evidence is now more robust to small-sample concerns, but it remains suggestive rather than definitive. Keep causal language qualified and report wide confidence intervals transparently.
