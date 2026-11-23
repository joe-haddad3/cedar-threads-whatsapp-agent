"""Win-back targeting.

Rules pick who the shop should re-engage, prioritised by value, and suggest an
approved follow-up template for each. Two pools:

  * Lapsed buyers  — ordered before, gone quiet (high monetary + low recency).
  * Warm no-buy    — chatted/showed interest but never ordered, then went quiet.
"""
from __future__ import annotations

import pandas as pd

QUIET_DAYS = 14


def targets(orders: pd.DataFrame, events: pd.DataFrame, rfm: pd.DataFrame, limit: int = 25) -> pd.DataFrame:
    now = pd.Timestamp.utcnow().tz_localize(None)
    rows = []

    # 1) Lapsed buyers from the RFM table.
    if not rfm.empty:
        lapsed = rfm[rfm["segment"].isin(["At Risk", "Can't Lose Them", "Hibernating"])]
        for _, r in lapsed.iterrows():
            rows.append({
                "phone": r["phone"],
                "customer_name": r["customer_name"],
                "reason": f"{r['segment']} — {int(r['recency_days'])}d since last order",
                "value_usd": float(r["monetary"]),
                "template": "back_in_stock" if r["segment"] == "Can't Lose Them" else "quiet_checkin",
                "priority": float(r["monetary"]) + (30 if r["segment"] == "Can't Lose Them" else 0),
            })

    # 2) Warm leads: chatted, never ordered, quiet for QUIET_DAYS.
    if not events.empty:
        buyers = set(orders["phone"]) if not orders.empty else set()
        last_activity = events.groupby("phone")["datetime"].max()
        interested = set(events.loc[events["type"].isin(["product_asked", "stock_checked", "objection"]), "phone"])
        names = {}  # phone -> any name we can find
        if not orders.empty:
            names = dict(zip(orders["phone"], orders["customer_name"]))
        for phone in interested - buyers:
            last = last_activity.get(phone)
            if last is None or (now - last).days < QUIET_DAYS:
                continue
            objected = not events[(events["phone"] == phone) & (events["type"] == "objection")].empty
            rows.append({
                "phone": phone,
                "customer_name": names.get(phone, ""),
                "reason": ("objected on price, went quiet" if objected else "browsed, never ordered") + f" ({(now - last).days}d)",
                "value_usd": 0.0,
                "template": "abandoned_cart",
                "priority": 10 if objected else 5,
            })

    df = pd.DataFrame(rows, columns=["phone", "customer_name", "reason", "value_usd", "template", "priority"])
    if df.empty:
        return df
    return df.sort_values("priority", ascending=False).drop(columns="priority").head(limit).reset_index(drop=True)
