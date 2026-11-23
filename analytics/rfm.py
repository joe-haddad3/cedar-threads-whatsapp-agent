"""RFM segmentation.

For each customer who has ordered, score Recency, Frequency and Monetary 1-4
(4 = best) and map the combined score to a human segment the shop owner can act
on (Champions, Loyal, At Risk, ...). Falls back gracefully on tiny datasets
where quantile binning isn't possible.
"""
from __future__ import annotations

import pandas as pd


def _score(series: pd.Series, reverse: bool = False) -> pd.Series:
    """Quantile score 1-4; reverse=True means lower raw value scores higher."""
    labels = [4, 3, 2, 1] if reverse else [1, 2, 3, 4]
    try:
        return pd.qcut(series.rank(method="first"), 4, labels=labels).astype(int)
    except (ValueError, IndexError):
        # too few distinct values for 4 bins — rank into available buckets
        ranked = series.rank(method="dense")
        n = ranked.max()
        scaled = ((ranked - 1) / max(n - 1, 1) * 3 + 1).round().astype(int)
        return (5 - scaled) if reverse else scaled


def _segment(r: int, f: int, m: int) -> str:
    if r >= 3 and f >= 3:
        return "Champions"
    if f >= 3:
        return "Loyal"
    if r >= 3 and f <= 2:
        return "New / Promising"
    if r == 2 and m >= 3:
        return "At Risk"
    if r == 1 and m >= 3:
        return "Can't Lose Them"
    if r <= 2 and f <= 2:
        return "Hibernating"
    return "Needs Attention"


def compute(orders: pd.DataFrame) -> pd.DataFrame:
    cols = ["phone", "customer_name", "recency_days", "frequency", "monetary", "R", "F", "M", "segment"]
    if orders.empty:
        return pd.DataFrame(columns=cols)

    now = pd.Timestamp.utcnow().tz_localize(None)
    g = orders.groupby("phone").agg(
        customer_name=("customer_name", "last"),
        last_order=("created_at", "max"),
        frequency=("order_id", "count"),
        monetary=("total_usd", "sum"),
    )
    g["recency_days"] = (now - g["last_order"]).dt.days

    g["R"] = _score(g["recency_days"], reverse=True)  # recent = high R
    g["F"] = _score(g["frequency"])
    g["M"] = _score(g["monetary"])
    g["segment"] = [ _segment(r, f, m) for r, f, m in zip(g["R"], g["F"], g["M"]) ]

    out = g.reset_index()[
        ["phone", "customer_name", "recency_days", "frequency", "monetary", "R", "F", "M", "segment"]
    ]
    out["monetary"] = out["monetary"].round(2)
    return out.sort_values(["segment", "monetary"], ascending=[True, False]).reset_index(drop=True)


def segment_summary(rfm: pd.DataFrame) -> pd.DataFrame:
    if rfm.empty:
        return pd.DataFrame(columns=["segment", "customers", "revenue", "avg_recency_days"])
    s = (
        rfm.groupby("segment")
        .agg(customers=("phone", "count"), revenue=("monetary", "sum"), avg_recency_days=("recency_days", "mean"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    s["revenue"] = s["revenue"].round(2)
    s["avg_recency_days"] = s["avg_recency_days"].round(1)
    return s
