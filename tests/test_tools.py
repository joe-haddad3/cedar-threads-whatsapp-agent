import json

from app import rag
from app.tools import (
    ToolContext,
    check_stock,
    create_order,
    execute_tool,
    handoff_to_human,
    schedule_followup,
    search_catalog,
)


def test_search_catalog_finds_hoodie_with_price():
    result = search_catalog("hoodie price")
    ids = [p["id"] for p in result["products"]]
    assert "HD-001" in ids
    hoodie = next(p for p in result["products"] if p["id"] == "HD-001")
    assert hoodie["price_usd"] == 34  # price comes only from the catalog


def test_search_catalog_returns_faq_for_delivery():
    result = search_catalog("how long is delivery to tripoli")
    assert "faq_answer" in result
    assert "deliver" in result["faq_answer"].lower()


def test_check_stock_known_size_in_stock():
    out = check_stock(product_id="HD-001", size="M")
    assert out["in_stock"] is True
    assert out["quantity"] > 0


def test_check_stock_sold_out_size():
    out = check_stock(product_id="TS-001", size="XXL")  # XXL = 0 in catalog
    assert out["in_stock"] is False


def test_create_order_persists_and_totals():
    ctx = ToolContext(phone="9617111", customer_name="Rami")
    out = create_order(ctx, product_id="CAP-001", size="one-size", quantity=2)
    assert out["ok"] is True
    cap = rag.get_product("CAP-001")
    assert out["total_usd"] == cap["price_usd"] * 2
    assert out["order_id"].startswith("CT-")


def test_create_order_rejects_oversell():
    ctx = ToolContext(phone="9617222")
    out = create_order(ctx, product_id="TS-001", size="XXL", quantity=1)
    assert out["ok"] is False
    assert out["error"] == "insufficient_stock"


def test_handoff_sets_human_status():
    from app import memory

    ctx = ToolContext(phone="9617333")
    memory.get_or_create_customer("9617333")
    out = handoff_to_human(ctx, reason="angry customer")
    assert out["status"] == "handed_off"
    assert memory.get_or_create_customer("9617333")["status"] == "human"


def test_schedule_followup_stored():
    ctx = ToolContext(phone="9617444")
    out = schedule_followup(ctx, template="abandoned_cart", detail="Essential Hoodie", after_hours=1)
    assert out["ok"] is True
    assert out["followup_id"] >= 1


def test_execute_tool_returns_json_string():
    ctx = ToolContext(phone="9617555")
    raw = execute_tool("search_catalog", {"query": "cap"}, ctx)
    assert isinstance(raw, str)
    assert json.loads(raw)["products"]
