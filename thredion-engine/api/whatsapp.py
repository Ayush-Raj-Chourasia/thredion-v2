"""
Thredion Engine — WhatsApp Webhook (Twilio)

IMPORTANT: Twilio webhooks time out after 15 seconds.
The cognitive pipeline (extract -> LLM -> embed -> DB) takes 30-60 s.

Pattern used here:
    1. Parse request -> return immediate TwiML "Got it, processing..."
    2. Kick off pipeline in a background thread (own DB session)
    3. When done, push the full result back via Twilio REST API
"""

import re
import logging
import threading

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from core.config import settings
from db.database import SessionLocal
from db.models import User
from services.pipeline import process_url
from api.routes import notify_change

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

URL_PATTERN = re.compile(
    r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.'
    r'[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
)


# ── Twilio outbound ───────────────────────────────────────────

def _send_whatsapp(to: str, body: str) -> None:
    """Send a proactive WhatsApp message via Twilio REST API."""
    try:
        from twilio.rest import Client
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN
                and settings.TWILIO_WHATSAPP_NUMBER):
            logger.warning("[WhatsApp] Twilio credentials missing — cannot send reply")
            return
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        from_num = settings.TWILIO_WHATSAPP_NUMBER
        if not from_num.startswith("whatsapp:"):
            from_num = f"whatsapp:{from_num}"
        to_num = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
        client.messages.create(body=body, from_=from_num, to=to_num)
        logger.info(f"[WhatsApp] Follow-up sent to {to}")
    except Exception as exc:
        logger.error(f"[WhatsApp] Failed to send follow-up to {to}: {exc}")


# ── Phone normalisation ───────────────────────────────────────

def _normalize_phone(raw: str) -> str:
    phone = raw.replace("whatsapp:", "").strip()
    phone = re.sub(r"[\s\-\(\)]", "", phone)
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def _get_or_create_user(phone: str) -> User:
    """Find or create user; uses its own session so it's thread-safe."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.phone_number == phone).first()
        if not user:
            user = User(phone_number=phone)
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"[WhatsApp] Created new user: {phone}")
        return user
    finally:
        db.close()


# ── Background pipeline ───────────────────────────────────────

def _run_pipeline_background(url: str, user_phone: str) -> None:
    """
    Runs in a background thread with its own DB session.
    Sends the full result back via Twilio REST API when done.
    """
    from db.database import init_db
    init_db()
    db = SessionLocal()
    try:
        user = _get_or_create_user(user_phone)
        result = process_url(url, user.id, db)
        notify_change("memory_added", str(result.get("memory_id", "")))

        if result.get("duplicate"):
            reply = _build_duplicate_reply(result)
        else:
            reply = _build_cognitive_reply(result)

        _send_whatsapp(user_phone, reply)
    except Exception as exc:
        logger.error(f"[WhatsApp BG] Pipeline failed for {url}: {exc}", exc_info=True)
        _send_whatsapp(
            user_phone,
            f"⚠️ Something went wrong processing your link.\n\n"
            f"Details: {str(exc)[:200]}\n\n"
            "Please try again with the same link."
        )
    finally:
        db.close()


# ── Webhook endpoint ──────────────────────────────────────────

@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    """
    Twilio WhatsApp webhook.
    Always returns TwiML within ~1 s (beats Twilio 15 s timeout).
    The heavy pipeline runs in a background thread and
    replies to the user via Twilio REST API when finished.
    """
    logger.info("[WhatsApp] Webhook hit")

    try:
        form_data = await request.form()
    except Exception:
        return _twiml_response(_build_help_reply())

    body = str(form_data.get("Body", "") or "").strip()
    from_raw = str(form_data.get("From", "") or "")

    # Twilio status-callback POSTs have no From field
    if not from_raw:
        return _twiml_empty()

    user_phone = _normalize_phone(from_raw)
    logger.info(f"[WhatsApp] From={user_phone!r}  Body={body!r}")
    # Audio / voice note
    media_content_type = str(form_data.get("MediaContentType0", "") or "")
    if form_data.get("MediaUrl0") and (
        "audio" in media_content_type or "ogg" in media_content_type
    ):
        return _twiml_response(
            "🎤 Voice note received!\n"
            "Voice transcription is coming soon. "
            "For now, send me a link to save it. 🧠"
        )

    urls = URL_PATTERN.findall(body)

    # No URL + short message → help
    if not urls and len(body.split()) <= 3:
        return _twiml_response(_build_help_reply())

    # URL found → start background thread, ACK Twilio immediately
    if urls:
        url = urls[0]
        logger.info(f"[WhatsApp] Launching background pipeline for: {url}")
        threading.Thread(
            target=_run_pipeline_background,
            args=(url, user_phone),
            daemon=True,
        ).start()
        return _twiml_response(
            "⏳ Got your link! Analyzing it now...\n\n"
            "You'll receive a full summary in a few seconds. 🧠"
        )

    return _twiml_response(_build_help_reply())


@router.get("/webhook")
async def whatsapp_verify():
    """Health check / verification endpoint for Twilio."""
    return PlainTextResponse("Thredion WhatsApp webhook is active ✓")


# ── Reply builders ────────────────────────────────────────────

def _build_duplicate_reply(result: dict) -> str:
    summary = result.get("summary", "")
    category = result.get("category", "")
    score = result.get("importance_score", 0)
    return (
        "🔁 *Already in your memory vault!*\n\n"
        f"📝 *Summary:* {summary}\n"
        f"🏷️ *Category:* {category}\n"
        f"⭐ *Importance:* {score}/100\n\n"
        "This link was previously saved. No duplicate created."
    )


def _build_cognitive_reply(result: dict) -> str:
    parts = ["✅ *Saved to your memory vault!*"]
    bucket_or_cat = result.get("bucket") or result.get("category") or "General"
    parts.append(f"📂 *{bucket_or_cat}*")
    score = result.get("importance_score", 0)
    parts.append(f"⭐ *Importance:* {score}/100")
    parts.append(f"📝 *{result.get('title', 'Untitled')}*")
    parts.append("")
    parts.append(result.get("summary", "Summary not available."))
    connections = result.get("connections") or []
    if connections:
        parts.append(f"\n🔗 Connected to {len(connections)} related memory(ies)")
    return "\n".join(parts)


def _build_help_reply() -> str:
    return (
        "🧠 *Thredion — AI Cognitive Memory Engine*\n\n"
        "Send me a link and I'll:\n"
        "• 📝 Summarize it with AI\n"
        "• 🏷️ Auto-categorize it\n"
        "• 🔗 Connect it to related memories\n"
        "• ⭐ Score its importance\n"
        "• 💡 Resurface forgotten insights\n\n"
        "Supported:\n"
        "• Instagram reels/posts\n"
        "• Twitter/X posts\n"
        "• YouTube videos\n"
        "• Blog articles & websites\n\n"
        "Just paste a URL and I'll handle the rest! 🚀"
    )


# ── TwiML helpers ─────────────────────────────────────────────

def _twiml_response(message: str) -> PlainTextResponse:
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Message>{_escape_xml(message)}</Message>"
        "</Response>"
    )
    return PlainTextResponse(content=twiml, media_type="application/xml")


def _twiml_empty() -> PlainTextResponse:
    return PlainTextResponse(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml",
    )


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
