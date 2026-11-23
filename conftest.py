"""Shared pytest setup.

Lives at the project root so `import config` / `from app import ...` resolve.
Every test gets a throwaway SQLite DB and orders dir, and the offline mock
brain, so the whole suite runs with no network and no keys.
"""
import pytest

import config
from app import memory
from app.llm import MockClient, reset_llm


@pytest.fixture(autouse=True)
def fresh_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ORDERS_DIR", tmp_path)
    monkeypatch.setattr(config, "USE_MOCK_LLM", True)
    # Keep tests hermetic: never touch the real WhatsApp API (dry-run mode).
    monkeypatch.setattr(config, "WHATSAPP_TOKEN", "")
    monkeypatch.setattr(config, "WHATSAPP_PHONE_NUMBER_ID", "")
    reset_llm(MockClient())
    memory.init_db()
    yield
    reset_llm(None)
