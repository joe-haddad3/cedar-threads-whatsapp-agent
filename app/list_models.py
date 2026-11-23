"""Print the chat models your Groq key can use.

    python -m app.list_models

Groq retires model ids periodically, so if you get a 404 from the API, run this
to find a current one and set LLM_MODEL in your .env.
"""
from __future__ import annotations

import config


def main() -> None:
    if not config.GROQ_API_KEY:
        print("No GROQ_API_KEY set in .env — nothing to list (running in mock mode).")
        return

    import httpx

    resp = httpx.get(
        config.GROQ_BASE_URL + "/models",
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    ids = sorted(m["id"] for m in resp.json().get("data", []))

    skip = ("whisper", "tts", "guard", "embed", "orpheus")
    print("Chat-capable models for your key:\n")
    for mid in ids:
        if not any(s in mid.lower() for s in skip):
            marker = "  <- current LLM_MODEL" if mid == config.LLM_MODEL else ""
            print(f"  {mid}{marker}")
    print("\nSet one in .env as:  LLM_MODEL=<id>")


if __name__ == "__main__":
    main()
