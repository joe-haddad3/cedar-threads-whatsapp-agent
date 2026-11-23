"""Catalog + FAQ retrieval.

This is the "R" in RAG: before the agent answers anything about products or
prices, it must retrieve the facts from here. We deliberately keep retrieval
simple and dependency-free (token overlap scoring) so it runs offline on a slow
connection — no embedding model to download. The scoring is good enough for a
catalog of this size and is easy for the client to reason about.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from config import DATA_DIR

_WORD_RE = re.compile(r"[\w؀-ۿ]+", re.UNICODE)  # includes Arabic range

# Common filler words (EN/FR + chat fillers). Dropped before scoring so a word
# like "how" or "the" can never, on its own, match a product or FAQ entry.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "am", "be", "do", "does", "did", "you", "i",
    "me", "my", "we", "us", "to", "of", "in", "on", "for", "and", "or", "how",
    "much", "many", "long", "what", "it", "this", "that", "please", "can",
    "could", "would", "will", "want", "like", "show", "get", "got", "there",
    "here", "your", "with", "have", "has", "looking", "need", "some", "any",
    "el", "la", "le", "les", "un", "une", "des", "du", "pour", "est", "ce",
    "je", "tu", "vous", "moi", "combien",
}


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def _score_tokens(text: str) -> set[str]:
    """Tokens used for relevance scoring, minus filler words."""
    return {t for t in _tokens(text) if t not in _STOPWORDS and len(t) > 1}


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    with open(DATA_DIR / "catalog.json", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _faq() -> dict[str, Any]:
    with open(DATA_DIR / "faq.json", encoding="utf-8") as fh:
        return json.load(fh)


def shop_info() -> dict[str, Any]:
    """Shop-level facts: name, delivery, payment methods."""
    return _catalog()["shop"]


def all_products() -> list[dict[str, Any]]:
    return _catalog()["products"]


def get_product(product_id: str) -> dict[str, Any] | None:
    for p in all_products():
        if p["id"].lower() == (product_id or "").lower():
            return p
    return None


def _product_haystack(p: dict[str, Any]) -> str:
    return " ".join(
        [p["id"], p["name"], p["category"], p["description"], " ".join(p["colors"])]
    )


def search_products(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return products ranked by token overlap with the query.

    Falls back to a category/substring match so short queries like "hoodie"
    or "jeans" still work even when scoring is thin.
    """
    q_tokens = _score_tokens(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for p in all_products():
        hay = _score_tokens(_product_haystack(p))
        overlap = len(q_tokens & hay)
        # Boost exact category / substring hits.
        if query and query.lower() in _product_haystack(p).lower():
            overlap += 2
        if overlap:
            scored.append((overlap, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:limit]]


def search_faq(query: str, threshold: int = 1) -> dict[str, Any] | None:
    """Best-matching FAQ entry, or None if nothing is relevant."""
    q_tokens = _score_tokens(query)
    best: tuple[int, dict[str, Any]] | None = None
    for entry in _faq()["entries"]:
        hay: set[str] = set()
        for phrase in entry["q"]:
            hay |= _score_tokens(phrase)
        overlap = len(q_tokens & hay)
        if best is None or overlap > best[0]:
            best = (overlap, entry)
    if best and best[0] >= threshold:
        return best[1]
    return None


def refresh_cache() -> None:
    """Drop cached JSON (use after editing catalog/FAQ at runtime)."""
    _catalog.cache_clear()
    _faq.cache_clear()
