"""Cedar Threads — Studio.

One small, nice-looking app that puts everything in a browser UI:

    💬  Live Chat   — talk to the agent in a clean, premium chat
    📊  Dashboard   — the Part B analytics (KPIs, segments, win-back, report)

    pip install -r requirements.txt
    streamlit run studio.py

No WhatsApp, no keys needed — it uses the offline brain unless GROQ_API_KEY is set.
"""
from __future__ import annotations

import html
import time

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import config
from analytics import data as dataload
from analytics import kpis as kpi_mod
from analytics import report as report_mod
from analytics import rfm as rfm_mod
from analytics import topics as topics_mod
from analytics import winback as winback_mod
from app import memory
from app.agent import Agent

DEMO_PHONE = "96170000000"

st.set_page_config(
    page_title="Cedar Threads — Studio",
    page_icon="🧵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
#  Styling — a premium boutique chat (cedar green + gold)                     #
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@600;700&display=swap');

      :root {
        --cedar-900:#0c3b2e; --cedar-700:#1b5e43; --cedar-500:#27724f;
        --gold:#c9a86a; --ink:#1f2937; --muted:#9aa0a6;
        --linen:#faf9f6; --line:#ededed;
      }

      /* Center the conversation and give it room to breathe */
      .chat-wrap { max-width: 760px; margin: 4px auto 0; }

      .chat-card {
        background:#fff; border-radius:22px; border:1px solid #ececec;
        box-shadow:0 24px 70px rgba(17,24,39,.12); overflow:hidden;
      }

      .chat-head {
        display:flex; align-items:center; gap:14px; padding:18px 24px;
        background:linear-gradient(135deg,var(--cedar-900) 0%,var(--cedar-700) 55%,var(--cedar-500) 100%);
        color:#fff;
      }
      .chat-avatar {
        width:48px; height:48px; border-radius:50%;
        background:#f3ead6; color:var(--cedar-700);
        font-family:'Playfair Display',serif; font-weight:700; font-size:21px;
        display:flex; align-items:center; justify-content:center;
        box-shadow:0 0 0 2px var(--gold), 0 0 0 5px rgba(255,255,255,.14);
      }
      .chat-name { font-family:'Playfair Display',serif; font-size:20px; font-weight:700; letter-spacing:.2px; }
      .chat-status { font-size:12.5px; opacity:.9; display:flex; align-items:center; gap:7px; margin-top:2px; }
      .dot { width:8px; height:8px; border-radius:50%; background:#4ade80; animation:pulse 2.2s infinite; }
      @keyframes pulse {
        0%{box-shadow:0 0 0 0 rgba(74,222,128,.6);}
        70%{box-shadow:0 0 0 7px rgba(74,222,128,0);}
        100%{box-shadow:0 0 0 0 rgba(74,222,128,0);}
      }

      .chat-body {
        background:var(--linen); padding:26px 26px 30px; height:520px; overflow-y:auto;
        display:flex; flex-direction:column; gap:16px; font-family:'Inter',sans-serif;
      }
      .chat-body::-webkit-scrollbar { width:8px; }
      .chat-body::-webkit-scrollbar-thumb { background:#e4dfd4; border-radius:8px; }

      .row { display:flex; flex-direction:column; max-width:76%; }
      .row.me  { align-self:flex-end;  align-items:flex-end; }
      .row.bot { align-self:flex-start; align-items:flex-start; }

      .bubble {
        padding:12px 16px; border-radius:18px; font-size:14.5px; line-height:1.55;
        white-space:pre-wrap; word-wrap:break-word;
      }
      .bubble p { margin:0 0 6px; }
      .bubble p:last-child { margin-bottom:0; }
      .bubble ol, .bubble ul { margin:4px 0 2px; padding-left:20px; }
      .row.me .bubble {
        background:linear-gradient(135deg,var(--cedar-700),var(--cedar-900));
        color:#fff; border-bottom-right-radius:5px; box-shadow:0 6px 18px rgba(12,59,46,.24);
      }
      .row.bot .bubble {
        background:#fff; color:var(--ink); border:1px solid var(--line);
        border-bottom-left-radius:5px; box-shadow:0 4px 14px rgba(17,24,39,.06);
      }
      .meta { font-size:11px; color:var(--muted); margin:5px 7px 0; }
      .toolchip {
        display:inline-flex; align-items:center; gap:6px; margin-top:7px;
        font-size:11px; color:var(--cedar-700); background:#eef5f0;
        border:1px solid #dce9e1; padding:3px 10px; border-radius:999px; font-weight:600;
        letter-spacing:.2px;
      }
      .sys-note {
        align-self:center; background:#fff7e6; color:#8a6d1e; border:1px solid #f1e2bf;
        font-size:12px; padding:6px 13px; border-radius:999px; font-family:'Inter',sans-serif;
      }

      /* Sidebar polish */
      .brand-title { font-family:'Playfair Display',serif; font-size:24px; font-weight:700; }
      .brain-pill {
        display:inline-block; padding:4px 12px; border-radius:999px;
        background:#eef5f0; color:var(--cedar-700); font-size:12px; font-weight:600;
        border:1px solid #dce9e1;
      }
      /* Make Streamlit's chat input feel part of the card */
      [data-testid="stChatInput"] { max-width:760px; margin:14px auto 0; }

      /* Dashboard KPI cards */
      .kpi-card {
        background:#fff; border:1px solid #ececec; border-radius:16px;
        padding:16px 18px; box-shadow:0 4px 14px rgba(17,24,39,.05);
        height:100%; font-family:'Inter',sans-serif;
      }
      .kpi-label {
        font-size:11.5px; color:#6b7280; font-weight:700;
        text-transform:uppercase; letter-spacing:.5px;
      }
      .kpi-value {
        font-size:30px; font-weight:700; color:var(--cedar-900);
        line-height:1.1; margin:6px 0 4px;
      }
      .kpi-note { font-size:12px; color:#9aa0a6; line-height:1.45; }
      .sect-note { color:#6b7280; font-size:13px; margin:-2px 0 6px; font-family:'Inter',sans-serif; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
#  Shared helpers                                                             #
# --------------------------------------------------------------------------- #
def brain_label() -> str:
    return f"Groq · {config.LLM_MODEL}" if not config.USE_MOCK_LLM else "offline (mock)"


def _now() -> str:
    return time.strftime("%H:%M")


def get_agent() -> Agent:
    if "agent" not in st.session_state:
        memory.init_db()
        st.session_state.agent = Agent()
    return st.session_state.agent


def reset_chat() -> None:
    memory.init_db()
    try:
        with memory._conn() as c:  # noqa: SLF001 - dev tool
            c.execute("DELETE FROM messages WHERE phone=?", (DEMO_PHONE,))
            c.execute("DELETE FROM customers WHERE phone=?", (DEMO_PHONE,))
    except Exception:  # noqa: BLE001
        pass
    st.session_state.msgs = _greeting()


def _greeting() -> list[dict]:
    return [{
        "role": "bot",
        "text": f"Marhaba! 👋 Welcome to {config.SHOP_NAME}. Ask me about our clothes, "
                "prices, sizes, or delivery — I'm here to help.",
        "tools": [], "note": None, "ts": _now(),
    }]


def send(text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    st.session_state.msgs.append({"role": "me", "text": text, "tools": [], "note": None, "ts": _now()})
    reply = get_agent().handle(DEMO_PHONE, text)
    if reply.muted:
        st.session_state.msgs.append(
            {"role": "note", "text": "This chat is now with a human agent — the assistant is silent.",
             "tools": [], "note": None, "ts": _now()})
        return
    note = "⚠ Handed off to a human teammate" if reply.handed_off else None
    st.session_state.msgs.append(
        {"role": "bot", "text": reply.text or "", "tools": reply.tools_used, "note": note, "ts": _now()})


# --------------------------------------------------------------------------- #
#  Live Chat page                                                             #
# --------------------------------------------------------------------------- #
def page_chat() -> None:
    if "msgs" not in st.session_state:
        st.session_state.msgs = _greeting()

    rows = []
    for m in st.session_state.msgs:
        if m["role"] == "note":
            rows.append(f'<div class="sys-note">{html.escape(m["text"])}</div>')
            continue
        side = "me" if m["role"] == "me" else "bot"
        inner = f'<div class="row {side}"><div class="bubble">{html.escape(m["text"])}</div>'
        if m.get("tools"):
            inner += f'<div class="toolchip">🔧 {", ".join(m["tools"])}</div>'
        inner += f'<div class="meta">{m.get("ts", "")}</div></div>'
        rows.append(inner)
        if m.get("note"):
            rows.append(f'<div class="sys-note">{html.escape(m["note"])}</div>')

    initial = config.SHOP_NAME.strip()[:1].upper() or "C"
    card_html = f"""
    <div class="chat-wrap">
      <div class="chat-card">
        <div class="chat-head">
          <div class="chat-avatar">{initial}</div>
          <div>
            <div class="chat-name">{html.escape(config.SHOP_NAME)}</div>
            <div class="chat-status"><span class="dot"></span> Online · AI concierge</div>
          </div>
        </div>
        <div class="chat-body" id="wa-body">{''.join(rows)}</div>
      </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)

    prompt = st.chat_input("Write a message…")
    if prompt:
        send(prompt)
        st.rerun()

    # Keep the latest message in view.
    components.html(
        "<script>var b=window.parent.document.getElementById('wa-body');"
        "if(b){b.scrollTop=b.scrollHeight;}</script>",
        height=0,
    )


# --------------------------------------------------------------------------- #
#  Dashboard page                                                             #
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner="Crunching the numbers…")
def analyse() -> dict:
    d = dataload.load_all()
    k = kpi_mod.compute(d["events"], d["orders"], d["customers"])
    rfm = rfm_mod.compute(d["orders"])
    seg = rfm_mod.segment_summary(rfm)
    topics = topics_mod.cluster(memory.message_texts("user"))
    wb = winback_mod.targets(d["orders"], d["events"], rfm)
    rep = report_mod.write(k, seg, topics, wb)
    ts = kpi_mod.orders_timeseries(d["orders"], "D")
    return {"d": d, "k": k, "rfm": rfm, "seg": seg, "topics": topics, "wb": wb, "rep": rep, "ts": ts}


def page_dashboard() -> None:
    st.markdown("### 📊 Marketing Insights")
    c1, c2 = st.columns([4, 1])
    c1.caption("Your marketing brain — what the chats and sales reveal about winning and keeping customers.")
    if c2.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    A = analyse()
    k = A["k"]

    if k["total_chats"] == 0 and k["orders_count"] == 0:
        st.warning("No data yet. Run **`python seed_demo.py`** in a terminal to populate "
                   "demo data, then click Refresh — or just chat on the Live Chat page.")
        return

    def card(col, label, value, note):
        col.markdown(
            f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value">{value}</div>'
            f'<div class="kpi-note">{note}</div></div>',
            unsafe_allow_html=True,
        )

    st.subheader("The numbers that matter")
    st.markdown("<div class='sect-note'>Each card says what it means — no marketing jargon.</div>",
                unsafe_allow_html=True)

    r1 = st.columns(3)
    card(r1[0], "Money earned", f"${k['revenue_usd']:,.0f}", "Total sales from all WhatsApp orders.")
    card(r1[1], "Orders placed", k["orders_count"], "How many orders customers completed.")
    card(r1[2], "Chats that bought", f"{k['conversion_rate']*100:.0f}%",
         "Of everyone who messaged, how many actually ordered. Your sales effectiveness.")
    st.write("")
    r2 = st.columns(3)
    card(r2[0], "Avg. spend per order", f"${k['aov_usd']:.0f}", "What a typical order is worth.")
    card(r2[1], "Bought again", f"{k['repeat_rate']*100:.0f}%",
         "Share of buyers who came back for more — your loyalty.")
    card(r2[2], "Going quiet", k["churned_customers"],
         f"Past buyers silent for {kpi_mod.CHURN_DAYS}+ days — at risk of leaving.")
    st.write("")
    r3 = st.columns(3)
    card(r3[0], "People who messaged", k["total_chats"], "Total customers who started a chat.")
    card(r3[1], "Said it's too pricey", f"{k['objection_rate']*100:.0f}%",
         "Chats that pushed back on price (ghali) — a cue for your pricing message.")
    card(r3[2], "Needed a human", f"{k['handoff_rate']*100:.0f}%",
         "Share the AI passed to a teammate — the rest it handled alone.")

    left, right = st.columns(2)
    with left:
        st.subheader("Orders & revenue over time")
        st.markdown("<div class='sect-note'>Busy days vs slow days — the best times to post and run offers.</div>",
                    unsafe_allow_html=True)
        ts = A["ts"]
        if not ts.empty:
            st.bar_chart(ts.set_index("period")[["orders"]])
            st.line_chart(ts.set_index("period")[["revenue"]])
    with right:
        st.subheader("Top products")
        st.markdown("<div class='sect-note'>Your bestsellers — the items to feature in ads and promos.</div>",
                    unsafe_allow_html=True)
        if k["top_products"]:
            tp = pd.DataFrame(k["top_products"]).set_index("product_name")
            st.bar_chart(tp[["revenue"]])
            st.dataframe(tp, use_container_width=True)

    st.subheader("Your customers, grouped")
    st.markdown("<div class='sect-note'>From your best, most-loyal shoppers to the ones slipping away — so you "
                "can treat each group differently. (Champions = top buyers; At Risk / Hibernating = fading.)</div>",
                unsafe_allow_html=True)
    seg = A["seg"]
    if not seg.empty:
        sa, sb = st.columns([1, 1])
        sa.bar_chart(seg.set_index("segment")[["customers"]])
        sb.dataframe(seg, use_container_width=True, hide_index=True)
        with st.expander("See every customer's RFM scores"):
            st.dataframe(A["rfm"], use_container_width=True, hide_index=True)

    st.subheader("What customers ask about")
    st.markdown("<div class='sect-note'>The AI groups every chat by topic, with real quotes — free market "
                "research in your customers' own words.</div>", unsafe_allow_html=True)
    if A["topics"]:
        for t in A["topics"]:
            with st.expander(f"**{t['topic']}** — {t['count']} messages"):
                for q in t.get("quotes", []):
                    st.markdown(f"> {q}")
    else:
        st.caption("No customer messages to analyse yet.")

    st.subheader("🎯 Win-back targets")
    st.markdown("<div class='sect-note'>A ready-made re-engagement list: quiet customers worth a friendly "
                "nudge, most valuable first — each with a suggested message.</div>", unsafe_allow_html=True)
    wb = A["wb"]
    if not wb.empty:
        st.caption(f"{len(wb)} customers worth re-engaging, highest-value first.")
        st.dataframe(wb, use_container_width=True, hide_index=True)
    else:
        st.caption("No win-back targets right now — nobody has lapsed.")

    st.subheader("📝 This week's report")
    st.markdown("<div class='sect-note'>A short plain-English summary and one recommendation — like a mini "
                "marketing consultant reading all your chats for you.</div>", unsafe_allow_html=True)
    st.markdown(A["rep"])


# --------------------------------------------------------------------------- #
#  Shell                                                                      #
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("<div class='brand-title'>🧵 Cedar Threads</div>", unsafe_allow_html=True)
    st.markdown(f"<span class='brain-pill'>brain · {brain_label()}</span>", unsafe_allow_html=True)
    st.write("")
    page = st.radio("View", ["💬 Live Chat", "📊 Dashboard"], label_visibility="collapsed")
    st.divider()
    if page == "💬 Live Chat":
        st.caption("Speaks Arabic, Arabizi, French & English.")
        if st.button("🗑️ Reset conversation", use_container_width=True):
            reset_chat()
            st.rerun()
    st.caption("A WhatsApp AI sales concierge for a small Lebanese clothing house.")

if page == "💬 Live Chat":
    page_chat()
else:
    page_dashboard()
