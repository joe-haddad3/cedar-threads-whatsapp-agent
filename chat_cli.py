"""Local command-line tester for the Cedar Threads agent.

Talk to the agent in your terminal exactly as a WhatsApp customer would — no
Meta, no ngrok, no keys required (it uses the offline mock brain unless you set
GROQ_API_KEY in .env).

    python chat_cli.py

Commands:
    /voice <path>   transcribe an audio file and send it as your message
    /phone <number> switch to a different customer (new memory)
    /reset          forget this customer's history
    /quit           exit
"""
from __future__ import annotations

import sys

import config
from app import memory
from app.agent import Agent
from app.transcription import transcribe_file

DEMO_PHONE = "96170000000"


def main() -> None:
    agent = Agent()
    phone = DEMO_PHONE
    mode = "MOCK (offline)" if config.USE_MOCK_LLM else f"Groq · {config.LLM_MODEL}"

    print("=" * 60)
    print(f"  {config.SHOP_NAME} — WhatsApp agent (CLI tester)")
    print(f"  Brain: {mode}")
    print(f"  Customer: {phone}")
    print("  Type a message, or /quit. Try: 'how much is the hoodie?'")
    print("=" * 60)

    while True:
        try:
            text = input(f"\n[{phone}] you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye 👋")
            return

        if not text:
            continue
        if text == "/quit":
            print("bye 👋")
            return
        if text == "/reset":
            memory.init_db()
            with memory._conn() as c:  # noqa: SLF001 - fine for a dev tool
                c.execute("DELETE FROM messages WHERE phone=?", (phone,))
                c.execute("DELETE FROM customers WHERE phone=?", (phone,))
            print("(history cleared)")
            continue
        if text.startswith("/phone "):
            phone = text.split(" ", 1)[1].strip()
            print(f"(switched to {phone})")
            continue
        if text.startswith("/voice "):
            path = text.split(" ", 1)[1].strip().strip('"')
            try:
                text = transcribe_file(path)
                print(f"[transcribed] {text}")
            except Exception as exc:  # noqa: BLE001
                print(f"(could not transcribe: {exc})")
                continue

        reply = agent.handle(phone, text)
        if reply.muted:
            print("  bot > (silent — this chat is with a human agent)")
            continue
        tag = f"  [tools: {', '.join(reply.tools_used)}]" if reply.tools_used else ""
        print(f"  bot > {reply.text}{tag}")
        if reply.handed_off:
            print("  (⚠ handed off to a human)")


if __name__ == "__main__":
    sys.exit(main())
