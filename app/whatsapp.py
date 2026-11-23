"""Thin wrapper over the Meta WhatsApp Cloud API.

Handles the three things we need: send a text reply, resolve a media id to a
download URL, and download the bytes. All calls are no-ops/logged if the token
isn't configured, so importing this never crashes the offline demo.
"""
from __future__ import annotations

import logging
from pathlib import Path

import config

log = logging.getLogger("whatsapp")


def _base() -> str:
    return f"https://graph.facebook.com/{config.GRAPH_API_VERSION}"


def _configured() -> bool:
    return bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID)


def send_text(to: str, body: str) -> dict:
    """Send a plain text WhatsApp message to `to` (E.164, no +)."""
    if not _configured():
        log.info("[whatsapp:dry-run] -> %s: %s", to, body)
        return {"dry_run": True, "to": to, "body": body}

    import httpx

    url = f"{_base()}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    resp = httpx.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def send_template(to: str, template_name: str, params: list[str], language: str = "en") -> dict:
    """Send a pre-approved template message (used for follow-ups)."""
    if not _configured():
        log.info("[whatsapp:dry-run template] -> %s: %s %s", to, template_name, params)
        return {"dry_run": True, "to": to, "template": template_name, "params": params}

    import httpx

    url = f"{_base()}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    components = [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in params],
        }
    ]
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": components,
        },
    }
    resp = httpx.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def download_media(media_id: str, dest_dir: str | Path) -> Path:
    """Resolve a media id and download its bytes. Returns the saved file path."""
    if not _configured():
        raise RuntimeError("WhatsApp token not configured; cannot download media.")

    import httpx

    headers = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}
    meta = httpx.get(f"{_base()}/{media_id}", headers=headers, timeout=30.0)
    meta.raise_for_status()
    info = meta.json()
    media_url = info["url"]
    mime = info.get("mime_type", "audio/ogg")
    ext = {"audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a"}.get(mime, ".ogg")

    blob = httpx.get(media_url, headers=headers, timeout=60.0)
    blob.raise_for_status()

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{media_id}{ext}"
    path.write_bytes(blob.content)
    return path
