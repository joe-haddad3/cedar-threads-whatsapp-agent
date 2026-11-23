"""Scheduled follow-ups.

The agent calls schedule_followup, which stores a due time in the DB. This
module is the worker that actually sends due follow-ups using approved WhatsApp
templates. Run it on a cron / Task Scheduler every few minutes:

    python -m app.followups

(It is also importable so a test can drive it with a fixed clock.)
"""
from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from typing import Any

import config
from app import memory, whatsapp

log = logging.getLogger("followups")


@lru_cache(maxsize=1)
def _templates() -> dict[str, dict[str, Any]]:
    with open(config.DATA_DIR / "templates.json", encoding="utf-8") as fh:
        data = json.load(fh)
    return {t["name"]: t for t in data["templates"]}


def _render(template_name: str, name: str, detail: str) -> str:
    tpl = _templates().get(template_name)
    if not tpl:
        return f"Hi {name}, just checking in about {detail}."
    return tpl["body"].replace("{{1}}", name or "there").replace("{{2}}", detail or "your items")


def run_due(now: float | None = None) -> int:
    """Send every follow-up whose time has come. Returns how many were sent."""
    now = now or time.time()
    sent = 0
    for fu in memory.due_followups(now):
        customer = memory.get_or_create_customer(fu["phone"])
        name = customer.get("name") or "there"
        tpl = _templates().get(fu["template"])
        if tpl:
            whatsapp.send_template(
                fu["phone"],
                fu["template"],
                params=[name, fu["detail"]],
                language=tpl.get("language", "en"),
            )
        else:
            whatsapp.send_text(fu["phone"], _render(fu["template"], name, fu["detail"]))
        memory.mark_followup_sent(fu["id"])
        sent += 1
        log.info("sent follow-up %s to %s", fu["template"], fu["phone"])
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = run_due()
    print(f"Sent {n} follow-up(s).")
