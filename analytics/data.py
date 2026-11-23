"""Load the agent's events, orders and customers into pandas DataFrames.

This is the single source of truth every other analytics module reads from, so
the shapes are defined here once.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import config
from app import memory


def events_df() -> pd.DataFrame:
    rows = memory.all_events()
    df = pd.DataFrame(rows, columns=["phone", "type", "data", "ts"])
    if df.empty:
        return df.assign(datetime=pd.NaT)
    df["datetime"] = pd.to_datetime(df["ts"], unit="s")
    df["data"] = df["data"].apply(lambda s: json.loads(s) if isinstance(s, str) and s else {})
    return df


def orders_df() -> pd.DataFrame:
    path = Path(config.ORDERS_DIR) / "orders.jsonl"
    cols = [
        "order_id", "created_at", "phone", "customer_name", "product_id",
        "product_name", "size", "quantity", "unit_price_usd", "total_usd", "status",
    ]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["total_usd"] = pd.to_numeric(df["total_usd"], errors="coerce").fillna(0.0)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(1).astype(int)
    return df


def customers_df() -> pd.DataFrame:
    df = pd.DataFrame(memory.all_customers(), columns=["phone", "name", "status", "created_at", "last_seen"])
    if df.empty:
        return df
    df["created_at"] = pd.to_datetime(df["created_at"], unit="s")
    df["last_seen"] = pd.to_datetime(df["last_seen"], unit="s")
    return df


def load_all() -> dict[str, pd.DataFrame]:
    return {"events": events_df(), "orders": orders_df(), "customers": customers_df()}
