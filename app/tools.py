"""The agent's tools.

Five tools, exactly as the brief specifies:
    search_catalog, check_stock, create_order, handoff_to_human, schedule_followup

Each tool has (a) an OpenAI-format JSON schema the LLM sees, and (b) a Python
implementation. `execute_tool` dispatches by name and always returns a JSON
string (that is what gets fed back to the model as the tool result).

Design rule that enforces the "never invent a price" guarantee: prices and
stock ONLY ever come out of these functions, which read from rag.py. The model
is never given prices in the prompt, so the only way a price reaches the
customer is through a tool result.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import config
from app import memory, orders, rag


@dataclass
class ToolContext:
    """Who we're talking to. Injected per turn so tools know the customer."""

    phone: str
    customer_name: str | None = None


# --------------------------------------------------------------------------- #
# Schemas advertised to the LLM                                               #
# --------------------------------------------------------------------------- #
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": (
                "Search the shop catalog and FAQ. Use this for ANY question about "
                "products, prices, colors, delivery, payment, returns or sizing. "
                "Never state a price or product detail without calling this first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What the customer is asking about, e.g. 'hoodie price' or 'delivery to Tripoli'.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": "Check whether a product is in stock, optionally for a specific size.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "Catalog id like 'HD-001' if known."},
                    "query": {"type": "string", "description": "Free-text product name if the id is unknown."},
                    "size": {"type": "string", "description": "Requested size, e.g. 'M' or '32'."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": (
                "Save an order. ONLY call this AFTER the customer has clearly "
                "confirmed the item, size and quantity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "size": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1},
                    "customer_name": {"type": "string"},
                },
                "required": ["product_id", "size", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_human",
            "description": (
                "Escalate the conversation to a human agent. Use when the customer "
                "is upset, asks for a person, has a complaint/return dispute, or "
                "asks something you cannot handle."
            ),
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_followup",
            "description": (
                "Schedule a WhatsApp follow-up for a customer who went quiet or "
                "wanted to be notified (e.g. restock, abandoned cart)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "template": {
                        "type": "string",
                        "enum": ["abandoned_cart", "back_in_stock", "quiet_checkin"],
                    },
                    "detail": {"type": "string", "description": "Item or context for the message."},
                    "after_hours": {"type": "number", "description": "Delay before sending, in hours."},
                },
                "required": ["template", "detail"],
            },
        },
    },
]


# --------------------------------------------------------------------------- #
# Implementations                                                             #
# --------------------------------------------------------------------------- #
def _public_product(p: dict[str, Any]) -> dict[str, Any]:
    available = [size for size, qty in p["variants"].items() if qty > 0]
    return {
        "id": p["id"],
        "name": p["name"],
        "category": p["category"],
        "price_usd": p["price_usd"],
        "colors": p["colors"],
        "available_sizes": available,
    }


def search_catalog(query: str) -> dict[str, Any]:
    products = [_public_product(p) for p in rag.search_products(query)]
    result: dict[str, Any] = {"products": products, "shop": rag.shop_info()}
    # Only fall back to an FAQ answer when the query didn't match a product,
    # so "how much is the hoodie?" returns the hoodie, not the delivery FAQ.
    if not products:
        faq = rag.search_faq(query)
        if faq:
            result["faq_answer"] = faq["a"]
    return result


def check_stock(product_id: str | None = None, query: str | None = None, size: str | None = None) -> dict[str, Any]:
    product = rag.get_product(product_id) if product_id else None
    if product is None and query:
        hits = rag.search_products(query, limit=1)
        product = hits[0] if hits else None
    if product is None:
        return {"found": False, "message": "No matching product."}

    variants = product["variants"]
    available_sizes = [s for s, q in variants.items() if q > 0]
    if size:
        qty = variants.get(size) or variants.get(size.upper()) or variants.get(size.lower()) or 0
        return {
            "found": True,
            "id": product["id"],
            "name": product["name"],
            "size": size,
            "in_stock": qty > 0,
            "quantity": qty,
            "available_sizes": available_sizes,
        }
    return {
        "found": True,
        "id": product["id"],
        "name": product["name"],
        "in_stock": bool(available_sizes),
        "available_sizes": available_sizes,
    }


def create_order(
    ctx: ToolContext,
    product_id: str,
    size: str,
    quantity: int = 1,
    customer_name: str | None = None,
) -> dict[str, Any]:
    product = rag.get_product(product_id)
    if product is None:
        return {"ok": False, "error": f"Unknown product {product_id!r}."}

    # Guard: never sell what isn't there.
    qty_in_stock = product["variants"].get(size) or product["variants"].get(size.upper()) or 0
    if qty_in_stock < quantity:
        return {
            "ok": False,
            "error": "insufficient_stock",
            "available_sizes": [s for s, q in product["variants"].items() if q > 0],
            "message": f"Only {qty_in_stock} of size {size} left.",
        }

    if customer_name:
        memory.set_name(ctx.phone, customer_name)

    order = orders.build_order(
        phone=ctx.phone,
        customer_name=customer_name or ctx.customer_name,
        product=product,
        size=size,
        quantity=quantity,
    )
    orders.save_order(order)
    return {"ok": True, **order}


def handoff_to_human(ctx: ToolContext, reason: str) -> dict[str, Any]:
    memory.set_status(ctx.phone, "human")
    return {
        "ok": True,
        "status": "handed_off",
        "reason": reason,
        "message": "A human agent has been notified.",
    }


def schedule_followup(
    ctx: ToolContext, template: str, detail: str, after_hours: float | None = None
) -> dict[str, Any]:
    after = after_hours if after_hours is not None else config.FOLLOWUP_AFTER_HOURS
    due_at = time.time() + after * 3600
    fid = memory.add_followup(ctx.phone, template, detail, due_at)
    return {"ok": True, "followup_id": fid, "template": template, "after_hours": after}


# --------------------------------------------------------------------------- #
# Dispatch                                                                    #
# --------------------------------------------------------------------------- #
# Tools that need to know the customer get the context injected.
_NEEDS_CTX = {"create_order", "handoff_to_human", "schedule_followup"}


def execute_tool(name: str, arguments: dict[str, Any], ctx: ToolContext) -> str:
    """Run a tool by name and return its result as a JSON string."""
    try:
        if name == "search_catalog":
            result = search_catalog(**arguments)
        elif name == "check_stock":
            result = check_stock(**arguments)
        elif name in _NEEDS_CTX:
            func = {
                "create_order": create_order,
                "handoff_to_human": handoff_to_human,
                "schedule_followup": schedule_followup,
            }[name]
            result = func(ctx, **arguments)
        else:
            result = {"error": f"Unknown tool {name!r}"}
    except TypeError as exc:
        result = {"error": f"Bad arguments for {name}: {exc}"}
    return json.dumps(result, ensure_ascii=False)
