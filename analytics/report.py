"""Write the weekly insights report + a concrete recommendation.

Takes the already-computed KPIs, segments, topics and win-back list, and turns
them into a short owner-facing narrative. Uses the LLM when available; otherwise
produces a clear templated report from the same numbers.
"""
from __future__ import annotations

import config
from app.llm import get_llm


def _facts(kpis: dict, seg_summary, topics: list[dict], winback) -> str:
    seg = "; ".join(f"{r['segment']}: {int(r['customers'])} ({r['revenue']}$)" for _, r in seg_summary.iterrows()) if len(seg_summary) else "n/a"
    tops = ", ".join(f"{t['topic']} ({t['count']})" for t in topics[:5]) or "n/a"
    prods = ", ".join(f"{p['product_name']} ({int(p['orders'])})" for p in kpis.get("top_products", [])[:3]) or "n/a"
    return (
        f"Chats: {kpis['total_chats']}, Orders: {kpis['orders_count']}, "
        f"Revenue: ${kpis['revenue_usd']}, AOV: ${kpis['aov_usd']}, "
        f"Conversion: {kpis['conversion_rate']*100:.0f}%, Repeat: {kpis['repeat_rate']*100:.0f}%, "
        f"Objection rate: {kpis['objection_rate']*100:.0f}%, Churned: {kpis['churned_customers']}. "
        f"Top products: {prods}. Segments: {seg}. Top topics: {tops}. "
        f"Win-back targets: {len(winback)}."
    )


def _templated(kpis: dict, seg_summary, topics: list[dict], winback) -> str:
    conv = kpis["conversion_rate"] * 100
    lines = [
        "## Weekly insights",
        f"- **{kpis['total_chats']} chats** produced **{kpis['orders_count']} orders** "
        f"(**{conv:.0f}% conversion**) for **${kpis['revenue_usd']:.0f}** revenue, AOV **${kpis['aov_usd']:.0f}**.",
        f"- **{kpis['repeat_rate']*100:.0f}%** of buyers are repeat customers; **{kpis['churned_customers']}** have gone quiet (churn risk).",
        f"- **{kpis['objection_rate']*100:.0f}%** of chats raised a price objection.",
    ]
    if topics:
        lines.append(f"- Customers most ask about: **{topics[0]['topic']}**" + (f" and **{topics[1]['topic']}**" if len(topics) > 1 else "") + ".")
    lines.append("")
    lines.append("## Recommendation")
    if conv < 30 and kpis["objection_rate"] > 0.25:
        rec = "Price objections are costing conversions — test a small bundle or free-delivery nudge for first-time buyers."
    elif kpis["churned_customers"] >= 3:
        rec = f"Run a win-back to the **{len(winback)}** flagged customers this week — prioritise the lapsed high-value buyers."
    elif kpis["repeat_rate"] < 0.2:
        rec = "Repeat rate is low — a post-purchase check-in and a 'back in stock' nudge could lift it."
    else:
        rec = f"Momentum is healthy — focus follow-ups on the **{len(winback)}** win-back targets to recover revenue."
    lines.append(f"- {rec}")
    return "\n".join(lines)


def write(kpis: dict, seg_summary, topics: list[dict], winback) -> str:
    if config.USE_MOCK_LLM:
        return _templated(kpis, seg_summary, topics, winback)
    try:
        facts = _facts(kpis, seg_summary, topics, winback)
        prompt = (
            "You are a retail analyst for a small Lebanese clothing shop. Based ONLY on these "
            "facts, write a short weekly report in markdown: a '## Weekly insights' section "
            "(3-5 bullet points, concrete numbers) and a '## Recommendation' section with ONE "
            "specific, actionable recommendation. Do not invent numbers.\n\nFacts: " + facts
        )
        resp = get_llm().chat([{"role": "user", "content": prompt}], tools=None)
        return (resp.content or "").strip() or _templated(kpis, seg_summary, topics, winback)
    except Exception:
        return _templated(kpis, seg_summary, topics, winback)
