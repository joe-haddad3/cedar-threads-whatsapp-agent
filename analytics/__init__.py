"""Part B — the analytics / insights layer.

Reads the events + orders that Part A (the agent) records, and turns them into
KPIs, RFM segments, chat topics and a written report. Pure-pandas where it can
be (KPIs, RFM, win-back); the LLM is used only for topic clustering and the
narrative report.
"""
