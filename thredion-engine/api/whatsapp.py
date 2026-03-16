"""
Thredion Engine — WhatsApp Webhook (Twilio)
Handles incoming WhatsApp messages, processes URLs, and replies with AI insights.
"""

import re
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User
from services.pipeline import process_url
from api.routes import notify_change

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

# Regex to extract URLs from messages
URL_PATTERN = re.compile(
    r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.'
    r'[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
)


def _get_or_create_user(phone: str, db: Session) -> User:
    """Find or create a user by WhatsApp phone number.
    Normalises to +E.164 format so it matches the auth JWT subject.
    """
    normalized = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if not normalized.startswith("+"):
        normalized = "+" + normalized
    user = db.query(User).filter(User.phone_number == normalized).first()
    if not user:
        user = User(phone_number=normalized)
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"[WhatsApp] Created new user: {normalized}")
    return user


@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Twilio WhatsApp webhook endpoint.
    Receives incoming messages, extracts URLs, processes them, and replies.
    All memories are written to the *memories* table so they appear on the dashboard.
    """
    try:
        form_data = await request.form()
    except Exception:
        return _twiml_response(_build_help_reply())

    body = form_data.get("Body", "") or ""
    from_number = form_data.get("From", "unknown") or "unknown"

    # Strip the "whatsapp:" prefix Twilio adds
    user_phone = str(from_number).replace("whatsapp:", "").strip() or "unknown"

    # Check for voice media
    voice_url = None
    media_url = form_data.get("MediaUrl0")
    media_content_type = form_data.get("MediaContentType0") or ""
    if media_url and ("audio" in media_content_type or "ogg" in media_content_type):
        voice_url = media_url
        logger.info(f"[WhatsApp] Voice note from {user_phone}: {voice_url}")

    logger.info(f"[WhatsApp] Message from {user_phone}: {body!r}")

    # Short plain text with no URL and no media → help
    urls = URL_PATTERN.findall(body or "")
    if not voice_url and not urls and len((body or "").split()) <= 3:
        return _twiml_response(_build_help_reply())

    # ── Find / create user ────────────────────────────────────
    if user_phone == "unknown":
        return _twiml_response("⚠️ Could not identify your WhatsApp number.")
    try:
        user = _get_or_create_user(user_phone, db)
    except Exception as e:
        logger.error(f"[WhatsApp] User lookup failed: {e}")
        return _twiml_response("⚠️ Account error. Please try again.")

    # ── Process URL → writes to memories table (shown on dashboard) ──
    if urls:
        url = urls[0]
        logger.info(f"[WhatsApp] Processing URL: {url}")
        try:
            result = process_url(url, user.id, db)
            notify_change("memory_added", str(result.get("memory_id", "")))
            if result.get("duplicate"):
                return _twiml_response(_build_duplicate_reply(result))
            return _twiml_response(_build_cognitive_reply(result))
        except Exception as e:
            logger.error(f"[WhatsApp] Pipeline error for {url}: {e}", exc_info=True)
            return _twiml_response("⚠️ Something went wrong processing your link. Please try again.")

    # Voice messages — acknowledge but not yet fully supported in pipeline
    if voice_url:
        return _twiml_response(
            "🎤 Voice note received!\n\n"
            "Full voice transcription is coming soon. "
            "For now, send me a link and I'll save it to your memory vault. 🧠"
        )

    return _twiml_response(_build_help_reply())


@router.get("/webhook")
async def whatsapp_verify():
    """Health check / verification endpoint for Twilio."""
    return PlainTextResponse("Thredion WhatsApp webhook is active ✓")


def _build_duplicate_reply(result: dict) -> str:
    """Build a reply when the URL was already saved."""
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
    """Build a rich WhatsApp reply after processing a cognitive entry."""
    parts = []

    parts.append("✅ *Captured to your memory vault!*")

    # process_url returns 'category'; process_cognitive returns 'bucket'
    bucket_or_cat = result.get("bucket") or result.get("category") or "General"
    parts.append(f"📂 *{bucket_or_cat}*")

    score = result.get("importance_score", 0)
    parts.append(f"⭐ *Importance:* {score}/100")

    parts.append(f"📝 *{result.get('title', 'Untitled')}*")
    parts.append("")
    parts.append(result.get("summary", "Summary not available."))

    return "\n".join(parts)


def _build_help_reply() -> str:
    """Build a help message when no URL is found."""
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
        "• Blog articles\n\n"
        "Just paste a URL and I'll handle the rest! 🚀"
    )


def _importance_bar(score: float) -> str:
    """Create a visual bar for importance score."""
    filled = int(score / 10)
    return "█" * filled + "░" * (10 - filled)


def _twiml_response(message: str, media_url: str = "") -> PlainTextResponse:
    """Wrap reply in TwiML format for Twilio, optionally with a media attachment."""
    media_tag = ""
    if media_url:
        # Twilio supports <Media> inside <Message> for sending images
        media_tag = f"<Media>{_escape_xml(media_url)}</Media>"
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Message>{_escape_xml(message)}{media_tag}</Message>"
        "</Response>"
    )
    return PlainTextResponse(content=twiml, media_type="application/xml")


def _escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
