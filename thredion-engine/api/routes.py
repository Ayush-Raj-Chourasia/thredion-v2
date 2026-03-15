"""
Thredion Engine — REST API Routes
Endpoints for the cognitive dashboard and manual interactions.
All endpoints require JWT authentication and scope data by user phone.
"""

import asyncio
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.database import get_db
from db.models import Memory, Connection, ResurfacedMemory, User
from services.pipeline import process_url
from services.knowledge_graph import get_full_graph, get_memory_connections
from services.resurfacing import get_recent_resurfaced
from api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["memories"])

# ── SSE Event Bus ─────────────────────────────────────────────
# Simple in-process pub/sub for server-sent events

_sse_subscribers: list[asyncio.Queue] = []


def notify_change(event_type: str = "update", data: str = ""):
    """Broadcast a change event to all SSE subscribers."""
    payload = json.dumps({"type": event_type, "data": data})
    dead = []
    for q in _sse_subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _sse_subscribers.remove(q)


async def _sse_generator(queue: asyncio.Queue):
    """Yield SSE-formatted events from the queue."""
    try:
        while True:
            payload = await asyncio.wait_for(queue.get(), timeout=30)
            yield f"data: {payload}\n\n"
    except asyncio.TimeoutError:
        # Send a keep-alive comment to prevent connection timeout
        yield ": keepalive\n\n"
    except asyncio.CancelledError:
        return


async def _sse_stream(queue: asyncio.Queue):
    """Infinite SSE stream with keep-alive."""
    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=25)
                yield f"data: {payload}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    except asyncio.CancelledError:
        return
    finally:
        if queue in _sse_subscribers:
            _sse_subscribers.remove(queue)


@router.get("/events")
async def sse_events(token: str = Query("", description="JWT token for auth")):
    """Server-Sent Events endpoint for real-time dashboard updates.
    Accepts JWT token as query param since EventSource doesn't support headers.
    """
    # Validate token (but don't block if empty — just for auth'd SSE)
    if token:
        from api.auth import _decode_token
        try:
            _decode_token(token)
        except Exception:
            pass  # Allow connection, just won't filter

    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_subscribers.append(queue)
    return StreamingResponse(
        _sse_stream(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Memories ──────────────────────────────────────────────────


@router.get("/memories")
def list_memories(
    search: str = Query("", description="Search term"),
    category: str = Query("", description="Filter by category"),
    sort: str = Query("newest", description="Sort: newest, oldest, importance"),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all memories for the authenticated user."""
    query = db.query(Memory).filter(Memory.user_id == user.id)

    if search:
        term = f"%{search}%"
        query = query.filter(
            Memory.title.ilike(term)
            | Memory.summary.ilike(term)
            | Memory.content.ilike(term)
            | Memory.category.ilike(term)
            | Memory.tags.ilike(term)
        )

    if category:
        query = query.filter(Memory.category == category)

    if sort == "oldest":
        query = query.order_by(Memory.created_at.asc())
    elif sort == "importance":
        query = query.order_by(Memory.importance_score.desc())
    else:
        query = query.order_by(Memory.created_at.desc())

    memories = query.limit(limit).all()

    return [_serialize_memory(m) for m in memories]


@router.get("/memories/{memory_id}")
def get_memory(memory_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get a single memory with its connections (owned by current user)."""
    memory = db.query(Memory).filter(Memory.id == memory_id, Memory.user_id == user.id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    result = _serialize_memory(memory)
    result["connections"] = get_memory_connections(memory_id, db)
    return result


@router.post("/memories")
def create_memory(
    url: str = Query(..., description="URL to save"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually add a new memory via URL (scoped to authenticated user)."""
    url = url.strip()
    if not re.match(r'^https?://', url):
        raise HTTPException(status_code=400, detail="Invalid URL — must start with http:// or https://")
    try:
        result = process_url(url, user.phone, db)
        notify_change("memory_added", str(result.get("memory_id", "")))
        return result
    except Exception as e:
        logger.error(f"Memory creation failed for {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Creation failed: {str(e)}")


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a memory owned by the current user."""
    memory = db.query(Memory).filter(Memory.id == memory_id, Memory.user_id == user.id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    # Delete related connections (both directions)
    db.query(Connection).filter(
        (Connection.source_id == memory_id) | (Connection.target_id == memory_id)
    ).delete(synchronize_session=False)
    # Delete related resurfaced entries
    db.query(ResurfacedMemory).filter(
        (ResurfacedMemory.memory_id == memory_id) | (ResurfacedMemory.triggered_by_id == memory_id)
    ).delete(synchronize_session=False)
    db.delete(memory)
    db.commit()
    notify_change("memory_deleted", str(memory_id))
    return {"detail": "Memory deleted", "id": memory_id}


# ── Process Endpoint ──────────────────────────────────────────


@router.post("/process")
def process_endpoint(
    url: str = Query(..., description="URL to process"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Process a URL through the full cognitive pipeline."""
    url = url.strip()
    if not re.match(r'^https?://', url):
        raise HTTPException(status_code=400, detail="Invalid URL — must start with http:// or https://")
    try:
        result = process_url(url, user.phone, db)
        notify_change("memory_added", str(result.get("memory_id", "")))
        return result
    except Exception as e:
        logger.error(f"Pipeline error for {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.post("/process-video")
async def process_video_endpoint(
    url: str = Query(..., description="Video URL to process"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Process a VIDEO URL with transcription.
    Handles both short (instant) and long (async) videos.
    """
    from services.pipeline import process_video_url_async
    
    url = url.strip()
    if not re.match(r'^https?://', url):
        raise HTTPException(status_code=400, detail="Invalid URL — must start with http:// or https://")
    
    try:
        result = await process_video_url_async(url, user.phone, db)
        
        if result.get('status') == 'completed':
            notify_change("memory_added", str(result.get("memory_id", "")))
        elif result.get('status') == 'processing':
            notify_change("job_queued", result.get("job_id", ""))
        
        return result
    except Exception as e:
        logger.error(f"Video pipeline error for {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


# ── Cognitive Pipeline Endpoints ──────────────────────────────


class BatchRequest(BaseModel):
    urls: list[str]


class CognitiveRequest(BaseModel):
    url: str


@router.post("/process-cognitive")
async def process_cognitive_endpoint(
    req: CognitiveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Process a single URL through the FULL cognitive pipeline:
    extract -> download audio -> transcribe -> LLM structure -> save.
    """
    from services.cognitive_pipeline import process_cognitive_entry
    
    url = req.url.strip()
    if not re.match(r'^https?://', url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    
    try:
        # Get user's existing buckets for better LLM bucketing
        existing_buckets = _get_user_buckets(user.id, db)
        
        entry = await process_cognitive_entry(url, user.phone, db, existing_buckets)
        
        # Save to database
        memory = _save_cognitive_entry(entry, user.phone, db)
        notify_change("memory_added", str(memory.id))
        
        return {
            "success": entry.success,
            "memory_id": memory.id,
            "title": entry.title,
            "content_quality": entry.content_quality,
            "cognitive_mode": entry.cognitive_mode,
            "bucket": entry.bucket,
            "summary": entry.summary,
            "key_points": entry.key_points,
            "tags": entry.tags,
            "content_length": len(entry.content),
            "transcript_length": len(entry.transcript) if entry.transcript else 0,
            "extraction_time_ms": entry.extraction_time_ms,
        }
    except Exception as e:
        logger.error(f"Cognitive pipeline error for {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.post("/process-batch")
async def process_batch_endpoint(
    req: BatchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Process multiple URLs through the cognitive pipeline.
    Handles the scenario: user forwards 10-20 Instagram reels.
    
    - Max 20 URLs per batch
    - Per-platform rate limiting
    - Deduplicates identical URLs
    - Returns grouped summary
    """
    from services.cognitive_pipeline import process_batch
    
    urls = [u.strip() for u in req.urls if u.strip() and re.match(r'^https?://', u.strip())]
    
    if not urls:
        raise HTTPException(status_code=400, detail="No valid URLs provided")
    
    if len(urls) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 URLs per batch")
    
    try:
        existing_buckets = _get_user_buckets(user.id, db)
        
        entries = await process_batch(urls, user.phone, db, existing_buckets)
        
        # Save all entries to database
        results = []
        for entry in entries:
            try:
                memory = _save_cognitive_entry(entry, user.phone, db)
                results.append({
                    "url": entry.url,
                    "success": entry.success,
                    "memory_id": memory.id,
                    "title": entry.title,
                    "content_quality": entry.content_quality,
                    "cognitive_mode": entry.cognitive_mode,
                    "bucket": entry.bucket,
                    "summary": entry.summary,
                })
                notify_change("memory_added", str(memory.id))
            except Exception as e:
                results.append({
                    "url": entry.url,
                    "success": False,
                    "error": str(e),
                })
        
        # Build grouped summary
        succeeded = [r for r in results if r.get("success")]
        bucket_counts = {}
        for r in succeeded:
            b = r.get("bucket", "Unknown")
            bucket_counts[b] = bucket_counts.get(b, 0) + 1
        
        return {
            "total": len(results),
            "succeeded": len(succeeded),
            "failed": len(results) - len(succeeded),
            "by_bucket": bucket_counts,
            "results": results,
            "summary": f"Processed {len(succeeded)}/{len(results)} URLs: " + 
                       ", ".join(f"{count} about {bucket}" 
                                for bucket, count in sorted(bucket_counts.items(), key=lambda x: -x[1]))
        }
    except Exception as e:
        logger.error(f"Batch pipeline error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch processing failed: {str(e)}")


@router.get("/job/{job_id}")
def get_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check status of an async transcription job."""
    memory = db.query(Memory).filter(
        Memory.transcription_job_id == job_id,
        Memory.user_id == user.id
    ).first()
    
    if not memory:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        'job_id': job_id,
        'memory_id': memory.id,
        'status': memory.transcription_status,
        'progress': 'processing' if memory.transcription_status == 'processing' else 'done',
        'message': f"Transcription status: {memory.transcription_status}",
        'transcript': memory.transcript if memory.transcription_status == 'completed' and memory.transcript else None,
        'summary': memory.summary if memory.transcription_status == 'completed' else None,
        'cognitive_mode': memory.cognitive_mode if memory.transcription_status == 'completed' else None,
        'bucket': memory.bucket if memory.transcription_status == 'completed' else None,
        'error': memory.processing_error if memory.transcription_status == 'failed' else None,
        'created_at': memory.created_at.isoformat() if memory.created_at else None,
        'processed_at': memory.processed_at.isoformat() if memory.processed_at else None,
    }


# ── Knowledge Graph ───────────────────────────────────────────


@router.get("/graph")
def get_knowledge_graph(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get the knowledge graph scoped to the authenticated user."""
    return get_full_graph(db, user_id=user.id)


# ── Resurfaced Insights ──────────────────────────────────────


@router.get("/resurfaced")
def get_resurfaced(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get recently resurfaced memories for the authenticated user."""
    return get_recent_resurfaced(db, limit, user_id=user.id)


# ── Statistics ────────────────────────────────────────────────


@router.get("/stats")
def get_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get dashboard statistics for the authenticated user."""
    total_memories = db.query(func.count(Memory.id)).filter(Memory.user_id == user.id).scalar() or 0

    # Get connection IDs for this user's memories
    user_mem_ids = db.query(Memory.id).filter(Memory.user_id == user.id).subquery()
    total_connections = db.query(func.count(Connection.id)).filter(
        Connection.source_id.in_(user_mem_ids) | Connection.target_id.in_(user_mem_ids)
    ).scalar() or 0
    total_resurfaced = db.query(func.count(ResurfacedMemory.id)).filter(
        ResurfacedMemory.memory_id.in_(user_mem_ids)
    ).scalar() or 0

    # Category distribution
    categories_raw = (
        db.query(Memory.category, func.count(Memory.id))
        .filter(Memory.user_id == user.id)
        .group_by(Memory.category)
        .all()
    )
    categories = {cat: count for cat, count in categories_raw}

    avg_importance = (
        db.query(func.avg(Memory.importance_score))
        .filter(Memory.user_id == user.id)
        .scalar() or 0.0
    )

    top_category = max(categories, key=categories.get) if categories else "None"

    return {
        "total_memories": total_memories,
        "total_connections": total_connections,
        "total_resurfaced": total_resurfaced,
        "categories": categories,
        "avg_importance": round(avg_importance, 1),
        "top_category": top_category,
    }


# ── Categories ────────────────────────────────────────────────


@router.get("/categories")
def get_categories(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all categories with counts for the authenticated user."""
    results = (
        db.query(Memory.category, func.count(Memory.id))
        .filter(Memory.user_id == user.id)
        .group_by(Memory.category)
        .order_by(func.count(Memory.id).desc())
        .all()
    )
    return [{"category": cat, "count": count} for cat, count in results]


# ── Random Inspiration ───────────────────────────────────────


@router.get("/random")
def get_random_memory(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get a random memory for the authenticated user."""
    memory = db.query(Memory).filter(Memory.user_id == user.id).order_by(func.random()).first()
    if not memory:
        raise HTTPException(status_code=404, detail="No memories yet")
    return _serialize_memory(memory)


# ── Helpers ───────────────────────────────────────────────────


def _serialize_memory(memory: Memory) -> dict:
    import json
    return {
        "id": memory.id,
        "title": memory.title,
        "summary": memory.summary,
        "content": getattr(memory, 'content', getattr(memory, 'cleaned_text', '')),
        "category": memory.category,
        "bucket": getattr(memory, 'bucket', None),
        "tags": json.loads(memory.tags) if memory.tags else [],
        "importance_score": memory.importance_score,
        "importance_reasons": (
            json.loads(memory.importance_reasons) if memory.importance_reasons else []
        ),
        "platform": getattr(memory, 'platform', None),
        "source_url": getattr(memory, 'source_url', getattr(memory, 'url', None)),
        "thumbnail_url": getattr(memory, 'thumbnail_url', None),
        "user_id": memory.user_id,
        "created_at": (memory.created_at.isoformat() + "Z") if memory.created_at else "",
        "content_quality": getattr(memory, 'content_quality', None),
        "cognitive_mode": getattr(memory, 'cognitive_mode', None),
    }

def _get_user_buckets(user_id, db: Session) -> list:
    """Get list of distinct bucket names for a user."""
    try:
        results = (
            db.query(Memory.bucket)
            .filter(Memory.user_id == user_id)
            .filter(Memory.bucket.isnot(None))
            .filter(Memory.bucket != "Uncategorized")
            .distinct()
            .all()
        )
        return [r[0] for r in results if r[0]]
    except Exception:
        return []


def _save_cognitive_entry(entry, user_phone: str, db: Session) -> Memory:
    """Save a CognitiveEntry to the database as a Memory record."""
    memory = Memory(
        url=entry.url,
        platform=entry.platform,
        title=(entry.title or "")[:512],
        content=entry.content or "",
        summary=entry.summary or "",
        category=entry.bucket or "Uncategorized",
        tags=json.dumps(entry.tags or []),
        thumbnail_url=entry.thumbnail_url or "",
        user_phone=user_phone,
        # Transcription fields
        transcript=entry.transcript or "",
        transcript_length=len(entry.transcript) if entry.transcript else 0,
        transcript_source="local" if entry.content_quality == "full_transcript" else "subtitle" if entry.content_quality == "subtitle_only" else "caption",
        is_video=entry.platform in ("youtube", "instagram", "twitter"),
        # Cognitive fields
        cognitive_mode=entry.cognitive_mode or "learn",
        key_points=json.dumps(entry.key_points or []),
        bucket=entry.bucket or "Uncategorized",
        actionability_score=entry.actionability_score or 0.0,
        emotional_tone=entry.emotional_tone or "neutral",
        confidence_score=entry.confidence_score or 0.0,
        # Realistic architecture fields
        source_type=entry.source_type or "unknown",
        content_quality=entry.content_quality or "pending",
        content_hash=entry.content_hash or None,
        extraction_time_ms=entry.extraction_time_ms or 0,
        # Status
        transcription_status="completed" if entry.success else "failed",
        processed_at=datetime.utcnow() if entry.success else None,
    )
    
    db.add(memory)
    db.commit()
    db.refresh(memory)
    
    logger.info(f"Saved cognitive entry: id={memory.id}, quality={entry.content_quality}, bucket={entry.bucket}")
    return memory
