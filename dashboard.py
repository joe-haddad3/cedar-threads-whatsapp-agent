"""Part B — Streamlit analytics dashboard for Cedar Threads.

Reads the events + orders the agent recorded and shows KPIs, orders over time,
RFM segments, what customers ask about (with real quotes), a prioritised
win-back list, and an LLM-written report + recommendation.

    pip install -r requirements.txt
    python seed_demo.py          # one-time: populate demo data
    streamlit run dashboard.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from analytics import data as dataload
from analytics import kpis as kpi_mod
from analytics import report as report_mod
from analytics import rfm as rfm_mod
from analytics import topics as topics_mod
from analytics import winback as winback_mod
from app import memory

st.set_page_config(page_title="Cedar Threads — Insights", page_icon="📊", layout="wide")


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


st.title("📊 Cedar Threads — Customer Insights")
brain = "Groq · " + config.LLM_MODEL if not config.USE_MOCK_LLM else "offline (mock)"
c1, c2 = st.columns([4, 1])
c1.caption(f"Part B analytics · brain: {brain}")
if c2.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

A = analyse()
k = A["k"]

if k["total_chats"] == 0 and k["orders_count"] == 0:
    st.warning("No data yet. Run **`python seed_demo.py`** to populate demo data, then Refresh.")
    st.stop()

# ---- KPI tiles --------------------------------------------------------------
st.subheader("Headline KPIs")
cols = st.columns(6)
cols[0].metric("Revenue", f"${k['revenue_usd']:,.0f}")
cols[1].metric("Orders", k["orders_count"])
cols[2].metric("Conversion", f"{k['conversion_rate']*100:.0f}%")
cols[3].metric("AOV", f"${k['aov_usd']:.0f}")
cols[4].metric("Repeat rate", f"{k['repeat_rate']*100:.0f}%")
cols[5].metric("Churn risk", k["churned_customers"], help=f"Buyers quiet >{kpi_mod.CHURN_DAYS} days")

cols = st.columns(3)
cols[0].metric("Total chats", k["total_chats"])
cols[1].metric("Price objections", f"{k['objection_rate']*100:.0f}%", help="Share of chats that pushed back on price")
cols[2].metric("Handed to human", f"{k['handoff_rate']*100:.0f}%")

# ---- Trend + top products ---------------------------------------------------
left, right = st.columns(2)
with left:
    st.subheader("Orders & revenue over time")
    ts = A["ts"]
    if not ts.empty:
        st.bar_chart(ts.set_index("period")[["orders"]])
        st.line_chart(ts.set_index("period")[["revenue"]])
with right:
    st.subheader("Top products")
    if k["top_products"]:
        tp = pd.DataFrame(k["top_products"]).set_index("product_name")
        st.bar_chart(tp[["revenue"]])
        st.dataframe(tp, use_container_width=True)

# ---- RFM segments -----------------------------------------------------------
st.subheader("Customer segments (RFM)")
seg = A["seg"]
if not seg.empty:
    sa, sb = st.columns([1, 1])
    sa.bar_chart(seg.set_index("segment")[["customers"]])
    sb.dataframe(seg, use_container_width=True, hide_index=True)
    with st.expander("See every customer's RFM scores"):
        st.dataframe(A["rfm"], use_container_width=True, hide_index=True)

# ---- Topics with quotes -----------------------------------------------------
st.subheader("What customers ask about")
if A["topics"]:
    for t in A["topics"]:
        with st.expander(f"**{t['topic']}** — {t['count']} messages"):
            for q in t.get("quotes", []):
                st.markdown(f"> {q}")
else:
    st.caption("No customer messages to analyse yet.")

# ---- Win-back ---------------------------------------------------------------
st.subheader("🎯 Win-back targets")
wb = A["wb"]
if not wb.empty:
    st.caption(f"{len(wb)} customers worth re-engaging, highest-value first. Each has a suggested approved template.")
    st.dataframe(wb, use_container_width=True, hide_index=True)
else:
    st.caption("No win-back targets right now — nobody has lapsed.")

# ---- Written report ---------------------------------------------------------
st.subheader("📝 This week's report")
st.markdown(A["rep"])
