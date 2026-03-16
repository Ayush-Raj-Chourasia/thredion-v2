"""
Thredion Engine — WhatsApp Webhook (Twilio)
Handles incoming WhatsApp messages, processes URLs, and replies with AI insights.
"""

import re
import logging

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from db.database import get_db
from app.services.pipeline import process_incoming
from api.routes import notify_change

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

# Regex to extract URLs from messages
URL_PATTERN = re.compile(
    r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.'
    r'[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
)


@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Twilio WhatsApp webhook endpoint.
    Receives incoming messages, extracts URLs, processes them, and replies.
    """
    # Parse form data from Twilio
    try:
        form_data = await request.form()
    except Exception:
        return _twiml_response(_build_help_reply())
    body = form_data.get("Body", "") or ""
    from_number = form_data.get("From", "unknown") or "unknown"
    
    # Clear phone number
    user_phone = str(from_number).replace("whatsapp:", "").strip() or "unknown"
    
    # Check for voice media
    voice_url = None
    media_url = form_data.get("MediaUrl0")
    media_content_type = form_data.get("MediaContentType0")
    
    if media_url and ("audio" in media_content_type or "ogg" in media_content_type):
        voice_url = media_url
        logger.info(f"[WhatsApp] Voice note from {user_phone}: {voice_url}")
    
    logger.info(f"[WhatsApp] Message from {user_phone}: {body}")

    # For short plain text without URL/media, keep legacy help response behavior.
    if not voice_url and not URL_PATTERN.search(body or "") and len((body or "").split()) <= 3:
        return _twiml_response(_build_help_reply())

    # Process via the new pipeline
    try:
        result = await process_incoming(
            phone_number=user_phone,
            message_text=body,
            voice_file_url=voice_url
        )
        
        if result.get("processing_status") == "failed":
            return _twiml_response("⚠️ Something went wrong, but I've saved your raw input.")
        
        reply = _build_cognitive_reply(result)
        return _twiml_response(reply)
        
    except Exception as e:
        logger.error(f"[WhatsApp] Pipeline error: {e}")
        return _twiml_response("⚠️ Exception occurred during processing. Raw input saved.")


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
    
    parts.append("✅ *Captured!*")
    parts.append(f"📂 *{result.get('bucket', 'General')}*")
    
    mode_icon = {"learn": "📚", "think": "💡", "reflect": "🪞"}.get(result.get("cognitive_mode", "learn"), "🧠")
    parts.append(f"{mode_icon} *{result.get('cognitive_mode', 'learn').capitalize()}*")
    
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
