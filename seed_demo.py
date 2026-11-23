"""Generate realistic demo data for the Part B analytics dashboard.

Creates a population of customers with backdated conversations, typed events,
representative messages (for topic clustering) and orders, so the KPIs, RFM
segments, topics and win-back lists all have real signal to show.

    python seed_demo.py            # reset + seed ~55 customers over ~45 days

It RESETS the local demo database and order files first (both are git-ignored),
so the dashboard shows a clean, coherent picture. Deterministic (fixed seed).
"""
from __future__ import annotations

import random
import time
from pathlib import Path

import config
from app import memory, orders, rag
from app.events import E

random.seed(42)
DAY = 86400
NOW = time.time()

FIRST_NAMES = [
    "Rami", "Lara", "Joe", "Nour", "Karim", "Maya", "Elie", "Rana", "Ziad",
    "Hiba", "Tarek", "Yara", "Fadi", "Dana", "Marwan", "Carla", "Sami", "Jana",
    "Bilal", "Reem", "Georges", "Nadine", "Hadi", "Lea", "Omar", "Tala",
]

# Representative customer messages per intent — feed the topic clustering.
MSG_BANK = {
    "price": [
        "addesh el hoodie?", "how much is the denim jacket?", "combien pour la robe?",
        "2addesh se3r el jeans?", "price of the cedar cap please", "shu se3r el cargo pants?",
    ],
    "sizing": [
        "fi 3andkon size L bl hoodie?", "do you have the tee in XL?",
        "quelle taille pour moi si je fais du M?", "size 32 available bl jeans?",
    ],
    "delivery": [
        "kam el delivery la Tripoli?", "do you deliver to Saida?",
        "combien de temps pour la livraison?", "free delivery fi?",
    ],
    "colors": [
        "shu alwan el tee?", "what colors for the hoodie?", "fi lon aswad?",
    ],
    "objection": [
        "ghali ktir :(", "$34 is a lot for a hoodie", "c'est un peu cher",
        "fi chi discount? ghalye shwar", "2addesh ktir hal se3r",
    ],
    "payment": [
        "bi2dar edfa3 OMT?", "can I pay cash on delivery?", "do you take whish?",
    ],
    "complaint": [
        "my order never arrived, baddi 7aki ma3 7ada",
        "the size was wrong, I want to exchange", "ma wsalne l order, where is it?",
    ],
}

PRODUCTS = [p["id"] for p in rag.all_products()]


def _reset() -> None:
    memory.init_db()
    with memory._conn() as c:  # noqa: SLF001
        for t in ("events", "messages", "customers", "followups"):
            c.execute(f"DELETE FROM {t}")
    for f in ("orders.csv", "orders.jsonl"):
        p = Path(config.ORDERS_DIR) / f
        if p.exists():
            p.unlink()


def _insert_customer(phone, name, created_at, status="bot"):
    with memory._conn() as c:  # noqa: SLF001
        c.execute(
            "INSERT OR REPLACE INTO customers (phone, name, status, created_at, last_seen) VALUES (?,?,?,?,?)",
            (phone, name, status, created_at, created_at),
        )


def _msg(phone, role, content, ts):
    with memory._conn() as c:  # noqa: SLF001
        c.execute(
            "INSERT INTO messages (phone, role, content, ts) VALUES (?,?,?,?)",
            (phone, role, content, ts),
        )


def _order(phone, name, product, size, qty, created_at):
    o = orders.build_order(phone=phone, customer_name=name, product=product, size=size, quantity=qty)
    o["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_at))
    orders.save_order(o)
    return o


def seed() -> dict:
    _reset()
    n_customers = 55
    stats = {"customers": 0, "orders": 0, "events": 0}

    for i in range(n_customers):
        name = random.choice(FIRST_NAMES)
        phone = "961" + random.choice(["70", "71", "76", "78", "79", "03", "81"]) + f"{random.randint(100000, 999999)}"
        first_seen = NOW - random.randint(1, 45) * DAY - random.randint(0, DAY)
        _insert_customer(phone, name, first_seen)
        stats["customers"] += 1

        memory.add_event(phone, E.CHAT_STARTED, {}, ts=first_seen)
        stats["events"] += 1
        t = first_seen + random.randint(30, 600)

        # Everyone asks about something -> product_asked + a representative message.
        intents = ["price"]
        intents += random.sample(["sizing", "delivery", "colors", "payment"], k=random.randint(0, 2))
        for intent in intents:
            _msg(phone, "user", random.choice(MSG_BANK[intent]), t)
            memory.add_event(phone, E.PRODUCT_ASKED if intent in ("price", "colors") else E.STOCK_CHECKED, {}, ts=t)
            stats["events"] += 1
            t += random.randint(20, 300)

        # ~35% raise a price objection.
        objected = random.random() < 0.35
        if objected:
            _msg(phone, "user", random.choice(MSG_BANK["objection"]), t)
            memory.add_event(phone, E.OBJECTION, {}, ts=t)
            stats["events"] += 1
            t += random.randint(20, 300)

        # Conversion: objectors convert less. Base ~45%, objectors ~20%.
        converts = random.random() < (0.20 if objected else 0.48)
        n_orders = 0
        if converts:
            n_orders = random.choices([1, 2, 3], weights=[70, 22, 8])[0]
            ot = t
            for _ in range(n_orders):
                prod = rag.get_product(random.choice(PRODUCTS))
                size = random.choice([s for s, q in prod["variants"].items() if q > 0] or ["M"])
                qty = random.choices([1, 2], weights=[80, 20])[0]
                o = _order(phone, name, prod, size, qty, ot)
                memory.add_event(phone, E.ORDER_PLACED, {"order_id": o["order_id"], "product_id": prod["id"], "total_usd": o["total_usd"]}, ts=ot)
                stats["events"] += 1
                stats["orders"] += 1
                ot += random.randint(2, 20) * DAY  # repeat purchases spread out

        # ~8% complaint -> handoff; ~6% off-topic refusal; ~15% quiet -> follow-up.
        r = random.random()
        if r < 0.08:
            _msg(phone, "user", random.choice(MSG_BANK["complaint"]), t)
            memory.add_event(phone, E.HANDOFF, {"reason": "complaint"}, ts=t)
            _insert_customer(phone, name, first_seen, status="human")
            stats["events"] += 1
        elif r < 0.14:
            memory.add_event(phone, E.OFFTOPIC_REFUSED, {}, ts=t)
            stats["events"] += 1
        if not converts and random.random() < 0.4:
            memory.add_event(phone, E.FOLLOWUP_SCHEDULED, {"template": "quiet_checkin"}, ts=t)
            stats["events"] += 1

    return stats


if __name__ == "__main__":
    s = seed()
    print(f"Seeded demo data into {config.DB_PATH}")
    print(f"  customers: {s['customers']}  orders: {s['orders']}  events: {s['events']}")
    print("Now run:  streamlit run dashboard.py")
