"""Guardrails.

Three jobs:
1. The system prompt — the agent's persona and hard rules.
2. Topic lock — refuse general-purpose-assistant requests. This is a compliance
   requirement: Meta banned general-purpose AI chatbots on WhatsApp Business in
   January 2026, so the agent must stay strictly on shop business.
3. Price-leak check — a safety net that catches any price the model states that
   did NOT come from a tool result, so an invented price never reaches a customer.
"""
from __future__ import annotations

import re
from typing import Any

import config
from app import rag

PRICE_RE = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)")

# Signals of a general-purpose request we must refuse.
_OFFTOPIC_SIGNALS = [
    "write a poem", "write me a", "write an essay", "essay", "poem", "joke",
    "tell me a story", "translate this", "weather", "news", "who won",
    "python code", "write code", "code for me", "homework", "recipe", "horoscope",
    "lyrics", "president", "election", "stock price", "bitcoin", "math problem",
    "solve this equation", "chatgpt", "act as", "ignore previous",
    # French
    "poeme", "poème", "meteo", "météo", "actualités", "actualites", "recette",
    "ecris moi", "écris-moi", "blague",
    # Arabic
    "قصيدة", "طقس", "اخبار", "أخبار", "نكتة", "وصفة",
]

# Shop vocabulary that marks a message as on-topic (English/French/Arabic/transliteration).
_ONTOPIC_SIGNALS = [
    "price", "cost", "how much", "size", "color", "colour", "stock", "available",
    "order", "buy", "delivery", "shipping", "pay", "payment", "return", "exchange",
    "hoodie", "tee", "shirt", "jeans", "jacket", "cap", "dress", "pants", "cargo",
    "socks", "catalog", "shop", "wear", "fit", "discount", "sale", "cedar",
    "tmn", "se3r", "se3er", "2addesh", "addesh", "kam", "ghali", "rkhis",
    "prix", "combien", "livraison", "taille", "couleur", "acheter", "commande",
    "سعر", "تمن", "قياس", "لون", "توصيل", "طلب", "شراء", "دفع", "غالي",
]


def detect_script(text: str) -> str:
    """'arabic' if the message contains Arabic-script letters, 'latin' if it
    contains Latin letters, else 'neutral' (emoji/numbers/punctuation only)."""
    if re.search(r"[؀-ۿ]", text or ""):
        return "arabic"
    if re.search(r"[A-Za-z]", text or ""):
        return "latin"
    return "neutral"


def _script_directive(script: str) -> str:
    if script == "latin":
        return (
            "\n\nIMPORTANT FOR THIS MESSAGE: the customer wrote in LATIN letters. "
            "The WHOLE reply — every word and every sentence — MUST be in Latin "
            "letters only (Arabizi / French / English). Do NOT add any Arabic-"
            "script sentence, not even a translation at the end, and not even for "
            "a greeting like 'marhaba'."
        )
    if script == "arabic":
        return (
            "\n\nIMPORTANT FOR THIS MESSAGE: the customer wrote in Arabic script. "
            "Reply in Arabic script (natural Lebanese dialect)."
        )
    return ""


_ARABIC_CLASS = "؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿"
_ARABIC_RUN = re.compile(f"[{_ARABIC_CLASS}][{_ARABIC_CLASS}\\s،؛؟!?.,]*")


def enforce_reply_script(reply: str, script: str) -> str:
    """If the customer wrote in Latin letters, remove any stray Arabic-script
    text the model may have appended, so the reply stays fully Latin.

    Only triggers for Latin-script conversations and only when Arabic-script
    characters are actually present; otherwise the reply is returned unchanged.
    If stripping would leave almost nothing (model answered entirely in Arabic),
    the original is kept rather than sending an empty message.
    """
    if script != "latin" or not reply:
        return reply
    if not re.search(f"[{_ARABIC_CLASS}]", reply):
        return reply
    cleaned = _ARABIC_RUN.sub("", reply)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned if len(cleaned) >= 3 else reply


def build_system_prompt(customer_name: str | None = None, script: str = "neutral") -> str:
    shop = rag.shop_info()
    who = f"The customer's name is {customer_name}. " if customer_name else ""
    return f"""You are the sales assistant for {shop['name']}, a Lebanese online clothing shop. {who}

LANGUAGE — mirror the customer's language AND script exactly:
- If they write in Arabic script, reply in Arabic script (natural Lebanese dialect, not formal).
- If they write in "Arabizi" / Lebanese Latin — Arabic words in Latin letters, often with numbers (3=ع, 7=ح, 2=ء/ق), e.g. "chou 3andak", "addesh", "kifak", "baddi", "gheir" — reply in the SAME Arabizi Latin style. Do NOT switch to Arabic script. Write it the way people text: plain letters a-z and the numbers 3, 7, 2 (e.g. "shu 3indna", "kifak"). Never use phonetic/IPA symbols like ʃ, ʿ, ū, ḥ.
- If they write in French, reply in French. If in English, reply in English.
- Match the SCRIPT of the customer's last message: Latin letters in -> Latin letters out, even for a single word. A greeting like "marhaba", "hi" or "chou" written in Latin letters gets a Latin-letters reply, never Arabic script.

WHAT YOU DO
- Help with products, prices, sizes, colors, stock, delivery, payment, returns, and placing orders.
- Handle price objections kindly (e.g. "ghali"/too expensive): acknowledge, note quality/value, mention free delivery over ${shop['delivery']['free_over_usd']}, never invent a discount.

HARD RULES
- NEVER state a price, size availability, or product detail from memory. ALWAYS call search_catalog or check_stock first and use ONLY what the tool returns.
- NEVER invent products, prices, colors, or promotions.
- Take an order ONLY after the customer confirms item + size + quantity, then call create_order. Read back the total.
- If the customer is upset, wants a human, or has a complaint/return dispute, call handoff_to_human.
- If the customer goes quiet or asks to be notified (restock, "let me think"), you may call schedule_followup.
- Stay strictly on {shop['name']} business. Politely refuse anything else (general questions, coding, translations, news, etc.). You are not a general assistant.

STYLE
- Warm, concise, WhatsApp-friendly. A few short lines. Light emoji is fine.{_script_directive(script)}"""


def is_on_topic(text: str, has_order_context: bool = False) -> tuple[bool, str]:
    """Return (on_topic, refusal_message). Refusal only when clearly off-topic."""
    low = (text or "").lower()

    off = any(sig in low for sig in _OFFTOPIC_SIGNALS)
    on = any(sig in low for sig in _ONTOPIC_SIGNALS)

    # On-topic signal, an ongoing order, or a short/greeting message => allow.
    if on or has_order_context or len(low.split()) <= 4:
        if not off:
            return True, ""
    if off and not on:
        return False, (
            f"Sorry, I can only help with {config.SHOP_NAME} — our clothes, prices, "
            "sizes, orders and delivery. Is there something from the shop I can help with? 🙂"
        )
    return True, ""


def allowed_prices() -> set[str]:
    """Every legitimate price the agent is ever allowed to say: catalog prices
    plus shop delivery figures. Used by the leak check."""
    prices: set[str] = set()
    for p in rag.all_products():
        prices.add(_fmt(p["price_usd"]))
    shop = rag.shop_info()
    d = shop["delivery"]
    for key in ("beirut_usd", "outside_beirut_usd", "free_over_usd"):
        prices.add(_fmt(d[key]))
    return prices


def prices_from_tool_results(tool_results: list[str]) -> set[str]:
    """Collect every numeric price present in this turn's tool outputs."""
    found: set[str] = set()
    for raw in tool_results:
        for m in re.findall(r"\"(?:price_usd|total_usd|unit_price_usd)\"\s*:\s*([\d.]+)", raw):
            found.add(_fmt(float(m)))
        for m in re.findall(r"(\d+(?:\.\d+)?)", raw):
            found.add(_fmt(float(m)))
    return found


def check_price_leak(reply: str, tool_results: list[str]) -> tuple[bool, list[str]]:
    """Return (clean, leaked_prices). A price is a leak if it appears in the
    reply but neither in this turn's tool results nor in the global allow-list."""
    said = {_fmt(float(m)) for m in PRICE_RE.findall(reply or "")}
    permitted = allowed_prices() | prices_from_tool_results(tool_results)
    leaked = sorted(said - permitted)
    return (not leaked), leaked


def _fmt(value: float | str) -> str:
    f = float(value)
    return str(int(f)) if f == int(f) else f"{f:.2f}"
