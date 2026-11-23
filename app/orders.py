"""Order persistence.

Default backend is a local CSV (zero setup, perfect for the course and demo).
A Google Sheets backend is included behind the same `save_order` function so the
client can flip ORDER_BACKEND=sheets later without touching the agent code.
"""
from __future__ import annotations

import csv
import json
import time
import uuid
from pathlib import Path
from typing import Any

import config

_FIELDS = [
    "order_id",
    "created_at",
    "phone",
    "customer_name",
    "product_id",
    "product_name",
    "size",
    "quantity",
    "unit_price_usd",
    "total_usd",
    "status",
]


def _new_order_id() -> str:
    return "CT-" + uuid.uuid4().hex[:8].upper()


def build_order(
    *,
    phone: str,
    customer_name: str | None,
    product: dict[str, Any],
    size: str,
    quantity: int,
) -> dict[str, Any]:
    unit = float(product["price_usd"])
    return {
        "order_id": _new_order_id(),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "phone": phone,
        "customer_name": customer_name or "",
        "product_id": product["id"],
        "product_name": product["name"],
        "size": size,
        "quantity": quantity,
        "unit_price_usd": unit,
        "total_usd": round(unit * quantity, 2),
        "status": "confirmed",
    }


def save_order(order: dict[str, Any]) -> dict[str, Any]:
    if config.ORDER_BACKEND == "sheets":
        _save_to_sheets(order)
    else:
        _save_to_csv(order)
    _append_json(order)  # always keep a local JSON mirror
    return order


def _save_to_csv(order: dict[str, Any]) -> None:
    path = Path(config.ORDERS_DIR) / "orders.csv"
    new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: order.get(k, "") for k in _FIELDS})


def _append_json(order: dict[str, Any]) -> None:
    path = Path(config.ORDERS_DIR) / "orders.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(order, ensure_ascii=False) + "\n")


def _save_to_sheets(order: dict[str, Any]) -> None:  # pragma: no cover - optional
    """Append to Google Sheets. Requires gspread + a service account.

    Enable by: pip install gspread google-auth, set GOOGLE_SHEETS_ID and
    GOOGLE_SERVICE_ACCOUNT_JSON (path to the key file), ORDER_BACKEND=sheets.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise RuntimeError(
            "ORDER_BACKEND=sheets but gspread is not installed. "
            "Run: pip install gspread google-auth"
        ) from exc

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON, scopes=scopes
    )
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(config.GOOGLE_SHEETS_ID).sheet1
    if not sheet.get_all_values():
        sheet.append_row(_FIELDS)
    sheet.append_row([order.get(k, "") for k in _FIELDS])
