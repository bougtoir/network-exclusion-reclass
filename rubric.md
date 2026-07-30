# Classification rubric for network exclusion and state collapse

This rubric is used to reclassify the 96 polity-period cases in
`data/classification_template.csv`. Classifications must be applied **before**
looking at the outcome (`overtaken`/`disrupted`/`survived`) and **supported by a
specific source URL or canonical printed source and a quoted passage**.

## Coding rules

1. **Blind to outcome**: Code `rater_closure_type` and related fields using only
   information about the polity's geography, trade routes, and policies up to the
   start of the period. Do not use conquest/survival as a criterion.
2. **One source per case minimum**: Every non-empty classification must cite a
   source URL (`rater_source_url`) or standard printed reference
   (`rater_source_ref`) with a quoted passage in `rater_source_quote`.
3. **Confidence**: `high` = multiple independent sources agree and the case is
   unambiguous; `medium` = one good source or minor ambiguity; `low` = contested
   or sparse evidence.
4. **Dominant network of the era**: Use the period and region to identify the
   dominant technological platform. A polity is **excluded** only if it is
   structurally cut off from that platform relative to its neighbors, not merely
   peripheral.

## Closure-type categories

| Code | Definition | Typical sources |
|------|-----------|-----------------|
| `open` | Direct access to the dominant technological network of the era (e.g., Mediterranean routes, Silk Road nodes, Atlantic trade, industrial rail/steam networks). | Trade-route atlases, port records, overland corridor histories, numismatic/commodity evidence. |
| `maritime_ban` | Deliberate state policy restricts or prohibits maritime contact and the import of maritime technology. | Legal codes, diplomatic records, chronicles of foreign relations. |
| `land_isolation` | Geography (mountains, deserts, distance from corridors, no navigable rivers) structurally limits access, independent of policy. | Physical geography, historical maps, travel-time estimates, caravan/riverine network records. |
| `tech_network_exclusion` | The polity is not on any of the era's dominant technological platforms, even though neighbors are; this is a structural condition, not a policy choice. | Network reconstructions, technology-adoption timelines, archaeological or textual evidence of missing techniques. |
| `bloc` | External powers impose a blockade, sanctions, or forced economic bloc that cuts the polity off from the network. | Diplomatic histories, war records, blockade documents. |
| `policy_closure` | Other deliberate closure (not maritime) that restricts movement of people, goods, or information. | Legal and diplomatic records. |
| `patron_open` | The polity maintains access only through a powerful external patron/protector. | Treaty records, alliance histories. |
| `uncertain` | Insufficient evidence to classify; use only when no better code applies. | N/A |

## Decision tree

1. Is the exclusion mainly the result of **state policy**?
   - Yes, and it targets maritime contact → `maritime_ban`.
   - Yes, and it targets other contacts → `policy_closure`.
   - No → go to 2.
2. Is the exclusion mainly imposed by **external powers**?
   - Yes → `bloc`.
   - No → go to 3.
3. Is the polity structurally cut off by **geography** from the era's dominant
   technological network?
   - Yes, and neighbors in similar positions are also cut off → `land_isolation`.
   - Yes, but neighbors are connected → `tech_network_exclusion`.
   - No → `open` or `patron_open`.
4. Does the polity rely on an external patron for access?
   - Yes → `patron_open`.
   - No → `open`.

## Outcome definitions (do not use for classification)

- `overtaken`: The polity was conquered or absorbed by an external power during the period.
- `disrupted`: The polity fragmented or lost effective sovereignty without full conquest.
- `survived`: The polity maintained independence and continuity through the end of the period.

These outcomes are recorded for analysis only and must not influence Step 3 above.

## Sub-sample for sensitivity analysis

After all 96 cases are coded, identify 20–30 cases with `rater_confidence = high`
and at least two independent source citations (URL in `rater_source_url` plus a
printed reference in `rater_source_ref`, or two distinct references). That subset
becomes the primary sensitivity-analysis sample.
