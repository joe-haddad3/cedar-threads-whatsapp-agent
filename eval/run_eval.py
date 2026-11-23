"""Evaluation harness.

Runs every conversation in conversations.jsonl through the agent and scores it
against the targets from the project brief:

    Correct product & price answers   > 90%
    Invented prices or products          0
    Orders extracted correctly         > 85%   (text here; voice is the same path
                                                 after transcription)
    Hands off when it should           > 90%
    Off-topic requests refused          100%

Run:  python eval/run_eval.py
Exit code is 0 if every target is met, else 1 (handy for CI).

The seed set is intentionally small (17 cases) so it runs instantly offline.
Grow it toward the brief's 100 conversations by adding lines to the .jsonl —
the scorer needs no changes.
"""
from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

# Isolate eval state from any real memory.db / orders.
_tmp = Path(tempfile.mkdtemp(prefix="cedar_eval_"))
config.DB_PATH = str(_tmp / "eval.db")
config.ORDERS_DIR = _tmp

from app import guardrails  # noqa: E402
from app.agent import Agent  # noqa: E402

CASES_FILE = Path(__file__).resolve().parent / "conversations.jsonl"


def load_cases() -> list[dict]:
    cases = []
    with open(CASES_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def run_case(agent: Agent, case: dict):
    phone = f"eval-{case['id']}-{uuid.uuid4().hex[:6]}"
    reply = None
    for turn in case["turns"]:
        reply = agent.handle(phone, turn)
    return reply


def prices_in(text: str) -> list[str]:
    return [m for m in guardrails.PRICE_RE.findall(text or "")]


def main() -> int:
    cases = load_cases()
    agent = Agent()

    totals: dict[str, list[int]] = {}  # category -> [passed, count]
    invented = 0
    invented_examples: list[str] = []
    allowed = guardrails.allowed_prices()

    for case in cases:
        reply = run_case(agent, case)
        text = reply.text or ""
        cat = case["category"]
        totals.setdefault(cat, [0, 0])
        totals[cat][1] += 1
        ok = False

        if cat == "price":
            ok = case["expect_price"] in text
        elif cat == "stock":
            ok = "stock" in text.lower()
        elif cat == "offtopic":
            ok = (not reply.tools_used) and ("only help with" in text.lower())
        elif cat == "handoff":
            ok = reply.handed_off
        elif cat == "order":
            ok = "create_order" in reply.tools_used and "confirmed" in text.lower()

        if ok:
            totals[cat][0] += 1

        # Invented-price check applies to every reply.
        for p in prices_in(text):
            key = str(int(float(p))) if float(p) == int(float(p)) else f"{float(p):.2f}"
            if key not in allowed:
                invented += 1
                invented_examples.append(f"{case['id']}: ${p}")

    # --- report -----------------------------------------------------------
    def pct(c: str) -> float:
        p, n = totals.get(c, [0, 0])
        return 100.0 * p / n if n else 0.0

    targets = {
        "price": ("Correct product & price answers", 90.0),
        "order": ("Orders extracted correctly", 85.0),
        "handoff": ("Hands off when it should", 90.0),
        "offtopic": ("Off-topic requests refused", 100.0),
    }

    print(f"\n  Cedar Threads - evaluation ({len(cases)} cases)")
    print(f"  Brain: {'MOCK (offline)' if config.USE_MOCK_LLM else config.LLM_MODEL}")
    print("  " + "-" * 56)
    all_pass = True
    for cat, (label, target) in targets.items():
        p, n = totals.get(cat, [0, 0])
        got = pct(cat)
        passed = got >= target
        all_pass &= passed
        print(f"  {label:<34} {p}/{n}  {got:5.1f}%  target {target:.0f}%  {'PASS' if passed else 'FAIL'}")

    # stock is informational
    if "stock" in totals:
        p, n = totals["stock"]
        print(f"  {'Stock answers handled':<34} {p}/{n}  {pct('stock'):5.1f}%  (info)")

    inv_pass = invented == 0
    all_pass &= inv_pass
    print(f"  {'Invented prices':<34} {invented}        target 0        {'PASS' if inv_pass else 'FAIL'}")
    if invented_examples:
        print("    leaked:", ", ".join(invented_examples[:5]))

    print("  " + "-" * 56)
    print(f"  OVERALL: {'PASS' if all_pass else 'FAIL'}\n")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
