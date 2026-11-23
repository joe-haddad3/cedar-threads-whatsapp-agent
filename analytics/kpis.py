"""Headline KPIs computed with pandas from events + orders.

conversion = customers who ordered / customers who chatted
AOV        = revenue / orders
repeat     = customers with 2+ orders / customers with 1+ order
churn      = past buyers with no activity in CHURN_DAYS and no recent order
"""
from __future__ import annotations

import pandas as pd

CHURN_DAYS = 21


def compute(events: pd.DataFrame, orders: pd.DataFrame, customers: pd.DataFrame) -> dict:
    now = pd.Timestamp.utcnow().tz_localize(None)

    chat_phones = set(events.loc[events["type"] == "chat_started", "phone"]) if not events.empty else set()
    if not chat_phones and not customers.empty:
        chat_phones = set(customers["phone"])
    total_chats = len(chat_phones)

    order_phones = set(orders["phone"]) if not orders.empty else set()
    orders_count = int(len(orders))
    revenue = float(orders["total_usd"].sum()) if not orders.empty else 0.0
    aov = revenue / orders_count if orders_count else 0.0

    # repeat buyers
    if not orders.empty:
        per_cust = orders.groupby("phone").size()
        repeat_buyers = int((per_cust >= 2).sum())
        buyers = int(per_cust.shape[0])
    else:
        repeat_buyers = buyers = 0
    repeat_rate = repeat_buyers / buyers if buyers else 0.0

    conversion = len(order_phones & chat_phones) / total_chats if total_chats else 0.0

    def ev_rate(evtype: str) -> float:
        if events.empty or not total_chats:
            return 0.0
        phones = set(events.loc[events["type"] == evtype, "phone"])
        return len(phones & chat_phones) / total_chats

    objection_rate = ev_rate("objection")
    handoff_rate = ev_rate("handoff")
    offtopic_count = int((events["type"] == "offtopic_refused").sum()) if not events.empty else 0

    # churn: bought before, last order older than CHURN_DAYS
    churned = 0
    if not orders.empty:
        last_order = orders.groupby("phone")["created_at"].max()
        churned = int((last_order < (now - pd.Timedelta(days=CHURN_DAYS))).sum())
    churn_rate = churned / buyers if buyers else 0.0

    # top products
    top_products = []
    if not orders.empty:
        tp = (
            orders.groupby("product_name")
            .agg(orders=("order_id", "count"), revenue=("total_usd", "sum"))
            .sort_values("revenue", ascending=False)
            .head(5)
            .reset_index()
        )
        top_products = tp.to_dict("records")

    return {
        "total_chats": total_chats,
        "total_customers": int(customers.shape[0]) if not customers.empty else total_chats,
        "orders_count": orders_count,
        "revenue_usd": round(revenue, 2),
        "aov_usd": round(aov, 2),
        "conversion_rate": round(conversion, 4),
        "repeat_rate": round(repeat_rate, 4),
        "objection_rate": round(objection_rate, 4),
        "handoff_rate": round(handoff_rate, 4),
        "offtopic_count": offtopic_count,
        "churned_customers": churned,
        "churn_rate": round(churn_rate, 4),
        "top_products": top_products,
    }


def orders_timeseries(orders: pd.DataFrame, freq: str = "D") -> pd.DataFrame:
    """Orders + revenue bucketed by day ('D') or week ('W')."""
    if orders.empty:
        return pd.DataFrame(columns=["period", "orders", "revenue"])
    g = (
        orders.set_index("created_at")
        .resample(freq)
        .agg(orders=("order_id", "count"), revenue=("total_usd", "sum"))
        .reset_index()
        .rename(columns={"created_at": "period"})
    )
    return g
