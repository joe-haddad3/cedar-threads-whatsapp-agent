"""FastAPI server for the Meta WhatsApp webhook.

    GET  /webhook  -> verification handshake (Meta calls this once).
    POST /webhook  -> incoming messages (text + voice notes).
    GET  /health   -> liveness probe.

Run it with:  uvicorn app.webhook:app --reload --port 8000
Then expose it with ngrok and paste the https URL into the Meta dashboard.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response

import config
from app import whatsapp
from app.agent import Agent
from app.transcription import transcribe_media

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook")

app = FastAPI(title=f"{config.SHOP_NAME} WhatsApp Agent")
agent = Agent()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "shop": config.SHOP_NAME, "mock_llm": config.USE_MOCK_LLM}


@app.get("/webhook")
def verify(request: Request) -> Response:
    """Meta's verification handshake."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    if mode == "subscribe" and token == config.WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="verification failed", status_code=403)


@app.post("/webhook")
async def receive(request: Request) -> dict:
    """Handle an incoming message event."""
    body = await request.json()
    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = value.get("contacts", [])
                name = None
                if contacts:
                    name = contacts[0].get("profile", {}).get("name")
                for msg in value.get("messages", []):
                    _handle_message(msg, name)
    except Exception:  # never 500 back to Meta — it will retry forever
        log.exception("error handling webhook event")
    return {"status": "received"}


def _handle_message(msg: dict, name: str | None) -> None:
    phone = msg.get("from")
    mtype = msg.get("type")

    if mtype == "text":
        text = msg["text"]["body"]
    elif mtype == "audio":
        media_id = msg["audio"]["id"]
        log.info("transcribing voice note %s", media_id)
        text = transcribe_media(media_id)
    else:
        whatsapp.send_text(
            phone, "I can read text and voice notes. Could you send one of those? 🙂"
        )
        return

    reply = agent.handle(phone, text, name=name)
    if reply.muted:
        log.info("chat with %s is in human mode; bot staying silent", phone)
        return
    if reply.text:
        whatsapp.send_text(phone, reply.text)
    if reply.handed_off:
        log.info("conversation %s handed off to a human", phone)
