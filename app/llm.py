"""LLM client abstraction.

The agent talks to an `LLMClient` interface, not to Groq directly. Two
implementations exist:

* `GroqClient`   - real calls to Groq's OpenAI-compatible endpoint, with tool
                   calling. Used whenever GROQ_API_KEY is set.
* `MockClient`   - a deterministic, rule-based stand-in that emulates tool
                   calling so the agent, CLI and tests all run offline. It is
                   NOT a language model; it just routes intents to tools and
                   phrases answers from the tool results.

Keeping this behind an interface means swapping providers (OpenAI, local
Ollama, etc.) is a one-file change and the test suite never needs the network.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import config


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient:
    """Interface the agent depends on."""

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        raise NotImplementedError

    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Real client (Groq)                                                          #
# --------------------------------------------------------------------------- #
class GroqClient(LLMClient):
    def __init__(self) -> None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        import httpx

        self._client = httpx.Client(
            base_url=config.GROQ_BASE_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            timeout=60.0,
        )

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": config.LLM_MODEL,
            "messages": messages,
            "temperature": config.LLM_TEMPERATURE,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        choice = resp.json()["choices"][0]["message"]

        calls: list[ToolCall] = []
        for tc in choice.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args))

        return LLMResponse(content=choice.get("content"), tool_calls=calls)

    def transcribe(self, audio_path: str) -> str:
        with open(audio_path, "rb") as fh:
            resp = self._client.post(
                "/audio/transcriptions",
                files={"file": (audio_path, fh, "application/octet-stream")},
                data={"model": config.WHISPER_MODEL},
            )
        resp.raise_for_status()
        return resp.json().get("text", "").strip()


# --------------------------------------------------------------------------- #
# Mock client (offline brain)                                                 #
# --------------------------------------------------------------------------- #
class MockClient(LLMClient):
    """Deterministic agent brain for offline demos and tests.

    It inspects the latest message and either (a) calls the right tool, or
    (b) turns a fresh tool result into a reply. It intentionally relies only on
    tool results for any product fact — it never fabricates prices — which makes
    it a faithful stand-in for the guardrails we want from the real model.
    """

    _n = 0

    def _next_id(self) -> str:
        MockClient._n += 1
        return f"mock_call_{MockClient._n}"

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        last = messages[-1]

        # If we just got a tool result, phrase an answer from it.
        if last["role"] == "tool":
            return LLMResponse(content=self._answer_from_tool(last))

        text = (last.get("content") or "").lower()

        # Order confirmation -> create_order (only if we already proposed one).
        if self._is_confirmation(text) and self._pending_order(messages):
            draft = self._pending_order(messages)
            return LLMResponse(
                tool_calls=[ToolCall(self._next_id(), "create_order", draft)]
            )

        # Explicit "talk to a human" / frustration -> handoff.
        if any(k in text for k in ["human", "agent", "person", "complaint", "manager", "موظف", "حدا"]):
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        self._next_id(),
                        "handoff_to_human",
                        {"reason": "customer asked for a human"},
                    )
                ]
            )

        # Stock question -> check_stock.
        if any(k in text for k in ["in stock", "available", "size", "do you have", "متوفر", "disponible"]):
            return LLMResponse(
                tool_calls=[ToolCall(self._next_id(), "check_stock", {"query": text})]
            )

        # Price / product question -> search_catalog.
        if any(
            k in text
            for k in ["price", "how much", "cost", "تمن", "سعر", "prix", "combien",
                      "hoodie", "tee", "t-shirt", "jeans", "jacket", "cap", "dress",
                      "pants", "cargo", "socks", "catalog", "show me", "looking for"]
        ):
            return LLMResponse(
                tool_calls=[ToolCall(self._next_id(), "search_catalog", {"query": text})]
            )

        # Greeting / fallback.
        if any(k in text for k in ["hi", "hello", "marhaba", "salam", "bonjour", "مرحبا", "سلام"]):
            return LLMResponse(
                content=f"Marhaba! Welcome to {config.SHOP_NAME}. "
                "I can help with our clothes, prices, sizes and orders. What are you looking for?"
            )

        return LLMResponse(
            content="I can help with our products, prices, sizes, delivery and orders. "
            "What would you like to know?"
        )

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _is_confirmation(text: str) -> bool:
        return any(
            k in text
            for k in ["yes", "confirm", "ok", "okay", "akid", "na3am", "oui", "نعم", "اكيد", "تمام"]
        )

    @staticmethod
    def _pending_order(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Find the product the assistant most recently offered.

        Works both within a turn (from a search_catalog tool result) and across
        turns (by spotting a catalog id like "HD-001" in a prior assistant
        reply, since tool results are not kept in the stored history)."""
        from app import rag

        def _draft(product_id: str) -> dict[str, Any] | None:
            p = rag.get_product(product_id)
            if not p:
                return None
            sizes = [s for s, q in p["variants"].items() if q > 0]
            return {"product_id": product_id, "size": sizes[0] if sizes else "M", "quantity": 1}

        id_re = re.compile(r"\b([A-Z]{2,3}-\d{3})\b")
        for msg in reversed(messages):
            if msg["role"] == "tool" and msg.get("name") == "search_catalog":
                try:
                    data = json.loads(msg["content"])
                except (json.JSONDecodeError, TypeError):
                    data = {}
                if data.get("products"):
                    return _draft(data["products"][0]["id"])
            if msg["role"] == "assistant" and msg.get("content"):
                found = id_re.search(msg["content"])
                if found:
                    draft = _draft(found.group(1))
                    if draft:
                        return draft
        return None

    @staticmethod
    def _answer_from_tool(tool_msg: dict[str, Any]) -> str:
        name = tool_msg.get("name", "")
        try:
            data = json.loads(tool_msg["content"])
        except (json.JSONDecodeError, TypeError):
            return "Done."

        if name == "search_catalog":
            products = data.get("products", [])
            if data.get("faq_answer"):
                return data["faq_answer"]
            if not products:
                return "I couldn't find that in our catalog. Can you tell me the item name?"
            lines = [
                f"- {p['name']} ({p['id']}): ${p['price_usd']} — colors: {', '.join(p['colors'])}"
                for p in products[:3]
            ]
            return "Here's what we have:\n" + "\n".join(lines) + "\n\nWant me to check a size or place an order?"

        if name == "check_stock":
            if data.get("in_stock"):
                sizes = ", ".join(data.get("available_sizes", []))
                return f"Yes, {data['name']} is in stock. Available sizes: {sizes}."
            return f"Sorry, {data.get('name', 'that item')} is out of stock in that size right now."

        if name == "create_order":
            return (
                f"Your order is confirmed ✅ (ref {data.get('order_id')}). "
                f"Total ${data.get('total_usd')}. We'll message you when it ships. Shukran!"
            )

        if name == "handoff_to_human":
            return "I've passed this to a member of our team — they'll reply shortly. 🙏"

        if name == "schedule_followup":
            return "Got it, I'll check back with you later."

        return "Done."

    def transcribe(self, audio_path: str) -> str:  # pragma: no cover - demo only
        return "[mock transcription — set GROQ_API_KEY to transcribe real audio]"


# --------------------------------------------------------------------------- #
_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    """Return the configured client (mock when no key / USE_MOCK_LLM=1)."""
    global _singleton
    if _singleton is None:
        _singleton = MockClient() if config.USE_MOCK_LLM else GroqClient()
    return _singleton


def reset_llm(client: LLMClient | None = None) -> None:
    """Swap the client (used by tests to inject a stub)."""
    global _singleton
    _singleton = client
