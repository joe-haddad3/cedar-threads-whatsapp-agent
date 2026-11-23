"""Per-customer memory, keyed by phone number.

Uses stdlib sqlite3 so there is nothing to install or run. Each customer has a
profile row and a rolling message log. The agent loads the recent history on
every turn so it "remembers" the person across messages and across restarts.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    phone        TEXT PRIMARY KEY,
    name         TEXT,
    status       TEXT DEFAULT 'bot',           -- 'bot' | 'human' (handed off)
    created_at   REAL,
    last_seen    REAL
);
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    phone     TEXT,
    role      TEXT,                             -- 'user' | 'assistant'
    content   TEXT,
    ts        REAL
);
CREATE TABLE IF NOT EXISTS followups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phone       TEXT,
    template    TEXT,
    detail      TEXT,
    due_at      REAL,
    sent        INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phone       TEXT,
    type        TEXT,                             -- chat_started, product_asked, ...
    data        TEXT,                             -- JSON blob of extra detail
    ts          REAL
);
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


def get_or_create_customer(phone: str, name: str | None = None) -> dict[str, Any]:
    now = time.time()
    with _conn() as c:
        row = c.execute("SELECT * FROM customers WHERE phone=?", (phone,)).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO customers (phone, name, created_at, last_seen) VALUES (?,?,?,?)",
                (phone, name, now, now),
            )
            row = c.execute("SELECT * FROM customers WHERE phone=?", (phone,)).fetchone()
        else:
            c.execute(
                "UPDATE customers SET last_seen=?, name=COALESCE(?, name) WHERE phone=?",
                (now, name, phone),
            )
        return dict(row)


def set_status(phone: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE customers SET status=? WHERE phone=?", (status, phone))


def set_name(phone: str, name: str) -> None:
    with _conn() as c:
        c.execute("UPDATE customers SET name=? WHERE phone=?", (name, phone))


def add_message(phone: str, role: str, content: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO messages (phone, role, content, ts) VALUES (?,?,?,?)",
            (phone, role, content, time.time()),
        )


def history(phone: str, limit: int = 12) -> list[dict[str, str]]:
    """Recent turns oldest-first, as {role, content} for the LLM."""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE phone=? ORDER BY id DESC LIMIT ?",
            (phone, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# --- follow-ups --------------------------------------------------------------
def add_followup(phone: str, template: str, detail: str, due_at: float) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO followups (phone, template, detail, due_at) VALUES (?,?,?,?)",
            (phone, template, detail, due_at),
        )
        return int(cur.lastrowid)


def due_followups(now: float | None = None) -> list[dict[str, Any]]:
    now = now or time.time()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM followups WHERE sent=0 AND due_at<=?", (now,)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_followup_sent(followup_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE followups SET sent=1 WHERE id=?", (followup_id,))


# --- events (analytics) ------------------------------------------------------
def add_event(phone: str, type: str, data: dict | None = None, ts: float | None = None) -> None:
    import json

    with _conn() as c:
        c.execute(
            "INSERT INTO events (phone, type, data, ts) VALUES (?,?,?,?)",
            (phone, type, json.dumps(data or {}, ensure_ascii=False), ts or time.time()),
        )


def all_events() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT phone, type, data, ts FROM events ORDER BY ts").fetchall()
    return [dict(r) for r in rows]


def all_customers() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT phone, name, status, created_at, last_seen FROM customers"
        ).fetchall()
    return [dict(r) for r in rows]


def message_texts(role: str = "user", limit: int = 2000) -> list[str]:
    """All message bodies for a role (used by topic clustering)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT content FROM messages WHERE role=? ORDER BY id DESC LIMIT ?",
            (role, limit),
        ).fetchall()
    return [r["content"] for r in rows]
