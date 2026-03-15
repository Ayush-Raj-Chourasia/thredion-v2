"""
Thredion Engine — Smart Resurfacing Engine
Intelligently resurfaces forgotten memories when contextually relevant.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from core.config import settings
from db.models import Memory, ResurfacedMemory, User
from services.embeddings import embedding_to_vector, cosine_similarity

logger = logging.getLogger(__name__)


def find_resurfaceable(new_memory: Memory, db: Session) -> list[dict]:
    """
    When a new memory is saved, find old memories that should be resurfaced.

    Resurfacing criteria:
    1. Similarity above threshold
    2. Not recently resurfaced (cooldown: 7 days)
    3. Old enough to be "forgotten" (at least 3 days old)
    4. Not the same URL
    """
    if not new_memory.embedding:
        return []

    new_vec = embedding_to_vector(new_memory.embedding)
    if new_vec is None:
        return []

    # Get old memories (at least 3 days old) belonging to the same user
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    old_memories = (
        db.query(Memory)
        .filter(Memory.id != new_memory.id)
        .filter(Memory.user_id == new_memory.user_id)
        .filter(Memory.source_url != new_memory.source_url)
        .filter(Memory.embedding.isnot(None))
        .filter(Memory.created_at < cutoff)
        .all()
    )

    if not old_memories:
        # For demo: if no old memories, use all other memories for this user
        old_memories = (
            db.query(Memory)
            .filter(Memory.id != new_memory.id)
            .filter(Memory.user_id == new_memory.user_id)
            .filter(Memory.source_url != new_memory.source_url)
            .filter(Memory.embedding.isnot(None))
            .all()
        )

    resurfaced = []

    for memory in old_memories:
        # Check cooldown
        recent = (
            db.query(ResurfacedMemory)
            .filter(ResurfacedMemory.memory_id == memory.id)
            .filter(
                ResurfacedMemory.created_at > datetime.now(timezone.utc) - timedelta(days=7)
            )
            .first()
        )
        if recent:
            continue

        old_vec = embedding_to_vector(memory.embedding)
        if old_vec is None:
            continue

        sim = cosine_similarity(new_vec, old_vec)

        if sim >= settings.RESURFACING_THRESHOLD:
            # Create resurfacing record
            reason = _build_reason(new_memory, memory, sim)
            resurface = ResurfacedMemory(
                user_id=new_memory.user_id,
                memory_id=memory.id,
                triggered_by_id=new_memory.id,
                reason=reason,
                similarity_score=round(sim, 4),
            )
            db.add(resurface)

            resurfaced.append({
                "memory_id": memory.id,
                "memory_title": memory.title or memory.summary[:50],
                "memory_summary": memory.summary,
                "memory_category": memory.category,
                "memory_url": memory.url,
                "reason": reason,
                "similarity_score": round(sim, 4),
            })

    if resurfaced:
        db.commit()
        logger.info(
            f"Resurfaced {len(resurfaced)} memories triggered by memory {new_memory.id}"
        )

    return resurfaced


def _build_reason(new_memory: Memory, old_memory: Memory, similarity: float) -> str:
    """Build a human-readable reason for why a memory was resurfaced."""
    reasons = []

    # Same category?
    if new_memory.category == old_memory.category:
        reasons.append(f"Both are about {new_memory.category}")

    # Calculate age
    if old_memory.created_at:
        age = datetime.now(timezone.utc) - old_memory.created_at.replace(tzinfo=timezone.utc)
        days = age.days
        if days > 0:
            reasons.append(f"Saved {days} day{'s' if days != 1 else ''} ago")

    # Similarity
    pct = int(similarity * 100)
    reasons.append(f"{pct}% semantic similarity")

    if not reasons:
        reasons.append("Related content detected")

    return " · ".join(reasons)


def get_recent_resurfaced(db: Session, limit: int = 20, user_id=None) -> list[dict]:
    """Get recently resurfaced memories for the dashboard, scoped to a user."""
    q = db.query(ResurfacedMemory)
    if user_id:
        # Only resurfaced entries whose memory belongs to this user
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            q = q.filter(ResurfacedMemory.user_id == user.id)
    records = (
        q.order_by(ResurfacedMemory.created_at.desc())
        .limit(limit)
        .all()
    )

    results = []
    for r in records:
        memory = db.query(Memory).filter(Memory.id == r.memory_id).first()
        triggered = db.query(Memory).filter(Memory.id == r.triggered_by_id).first()

        if memory and triggered:
            results.append({
                "id": r.id,
                "memory_id": memory.id,
                "memory_title": memory.title or memory.summary[:50],
                "memory_summary": memory.summary,
                "memory_category": memory.category,
                "memory_url": memory.url,
                "triggered_by_id": triggered.id,
                "triggered_by_title": triggered.title or triggered.summary[:50],
                "reason": r.reason,
                "similarity_score": r.similarity_score,
                "created_at": (r.created_at.isoformat() + "Z") if r.created_at else "",
            })

    return results
