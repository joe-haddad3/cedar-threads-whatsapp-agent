# Cedar Threads — WhatsApp Sales Agent

An AI agent that handles a small Lebanese online clothing shop's WhatsApp
customer chats in **Arabic, English and French**, understands **text and voice
notes**, and never invents a price (it must look everything up with a tool).

It demonstrates the core building blocks of a production agent: **tool use,
RAG (search-before-answer), per-customer memory, scheduled actions, guardrails,
and human handoff.**

> **Runs offline out of the box.** With no API keys, it uses a deterministic
> rule-based "brain" so you can demo it, run the tests, and run the evaluation
> immediately. Add a free Groq key to switch to a real LLM.

---

## 1. Quick start (no keys, 60 seconds)

```bash
cd whatsapp-agent
python -m pip install -r requirements.txt
python chat_cli.py
```

Then type, for example:

```
marhaba
how much is the hoodie?
yes I'll take it
write me a poem        # <- refused: it only talks shop
```

Run the automated checks:

```bash
python -m pytest          # 20 unit/integration tests
python eval/run_eval.py   # scores the agent against the project targets
```

`requirements.txt` is only needed for the **WhatsApp server** and the test
runner. The CLI and the offline brain need nothing but the Python standard
library, so `python chat_cli.py` works even before you `pip install`.

---

## 2. How it works

```
Customer message (text or voice)
        │
        ▼
Meta WhatsApp Cloud API  ──webhook──►  FastAPI server (app/webhook.py)
                                            │
                        voice note? ────────┤ download + transcribe (Whisper)
                                            ▼
                                    Agent loop (app/agent.py)
                                            │  LLM decides: answer or call a tool
                                            ▼
                 ┌─────────────┬────────────┬───────────────┬────────────────┐
             search_catalog  check_stock  create_order  handoff_to_human  schedule_followup
                 │  (RAG over catalog + FAQ)   │ (CSV / Sheets)   │ (mark human)   │ (templates)
                 └─────────────┴────────────┴───────────────┴────────────────┘
                                            │
                                   Guardrails (app/guardrails.py)
                                   • topic lock  • price-leak check
                                            ▼
                                     Reply back on WhatsApp
```

### The five tools (`app/tools.py`)
| Tool | What it does |
|------|--------------|
| `search_catalog` | Searches products **and** FAQ. The only source of prices/details. |
| `check_stock` | Live stock for a product / size. |
| `create_order` | Saves an order — **only after the customer confirms**. Refuses to oversell. |
| `handoff_to_human` | Escalates and mutes the bot for that chat. |
| `schedule_followup` | Queues an approved-template follow-up for a quiet customer. |

### Guardrails (why this passes Meta's rules)
Meta banned general-purpose AI chatbots on WhatsApp Business (Jan 2026), so the
agent must stay strictly on shop business:
- **Topic lock** — off-topic requests (poems, weather, code, news…) are refused
  in EN/FR/AR.
- **Never invent a price** — the model is *never given prices in its prompt*.
  Prices only exist inside tool results, and a **price-leak check** catches any
  `$` figure in a reply that didn't come from a tool or the catalog.
- **Confirm before ordering** — `create_order` is only called after the customer
  confirms item + size + quantity.

### Memory (`app/memory.py`)
SQLite (`memory.db`), keyed by phone number: a customer profile + rolling
message history + a follow-up queue. The agent reloads recent history every
turn, so it remembers people across messages and restarts.

### RAG — Retrieval-Augmented Generation (`app/rag.py`)
The agent never answers product, price, delivery or returns questions from
the LLM's own memory. It **retrieves** the facts first, then the LLM
**generates** the reply from them:

```
Customer: "how much is the hoodie?"
   │
   ▼
1. Retrieve  ── search_catalog tool → rag.search_products() + rag.search_faq()
   │            scans data/catalog.json and data/faq.json
   ▼
2. Augment   ── matching products / FAQ entry are returned to the LLM as a tool result
   │
   ▼
3. Generate  ── the LLM writes the answer using only that retrieved data
   │
   ▼
"The Essential Hoodie is $34 (black, grey, cream). Want me to check your size?"
```

How retrieval works:
- The query and every product/FAQ entry are split into words (Arabic letters included).
- Filler words (`the`, `how`, `combien`, …) are dropped.
- Each entry is scored by how many words it shares with the query; an exact
  name or category match gets a bonus. The top matches are returned.

It is **keyword-based** on purpose: no embedding model to download, so it runs
offline on a slow connection and is easy to explain. For a much larger
catalog you could swap `rag.py` for vector embeddings without touching the rest
of the agent.

Together with the price-leak check, this is what guarantees the bot **never
invents a price**.

---

## 3. Project layout

```
whatsapp-agent/
├─ chat_cli.py          # local tester (no WhatsApp needed)
├─ config.py            # all settings, from .env with safe fallbacks
├─ data/
│  ├─ catalog.json      # products, prices, stock, shop info  ← edit me
│  ├─ faq.json          # delivery / payment / returns / sizing
│  └─ templates.json    # WhatsApp follow-up templates
├─ app/
│  ├─ agent.py          # the decision loop
│  ├─ llm.py            # Groq client + offline MockClient (swappable)
│  ├─ tools.py          # the five tools + JSON schemas
│  ├─ rag.py            # catalog/FAQ retrieval (dependency-free)
│  ├─ guardrails.py     # system prompt, topic lock, price-leak check
│  ├─ memory.py         # per-customer SQLite memory
│  ├─ orders.py         # CSV (default) or Google Sheets
│  ├─ transcription.py  # voice-note → text
│  ├─ whatsapp.py       # Meta Cloud API send/receive
│  ├─ followups.py      # scheduled follow-up worker
│  └─ webhook.py        # FastAPI webhook
├─ tests/               # pytest suite (offline)
└─ eval/                # 17-case eval set + scorer
```

To adapt it to a different shop, **edit `data/catalog.json` and `data/faq.json`**
— no code changes needed.

---

## 4. Switch to a real LLM (Groq free tier)

1. Get a free key at <https://console.groq.com/keys>.
2. `cp .env.example .env` and set `GROQ_API_KEY=...`
3. Run `python chat_cli.py` — it now says `Brain: Groq · llama-3.3-70b-versatile`.

Voice transcription uses Groq Whisper (`whisper-large-v3`) with the same key.

> On a slow connection, installing can stall. If so:
> `set UV_CONCURRENT_DOWNLOADS=1` (or use plain `pip`, which is already the
> default here).

---

## 5. Connect it to WhatsApp (Meta test number + ngrok)

1. Create a Meta developer app and a **WhatsApp** product; note the free **test
   number**, its `PHONE_NUMBER_ID`, and a temporary access token.
2. Put them in `.env`: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
   `WHATSAPP_VERIFY_TOKEN` (any string you choose).
3. Start the server:
   ```bash
   uvicorn app.webhook:app --reload --port 8000
   ```
4. Expose it: `ngrok http 8000`, copy the `https://…ngrok…` URL.
5. In the Meta dashboard → WhatsApp → Configuration, set the **Callback URL** to
   `https://…ngrok…/webhook` and the **Verify token** to your `WHATSAPP_VERIFY_TOKEN`,
   then subscribe to `messages`.
6. Add your own phone as a test recipient and message the test number.

Follow-ups are sent by a worker you run on a schedule (Windows Task Scheduler /
cron):
```bash
python -m app.followups
```

### Orders to Google Sheets (optional)
Default is a local CSV in `orders/`. To use Sheets:
```bash
pip install gspread google-auth
# .env:
ORDER_BACKEND=sheets
GOOGLE_SHEETS_ID=<sheet id>
GOOGLE_SERVICE_ACCOUNT_JSON=<path to service-account.json>
```

---

## 6. Evaluation

`python eval/run_eval.py` runs the conversations in
`eval/conversations.jsonl` and scores them against the brief's targets:

| Metric | Target | Seed-set result |
|--------|--------|-----------------|
| Correct product & price answers | > 90% | 100% |
| Invented prices or products | 0 | 0 |
| Orders extracted correctly | > 85% | 100% |
| Hands off when it should | > 90% | 100% |
| Off-topic requests refused | 100% | 100% |

The seed set is 17 cases so it runs instantly. **Grow it toward the brief's 100
conversations** by adding lines to the `.jsonl` — the scorer needs no changes.
Voice-note accuracy is measured on the same path (transcription → text → agent);
record 10–20 Lebanese voice notes, transcribe them with a real Groq key, and add
the transcripts as `order` / `price` cases.

---

## 6b. Part B — Analytics dashboard (events → insights)

The agent (Part A) records a typed **event** at each step of every conversation
(`chat_started`, `product_asked`, `objection`, `order_placed`, `handoff`, …) into
SQLite. **Part B** reads those events + orders and turns them into business
insights.

```bash
pip install -r requirements.txt
python seed_demo.py          # one-time: populate ~55 demo customers of data
streamlit run dashboard.py   # opens the dashboard in your browser
```

The dashboard shows:
- **KPIs** — revenue, orders, conversion, AOV, repeat rate, churn risk, objection rate (pandas).
- **Trends** — orders & revenue over time, top products.
- **RFM segments** — Champions / Loyal / At Risk / Hibernating… scored from orders (pandas).
- **What customers ask about** — topics clustered from real chat messages, each with **verbatim quotes** (LLM, with a keyword fallback offline).
- **Win-back targets** — a prioritised list of who to re-engage, with a suggested approved template (rules).
- **Written report** — an LLM-written weekly summary + one concrete recommendation (templated fallback offline).

Layout:
```
app/events.py          # typed event logging (Part A → Part B bridge)
analytics/
  data.py              # load events/orders/customers into pandas
  kpis.py  rfm.py  winback.py      # pure-pandas metrics & segments
  topics.py  report.py             # LLM topics (with quotes) + narrative
seed_demo.py           # realistic demo-data generator
dashboard.py           # Streamlit UI
```

Everything except topics/report is pure pandas and runs offline; the two LLM
pieces use Groq when a key is set and fall back to deterministic logic otherwise.

## 7. Maps to the 6-week build plan

| Week | Deliverable | Where it lives |
|------|-------------|----------------|
| 1 | Webhook that echoes messages | `app/webhook.py` |
| 2 | LLM + catalog search tool | `app/llm.py`, `app/rag.py`, `app/tools.py` |
| 3 | Voice notes: download + transcribe | `app/transcription.py`, `app/whatsapp.py` |
| 4 | Memory, orders to Sheets, handoff | `app/memory.py`, `app/orders.py`, `tools.py` |
| 5 | Guardrails, follow-up templates, test set | `app/guardrails.py`, `app/followups.py`, `eval/` |
| 6 | Run the eval, fix failures, demo | `eval/run_eval.py`, `chat_cli.py` |

---

## 8. Cost

Fully free to run: Groq free tier (LLM + Whisper), the free Meta test number,
and your own phones as testers.
