"""Central configuration, loaded from environment variables (.env).

Nothing here is secret by default — real keys live in a local .env file that is
git-ignored. Every setting has a safe fallback so the project boots even with an
empty .env, which is what lets `chat_cli.py` and the test suite run offline.
"""
from __future__ import annotations

import os
from pathlib import Path

def _load_env_file(path: Path) -> None:
    """Minimal .env loader so the file is read even without python-dotenv."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


# Prefer python-dotenv when present; always run the fallback too (it only fills
# in anything dotenv missed, e.g. when run from a different working directory).
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass
_load_env_file(Path(__file__).resolve().parent / ".env")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ORDERS_DIR = BASE_DIR / "orders"
ORDERS_DIR.mkdir(exist_ok=True)


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# --- LLM (Groq free tier, OpenAI-compatible API) -------------------------------
GROQ_API_KEY = _get("GROQ_API_KEY")
GROQ_BASE_URL = _get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = _get("LLM_MODEL", "openai/gpt-oss-120b")
WHISPER_MODEL = _get("WHISPER_MODEL", "whisper-large-v3")
LLM_TEMPERATURE = float(_get("LLM_TEMPERATURE", "0.2"))

# When no key is present (or USE_MOCK_LLM=1), the agent uses a deterministic
# rule-based stand-in so you can demo and test without network access.
USE_MOCK_LLM = _get("USE_MOCK_LLM", "0") == "1" or not GROQ_API_KEY

# --- WhatsApp / Meta Cloud API -------------------------------------------------
WHATSAPP_TOKEN = _get("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = _get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = _get("WHATSAPP_VERIFY_TOKEN", "cedar-threads-verify")
GRAPH_API_VERSION = _get("GRAPH_API_VERSION", "v21.0")

# --- Orders --------------------------------------------------------------------
# "csv" (default, zero-setup) or "sheets" (needs gspread + a service account).
ORDER_BACKEND = _get("ORDER_BACKEND", "csv")
GOOGLE_SHEETS_ID = _get("GOOGLE_SHEETS_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = _get("GOOGLE_SERVICE_ACCOUNT_JSON")

# --- Storage -------------------------------------------------------------------
DB_PATH = _get("DB_PATH", str(BASE_DIR / "memory.db"))

# --- Business rules ------------------------------------------------------------
SHOP_NAME = _get("SHOP_NAME", "Cedar Threads")
# How long a chat can be quiet before a follow-up is eligible (hours).
FOLLOWUP_AFTER_HOURS = float(_get("FOLLOWUP_AFTER_HOURS", "24"))
