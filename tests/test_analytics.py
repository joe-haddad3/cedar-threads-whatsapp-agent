import time

from analytics import data as dataload
from analytics import kpis as kpi_mod
from analytics import rfm as rfm_mod
from analytics import winback as winback_mod
from app import memory, orders, rag
from app.events import E

DAY = 86400


def _seed_small():
    now = time.time()
    # A: chatted, one recent order
    memory.get_or_create_customer("A", "Ann")
    memory.add_event("A", E.CHAT_STARTED, {}, ts=now - DAY)
    memory.add_event("A", E.PRODUCT_ASKED, {}, ts=now - DAY)
    orders.save_order(orders.build_order(phone="A", customer_name="Ann", product=rag.get_product("CAP-001"), size="one-size", quantity=1))
    memory.add_event("A", E.ORDER_PLACED, {"total_usd": 12}, ts=now - DAY)

    # B: chatted, objected, never ordered, quiet 20 days
    memory.get_or_create_customer("B", "Bob")
    memory.add_event("B", E.CHAT_STARTED, {}, ts=now - 20 * DAY)
    memory.add_event("B", E.PRODUCT_ASKED, {}, ts=now - 20 * DAY)
    memory.add_event("B", E.OBJECTION, {}, ts=now - 20 * DAY)
    memory.add_message("B", "user", "ghali ktir")

    # C: chatted, two orders (repeat buyer)
    memory.get_or_create_customer("C", "Cara")
    memory.add_event("C", E.CHAT_STARTED, {}, ts=now - 5 * DAY)
    for _ in range(2):
        orders.save_order(orders.build_order(phone="C", customer_name="Cara", product=rag.get_product("HD-001"), size="M", quantity=1))
    memory.add_event("C", E.ORDER_PLACED, {}, ts=now - 5 * DAY)


def test_kpis_conversion_and_repeat():
    _seed_small()
    d = dataload.load_all()
    k = kpi_mod.compute(d["events"], d["orders"], d["customers"])
    assert k["total_chats"] == 3
    assert k["orders_count"] == 3          # A:1 + C:2
    assert abs(k["conversion_rate"] - 2 / 3) < 0.01   # A and C bought, of 3 chats
    assert abs(k["repeat_rate"] - 0.5) < 0.01         # C repeats, of 2 buyers
    assert k["revenue_usd"] > 0


def test_rfm_segments_buyers_only():
    _seed_small()
    d = dataload.load_all()
    rfm = rfm_mod.compute(d["orders"])
    assert set(rfm["phone"]) == {"A", "C"}            # only buyers
    assert "segment" in rfm.columns


def test_winback_flags_quiet_objector():
    _seed_small()
    d = dataload.load_all()
    rfm = rfm_mod.compute(d["orders"])
    wb = winback_mod.targets(d["orders"], d["events"], rfm)
    assert "B" in set(wb["phone"])                    # warm lead, objected, went quiet


def test_timeseries_has_rows():
    _seed_small()
    d = dataload.load_all()
    ts = kpi_mod.orders_timeseries(d["orders"], "D")
    assert ts["orders"].sum() == 3
