"""Typed event logging — the bridge between Part A (the agent) and Part B
(the analytics layer).

Every meaningful thing that happens in a conversation is recorded as an event in
SQLite, so Part B can later compute KPIs, segments and topics from them. Events
are deliberately small and typed; rich detail goes in the `data` dict.
"""
from __future__ import annotations

from app import memory


class E:
    """Event type constants."""

    CHAT_STARTED = "chat_started"
    PRODUCT_ASKED = "product_asked"
    STOCK_CHECKED = "stock_checked"
    OBJECTION = "objection"
    ORDER_PLACED = "order_placed"
    HANDOFF = "handoff"
    FOLLOWUP_SCHEDULED = "followup_scheduled"
    OFFTOPIC_REFUSED = "offtopic_refused"


# Keywords that signal a price objection ("too expensive"), across languages.
_OBJECTION_SIGNALS = [
    "ghali", "ghalye", "ghalieh", "expensive", "too much", "cher", "chere",
    "pricey", "2addesh ktir", "ktir ghali", "mech rخيص", "غالي", "كتير",
    "طالع غالي", "trop cher",
]


def log(phone: str, type: str, **data) -> None:
    """Record an event. Never raises — analytics must never break a live chat."""
    try:
        memory.add_event(phone, type, data or None)
    except Exception:  # pragma: no cover - defensive
        pass


def looks_like_objection(text: str) -> bool:
    low = (text or "").lower()
    return any(sig in low for sig in _OBJECTION_SIGNALS)
