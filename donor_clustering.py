"""Donor segmentation via RFM-style clustering.

Aggregates raw donation rows into one row per donor, clusters donors on
Recency / Frequency / Monetary value (classic RFM), labels the resulting
segments by engagement, and reports which underlying factors most distinguish
the top ("likely donor") segment from the rest, via a Random Forest's
feature importances.

CAVEAT: the `donations` table has no donor ID column, only `donor_name`. In
the seeded demo data, names are drawn from a small pool (10 first names x 10
last names), so several unrelated donations can collide into the same
"donor" bucket. That's fine for demonstrating the pipeline, but a real
deployment should group by a stable donor_id instead.
"""

import os
from typing import Any, Dict, List

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

RFM_COLUMNS = ["recency_days", "frequency", "monetary"]
PROFILE_FEATURE_COLUMNS = ["recency_days", "frequency", "monetary", "avg_amount"]
SEGMENT_LABELS_BY_RANK = ["Champions", "Loyal", "Occasional", "Lapsed"]

DONOR_NAME_CAVEAT = (
    "Donors are grouped by donor_name, the only identifier in this schema. "
    "In the seeded demo data, names are drawn from a small pool, so a "
    "'donor' bucket can represent more than one real person who happens to "
    "share a name. Swap in a real donor_id column for production use."
)


def build_donor_features(engine) -> pd.DataFrame:
    """Aggregate raw donation rows into one row per donor (by donor_name)."""
    df = pd.read_sql(
        "SELECT donor_name, amount, zip, state, donated_at FROM donations", engine
    )
    if df.empty:
        raise ValueError("No donation rows found to cluster.")
    df["donated_at"] = pd.to_datetime(df["donated_at"])

    # Snapshot date for recency: the day after the most recent donation in
    # the data. Using "now" would make recency drift upward forever against
    # a static seeded dataset; anchoring to the data's own timeline keeps the
    # segmentation meaningful regardless of when this is run.
    snapshot_date = df["donated_at"].max() + pd.Timedelta(days=1)

    def mode_or_first(s: pd.Series):
        m = s.mode()
        return m.iloc[0] if not m.empty else s.iloc[0]

    grouped = (
        df.groupby("donor_name")
        .agg(
            frequency=("amount", "count"),
            monetary=("amount", "sum"),
            avg_amount=("amount", "mean"),
            last_donated_at=("donated_at", "max"),
            first_donated_at=("donated_at", "min"),
            state=("state", mode_or_first),
            zip=("zip", mode_or_first),
        )
        .reset_index()
    )
    grouped["recency_days"] = (snapshot_date - grouped["last_donated_at"]).dt.days
    return grouped


def _rank_and_label_clusters(profile: pd.DataFrame):
    """Rank clusters by an engagement score (high monetary/frequency, low recency)."""
    z = profile[RFM_COLUMNS].apply(lambda s: (s - s.mean()) / (s.std(ddof=0) or 1))
    score = z["monetary"] + z["frequency"] - z["recency_days"]
    ranked = score.sort_values(ascending=False).index.tolist()
    labels = {}
    for rank, cluster_id in enumerate(ranked):
        if rank < len(SEGMENT_LABELS_BY_RANK):
            labels[cluster_id] = SEGMENT_LABELS_BY_RANK[rank]
        else:
            labels[cluster_id] = f"Segment {rank + 1}"
    return labels, ranked


def _build_clustered_donors(engine, n_clusters: int = 4):
    """Run the RFM clustering pipeline and return (donors_df, profile, labels, ranked, top_cluster).

    `donors_df` has one row per donor with `cluster`, `segment`, and
    `is_likely_donor` columns added. Shared by `run_cluster_analysis` and
    `get_segment_csv` so both see identical segment assignments for the same
    `n_clusters` (KMeans is seeded with a fixed random_state).
    """
    donors = build_donor_features(engine)
    n_clusters = max(2, min(int(n_clusters), len(donors)))

    scaler = StandardScaler()
    X_rfm = scaler.fit_transform(donors[RFM_COLUMNS])

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    donors["cluster"] = km.fit_predict(X_rfm)

    profile = donors.groupby("cluster")[RFM_COLUMNS].mean()
    labels, ranked = _rank_and_label_clusters(profile)
    donors["segment"] = donors["cluster"].map(labels)
    top_cluster = ranked[0]
    donors["is_likely_donor"] = (donors["cluster"] == top_cluster).astype(int)
    return donors, profile, labels, ranked, top_cluster


def run_cluster_analysis(engine, n_clusters: int = 4) -> Dict[str, Any]:
    donors, profile, labels, ranked, top_cluster = _build_clustered_donors(engine, n_clusters)
    n_clusters = len(ranked)

    # Feature importance: which factors best separate the top segment from
    # the rest? Train a small Random Forest classifier and read off its
    # feature_importances_. One-hot state columns are collapsed back into a
    # single "state" factor so the output reads as a clean ranked list.
    X_imp = donors[PROFILE_FEATURE_COLUMNS].copy()
    state_dummies = pd.get_dummies(donors["state"], prefix="state")
    X_imp = pd.concat([X_imp, state_dummies], axis=1)

    clf = RandomForestClassifier(n_estimators=200, random_state=42, max_depth=5)
    clf.fit(X_imp, donors["is_likely_donor"])

    importances = pd.Series(clf.feature_importances_, index=X_imp.columns)
    state_cols = [c for c in importances.index if c.startswith("state_")]
    combined = pd.concat(
        [importances[PROFILE_FEATURE_COLUMNS], pd.Series({"state": importances[state_cols].sum()})]
    )
    combined = (combined / combined.sum() * 100).sort_values(ascending=False)
    feature_importance: List[Dict[str, Any]] = [
        {"feature": name, "importance_pct": round(float(pct), 1)}
        for name, pct in combined.items()
    ]

    total_amount = float(donors["monetary"].sum())
    total_donors = len(donors)

    segments = []
    for cluster_id in ranked:
        mask = donors["cluster"] == cluster_id
        seg_donors = donors[mask]
        row = profile.loc[cluster_id]
        segments.append(
            {
                "segment": labels[cluster_id],
                "donor_count": int(mask.sum()),
                "pct_of_donors": round(100 * mask.sum() / total_donors, 1),
                "avg_recency_days": round(float(row["recency_days"]), 1),
                "avg_frequency": round(float(row["frequency"]), 1),
                "avg_monetary": round(float(row["monetary"]), 2),
                "pct_of_total_amount": round(100 * seg_donors["monetary"].sum() / total_amount, 1),
            }
        )

    top_donors = (
        donors[donors["cluster"] == top_cluster]
        .sort_values("monetary", ascending=False)
        .head(20)[["donor_name", "segment", "frequency", "monetary", "avg_amount", "recency_days", "state"]]
        .round(2)
        .to_dict(orient="records")
    )

    return {
        "donor_count": total_donors,
        "n_clusters": n_clusters,
        "likely_donor_segment": labels[top_cluster],
        "segments": segments,
        "feature_importance": feature_importance,
        "top_donors": top_donors,
        "note": DONOR_NAME_CAVEAT,
    }


SEGMENT_DOWNLOAD_COLUMNS = [
    "donor_name",
    "segment",
    "frequency",
    "monetary",
    "avg_amount",
    "recency_days",
    "state",
    "zip",
]


def get_segment_csv(engine, n_clusters: int, segment: str) -> Dict[str, str]:
    """Return {csv, filename} for every donor in the requested segment.

    `segment` is matched case-insensitively against the labels produced by
    `_rank_and_label_clusters` (e.g. "Champions", "Loyal", "Occasional",
    "Lapsed", or "Segment N" for n_clusters > 4).
    """
    donors, *_ = _build_clustered_donors(engine, n_clusters)
    available = sorted(donors["segment"].unique().tolist())
    match = next((s for s in available if s.lower() == segment.lower()), None)
    if match is None:
        raise ValueError(f"Unknown segment '{segment}'. Available segments: {', '.join(available)}")

    subset = (
        donors[donors["segment"] == match]
        .sort_values("monetary", ascending=False)[SEGMENT_DOWNLOAD_COLUMNS]
        .round(2)
    )
    filename = f"donor_segment_{match.lower().replace(' ', '_')}.csv"
    return {"csv": subset.to_csv(index=False), "filename": filename}


if __name__ == "__main__":
    from sqlalchemy import create_engine

    database_url = os.getenv("DATABASE_URL", "sqlite:///donations.db")
    engine = create_engine(database_url, future=True)
    import json

    print(json.dumps(run_cluster_analysis(engine), indent=2, default=str))
