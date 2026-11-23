"""Cluster customer messages into topics, WITH real verbatim quotes.

Uses the LLM when a real one is configured (Groq); otherwise falls back to a
keyword-based clustering so the dashboard still works offline. Either way, every
topic is backed by actual customer quotes — never invented.
"""
from __future__ import annotations

import json
import re

import config
from app.llm import get_llm

_KEYWORDS = {
    "Pricing & affordability": ["se3r", "addesh", "2addesh", "price", "how much", "combien", "ghali", "cher", "expensive", "discount", "سعر", "غالي"],
    "Sizing & fit": ["size", "taille", "qyes", "2yes", "fit", "small", "large", "xl", "32", "34", "قياس"],
    "Delivery & shipping": ["delivery", "deliver", "livraison", "ship", "tripoli", "saida", "beirut", "wsal", "توصيل"],
    "Colors & styles": ["color", "colour", "lon", "alwan", "couleur", "black", "aswad", "لون"],
    "Payment methods": ["pay", "omt", "whish", "cash", "paiement", "edfa3", "دفع"],
    "Complaints & issues": ["complaint", "never arrived", "wrong", "exchange", "ma wsal", "7aki ma3 7ada", "مشكلة"],
}


def _keyword_cluster(messages: list[str]) -> list[dict]:
    topics = []
    used = set()
    for name, keys in _KEYWORDS.items():
        quotes, count = [], 0
        for i, m in enumerate(messages):
            low = m.lower()
            if any(k in low for k in keys):
                count += 1
                if i not in used and len(quotes) < 3:
                    quotes.append(m)
                    used.add(i)
        if count:
            topics.append({"topic": name, "count": count, "quotes": quotes})
    return sorted(topics, key=lambda t: t["count"], reverse=True)


def _llm_cluster(messages: list[str]) -> list[dict] | None:
    sample = messages[:120]
    numbered = "\n".join(f"{i+1}. {m}" for i, m in enumerate(sample))
    prompt = (
        "You are analysing real customer WhatsApp messages for a Lebanese clothing shop. "
        "Group them into 4-7 clear topics. For each topic give a short name, the count of "
        "messages that fit it, and 2-3 VERBATIM example quotes copied exactly from the list "
        "(never invent or translate). Return ONLY JSON: "
        '[{"topic": "...", "count": N, "quotes": ["...", "..."]}]\n\nMessages:\n' + numbered
    )
    try:
        resp = get_llm().chat([{"role": "user", "content": prompt}], tools=None)
        text = resp.content or ""
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        start, end = text.find("["), text.rfind("]")
        data = json.loads(text[start : end + 1])
        return [t for t in data if t.get("topic") and t.get("quotes")]
    except Exception:
        return None


def cluster(messages: list[str]) -> list[dict]:
    messages = [m for m in messages if m and m.strip()]
    if not messages:
        return []
    if not config.USE_MOCK_LLM:
        llm_topics = _llm_cluster(messages)
        if llm_topics:
            return llm_topics
    return _keyword_cluster(messages)
