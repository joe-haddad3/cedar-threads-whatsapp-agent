"""The agent: the decision loop that turns a customer message into a reply.

Flow per turn:
    1. Remember the customer; store the incoming message.
    2. If the chat is already with a human, stay muted.
    3. Topic guard: refuse general-purpose requests (WhatsApp compliance).
    4. Run the LLM <-> tool loop until the model produces a final reply.
    5. Price-leak guard: make sure no un-sourced price slipped into the reply.
    6. Store and return the reply.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import json

import config
from app import events, guardrails, memory, tools
from app.events import E
from app.llm import LLMClient, get_llm

MAX_TOOL_ITERS = 5


@dataclass
class Reply:
    text: str | None
    muted: bool = False            # True when a human has taken over
    handed_off: bool = False       # True when THIS turn escalated
    tools_used: list[str] = field(default_factory=list)


class Agent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        memory.init_db()
        self.llm = llm or get_llm()

    def handle(self, phone: str, text: str, name: str | None = None) -> Reply:
        is_new_chat = not memory.history(phone, limit=1)
        customer = memory.get_or_create_customer(phone, name)
        memory.add_message(phone, "user", text)

        if is_new_chat:
            events.log(phone, E.CHAT_STARTED)
        if events.looks_like_objection(text):
            events.log(phone, E.OBJECTION, text=text[:120])

        # A human has taken this conversation over — the bot stays silent.
        if customer["status"] == "human":
            return Reply(text=None, muted=True)

        # Topic lock.
        on_topic, refusal = guardrails.is_on_topic(text, has_order_context=len(
            memory.history(phone)) > 2)
        if not on_topic:
            events.log(phone, E.OFFTOPIC_REFUSED, text=text[:120])
            memory.add_message(phone, "assistant", refusal)
            return Reply(text=refusal)

        ctx = tools.ToolContext(phone=phone, customer_name=customer.get("name"))
        script = guardrails.detect_script(text)
        messages = [
            {
                "role": "system",
                "content": guardrails.build_system_prompt(customer.get("name"), script),
            },
            *memory.history(phone),
        ]

        tool_results: list[str] = []
        used: list[str] = []
        handed_off = False

        for _ in range(MAX_TOOL_ITERS):
            resp = self.llm.chat(messages, tools.TOOL_SCHEMAS)

            if not resp.tool_calls:
                reply_text = resp.content or "Sorry, can you rephrase that?"
                break

            # Record the assistant's tool-call turn (OpenAI message shape).
            messages.append(
                {
                    "role": "assistant",
                    "content": resp.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": _dumps(tc.arguments)},
                        }
                        for tc in resp.tool_calls
                    ],
                }
            )

            for tc in resp.tool_calls:
                used.append(tc.name)
                result = tools.execute_tool(tc.name, tc.arguments, ctx)
                tool_results.append(result)
                self._log_tool_event(phone, tc.name, result)
                if tc.name == "handoff_to_human":
                    handed_off = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": result,
                    }
                )
        else:
            # Ran out of iterations without a final text answer.
            reply_text = "Let me get a teammate to help you with this. 🙏"
            handed_off = True
            tools.handoff_to_human(ctx, "tool loop did not converge")

        # Price-leak guard: if the model stated a price we can't trace to a tool
        # result, don't send it. Instead, rebuild a correct answer from the
        # catalog data we already fetched, so the customer still gets a real,
        # accurate reply (never a dead end).
        clean, leaked = guardrails.check_price_leak(reply_text, tool_results)
        if not clean:
            reply_text = _safe_answer_from_tools(tool_results)

        # If the customer wrote in Latin letters, keep the reply fully Latin.
        reply_text = guardrails.enforce_reply_script(reply_text, script)

        memory.add_message(phone, "assistant", reply_text)
        if handed_off:
            memory.set_status(phone, "human")
        return Reply(text=reply_text, handed_off=handed_off, tools_used=used)

    @staticmethod
    def _log_tool_event(phone: str, tool_name: str, result: str) -> None:
        """Translate a tool call + its result into an analytics event."""
        try:
            data = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            data = {}
        if tool_name == "search_catalog":
            events.log(phone, E.PRODUCT_ASKED)
        elif tool_name == "check_stock":
            events.log(phone, E.STOCK_CHECKED)
        elif tool_name == "create_order" and data.get("ok"):
            events.log(
                phone,
                E.ORDER_PLACED,
                order_id=data.get("order_id"),
                product_id=data.get("product_id"),
                total_usd=data.get("total_usd"),
            )
        elif tool_name == "handoff_to_human":
            events.log(phone, E.HANDOFF, reason=data.get("reason"))
        elif tool_name == "schedule_followup" and data.get("ok"):
            events.log(phone, E.FOLLOWUP_SCHEDULED, template=data.get("template"))


def _dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def _safe_answer_from_tools(tool_results: list[str]) -> str:
    """Build a correct, price-safe reply straight from the catalog tool results.

    Used when the price-leak guard rejects the model's wording. Every price here
    comes directly from a search_catalog result, so it is always accurate.
    """
    import json

    seen: set[str] = set()
    products: list[dict] = []
    for raw in tool_results:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for p in data.get("products") or []:
            if p.get("id") and p["id"] not in seen:
                seen.add(p["id"])
                products.append(p)

    if products:
        lines = [
            f"- {p['name']}: ${p['price_usd']} ({', '.join(p.get('colors', []))})"
            for p in products[:5]
        ]
        return (
            "Here's what we have:\n"
            + "\n".join(lines)
            + "\n\nWant me to check a size or place an order?"
        )

    # No product data to fall back on — ask rather than guess a price.
    return (
        "Let me pull up the exact price for you — which item are you asking about? "
        "I'll look it up right away. 🙂"
    )
