# Network exclusion and state collapse — 77-case reclassification

This repository contains the reclassification and resubmission preparation for
the paper *Network Exclusion and State Collapse: From Maritime Isolation to
Technological Access Denial in the Long Run of History*.

The Public Choice decision (July 2026) treated the manuscript as a **de novo**
rejection. The editor and referees found the question interesting but concluded
that the classification framework was not transparent and the causal mechanism
was assumed rather than demonstrated. This repository therefore rebuilds the
analysis from public data, using a pre-specified, source-anchored classification
rubric and Firth-penalized logistic regression.

## Sample

- 96 legacy polity-periods.
- 17 ongoing polities and 2 non-territorial trade networks (Hanseatic League,
  British Imperial Preference) excluded.
- **77 non-ongoing polities** in the analysis sample (`data/analysis_sample.csv`).

## Reproducible workflow

Run the scripts in this order from the repository root (after installing
`requirements.txt` and downloading `data/raw/cliopatria.geojson` from Zenodo
record 13363121):

1. `python scripts/reconstruct_geo_barrier.py`
2. `python scripts/compute_capital_distances.py`
3. `python scripts/reconstruct_external_threat.py`
4. `python scripts/reconstruct_relative_pop.py`
5. `python scripts/reconstruct_regime_duration.py`
6. `python scripts/reconstruct_has_external_patron.py`
7. `python scripts/build_cliopatria_mapping.py`
8. `python scripts/cliopatria_tree_score.py`
9. `python scripts/draft_classification.py`
10. `python scripts/baseline_logistic.py`
11. `python scripts/classification_logistic.py`
12. `python scripts/sensitivity_analysis.py`
13. `python scripts/generate_manuscript.py`

All numbers, figures, tables, and the `manuscript/manuscript.docx` are regenerated
from public data and checked-in scripts. No estimates or statistics are
hard-coded.

## Key outputs

- `data/analysis_sample.csv` — 77-case analysis sample with reconstructed variables.
- `data/classification_template_draft.csv` — draft source-anchored closure-type
  classification (human review required).
- `data/cliopatria_tree_score.csv` — phylogenetic/network embeddedness score.
- `data/baseline_logistic_results.csv` — Firth logistic regression on continuous
  variables.
- `data/classification_logistic_results.csv` — Firth logistic regression on
  closure-type dummies.
- `data/closure_collapse_rates.csv` — collapse rates by closure type.
- `data/sensitivity/*.csv` — sensitivity and robustness outputs.
- `manuscript/manuscript.docx` — resubmission manuscript with inline figures and
  tables.
- `manuscript/figures.pptx` — editable English figure slides.
- `manuscript/table*.docx` — editable separate table files.
- `manuscript.zip` — combined archive of the manuscript package and result CSVs.

## Classification rubric

The source-anchored rubric is in `rubric.md`. It distinguishes:

- `maritime_ban` — deliberate restrictions on maritime trade.
- `policy_closure` — other intentional closure policies.
- `bloc` — externally imposed network exclusion through alliance/bloc structures.
- `land_isolation` — structural isolation shared by neighbours.
- `tech_network_exclusion` — neighbours are connected to the dominant network while
  the polity is not.
- `patron_open` — access depends on a powerful external patron.
- `open` — direct access to the era's dominant network.
- `uncertain` — insufficient evidence.

Each non-`uncertain` classification requires a source URL or printed reference and
a confidence rating.

## Notes and limitations

- `data/capitals.csv` flags 11 ancient capital coordinates as `needs_review=1`.
- `data/polity_geometry_mapping.csv` uses modern ISO/admin-1 polygons as proxies
  for historical territories; `needs_review=1` flags remain for multi-country
  empires.
- The closure-type classification in `data/classification_template_draft.csv` is
  a **draft** for human review; it should not be treated as a final validated
  coding.
