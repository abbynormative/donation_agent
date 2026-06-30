# Skill: Cluster Analysis — Donor Segmentation Rules

## Purpose
Defines the business rules, segment definitions, and interpretation guidance for the donor segmentation feature (`/cluster-analysis`). The Python implementation lives in `donor_clustering.py`; this file is the authoritative spec for what each segment means and what thresholds to apply.

## Segment Definitions

### Business-rule segments (hardcoded thresholds — override cluster assignments)

| Segment | Rule | Meaning |
|---|---|---|
| **Champions** (Likely Donors) | `frequency_90d >= 3` — 3 or more donations in the last 90 days | Actively and recently giving donors. Primary outreach target for major-gift asks, sustainer programs, and upgrade campaigns. |
| **Lapsed** | `recency_days >= 180` — no donation in the last 6 months | Donors who have disengaged. Candidate for win-back campaigns with a softer ask or re-engagement messaging. |

These two rules are mutually exclusive: a donor with 3+ gifts in 90 days has a recency < 90 days, which is always < 180 days, so they cannot be simultaneously Lapsed.

### Data-driven segments (k-means RFM clustering — applied to remaining donors)

| Segment | Profile (relative to cohort) |
|---|---|
| **Loyal** | High total giving and/or moderate recency; engaged but below the Champions threshold |
| **Occasional** | Lower frequency and/or longer gaps between gifts; periodic donors |

The number of data-driven segments adjusts with the `n_clusters` parameter. At `n_clusters=4` (default) you get all four labels above. At `n_clusters=3`, the Loyal and Occasional bands collapse into two. At `n_clusters=2`, only two bands appear between Champions and Lapsed.

## Configuration Constants

Defined at the top of `donor_clustering.py` — change them there to adjust thresholds without touching the rest of the code.

| Constant | Default | Meaning |
|---|---|---|
| `LIKELY_DONOR_MIN_GIFTS_90D` | `3` | Minimum donations in the last 90 days to qualify as a "likely donor" (Champions segment). |
| `LAPSED_RECENCY_DAYS` | `180` | Days since last donation at or above which a donor is classified as Lapsed. 180 ≈ 6 months. |
| `RFM_COLUMNS` | `["recency_days", "frequency", "monetary"]` | Features used for k-means clustering. |
| `PROFILE_FEATURE_COLUMNS` | `["recency_days", "frequency", "monetary", "avg_amount"]` | Features used for Random Forest feature importance. `frequency_90d` is intentionally excluded here to avoid a circular self-prediction of the Champions label. |

## Metrics

- **Recency (days)**: days since the donor's most recent donation, measured from the day after the latest donation in the dataset. Lower = more recent = stronger engagement signal.
- **Frequency**: total lifetime donation count.
- **Frequency (90d)**: count of donations in the 90 days immediately before the snapshot date. Primary signal for the Champions / likely-donor classification.
- **Monetary**: total lifetime giving amount.
- **Avg gift**: monetary ÷ frequency.

## Feature Importance

A small Random Forest (`n_estimators=200, max_depth=5`) is trained to classify "Champions (likely donor)" vs. everyone else. Its `feature_importances_` are reported as the ranked "most important factors" panel.

`frequency_90d` is deliberately excluded from these features so the result shows *why* donors are likely givers — not just the tautological "they donated recently." Typical high-importance factors: `monetary` (total giving), `recency_days`, `frequency`, `avg_amount`, and geographic signals like `state`.

## Interpretation Notes

- The **top donors preview** is filtered to donors who meet the Champions business rule (frequency_90d ≥ `LIKELY_DONOR_MIN_GIFTS_90D`), sorted by total lifetime monetary value.
- Segment percentages in the segments table are computed from *final labels* (after business-rule overrides), not from raw k-means cluster IDs.
- A donor assigned to the k-means "Champions" cluster who hasn't given in 6+ months will be relabeled "Lapsed" in the final output. The cluster profile stats are recomputed from final labels.
- The `likely_donor_count` field in the API response is the count of donors meeting the Champions business rule, distinct from the size of the k-means Champions cluster.

## Demo Data Caveat

The seeded demo database uses a 10 × 10 first × last name pool, so many "donors" share a name. The 90-day and 6-month thresholds may produce a small Champions list on the sparse demo data; they will behave as intended on real datasets with higher per-donor donation frequency.
