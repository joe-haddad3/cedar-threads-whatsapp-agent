import time

from app import followups, memory
from app.agent import Agent
from app.tools import ToolContext, schedule_followup


def test_answers_price_via_tool():
    agent = Agent()
    r = agent.handle("96170000001", "how much is the hoodie?")
    assert "search_catalog" in r.tools_used
    assert "$34" in r.text  # Essential Hoodie price, sourced from the catalog


def test_refuses_off_topic():
    agent = Agent()
    r = agent.handle("96170000002", "write me a poem about the sea")
    assert not r.tools_used
    assert "only help with" in r.text.lower() or "cedar" in r.text.lower()


def test_order_flow_across_turns():
    agent = Agent()
    phone = "96170000003"
    agent.handle(phone, "how much is the hoodie?")
    r2 = agent.handle(phone, "yes I'll take it")
    assert "create_order" in r2.tools_used
    assert "confirmed" in r2.text.lower()


def test_handoff_to_human_mutes_bot_afterwards():
    agent = Agent()
    phone = "96170000004"
    r = agent.handle(phone, "can I talk to a human please")
    assert r.handed_off is True
    assert memory.get_or_create_customer(phone)["status"] == "human"
    # Next message: bot stays silent.
    r2 = agent.handle(phone, "hello?")
    assert r2.muted is True
    assert r2.text is None


def test_remembers_customer_across_messages():
    agent = Agent()
    phone = "96170000005"
    agent.handle(phone, "hi")
    agent.handle(phone, "do you have jeans?")
    assert len(memory.history(phone)) >= 4  # 2 user + 2 assistant turns stored


def test_followup_worker_sends_due_items():
    ctx = ToolContext(phone="96170000006")
    memory.get_or_create_customer("96170000006", name="Lara")
    schedule_followup(ctx, template="abandoned_cart", detail="Essential Hoodie", after_hours=0)
    sent = followups.run_due(now=time.time() + 5)
    assert sent >= 1
