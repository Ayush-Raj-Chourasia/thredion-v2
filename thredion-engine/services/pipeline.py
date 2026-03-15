"""
Thredion Engine — Core Processing Pipeline
The main orchestrator that chains extraction → transcription → LLM → embedding → 
knowledge graph → importance → resurfacing.

Supports both sync and async video processing:
- SHORT videos (<5 min): Instant local transcription
- LONG videos (>5 min): Async queue processing
"""

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from db.models import Memory, User
from services.extractor import extract_from_url
from services.embeddings import generate_embedding
from services.classifier import classify_content
from services.knowledge_graph import build_connections
from services.importance import compute_importance
from services.resurfacing import find_resurfaceable
from services.transcriber import process_video
from services.llm_processor import process_with_groq, process_with_openai, fallback_classification

logger = logging.getLogger(__name__)

# Guard against concurrent duplicate inserts (e.g., timed-out request + retry)
_process_lock = threading.Lock()


async def process_url(url: str, user_id: str, db: Session) -> dict:
    """
    Full cognitive pipeline: URL → extract → embed → classify → graph → score → resurface.
    Returns a dict with all results for the WhatsApp reply and API response.
    """
    # ── Step 0: Validate & Duplicate check ───────────────────
    url = url.strip()
    if not url:
        raise ValueError("URL cannot be empty")
    
    with _process_lock:
        # Normalize: strip trailing slash, but preserve query params for YouTube/search URLs
        normalized_url = url.rstrip("/")
        # For non-video platforms, also try stripping query params
        stripped_url = normalized_url.split("?")[0] if not any(
            p in url.lower() for p in ["youtube.com", "youtu.be", "twitter.com", "x.com"]
        ) else normalized_url
        
        # Get user ID from phone
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User {user_id} not found")
        user_id = user.id

        existing = (
            db.query(Memory)
            .filter(
                Memory.user_id == user_id,
                (Memory.source_url == url)
                | (Memory.source_url == normalized_url)
                | (Memory.source_url == stripped_url),
            )
            .first()
        )
        if existing:
            logger.info(f"[Pipeline] Duplicate URL detected — memory #{existing.id}")
            import json as _json
            return {
                "memory_id": str(existing.id),
                "url": existing.source_url,
                "platform": existing.source,
                "title": existing.title,
                "summary": existing.summary,
                "category": existing.category,
                "tags": _json.loads(existing.tags) if isinstance(existing.tags, str) else existing.tags,
                "topic_graph": [],
                "importance_score": existing.importance_score or 0,
                "importance_reasons": [],
                "connections": [],
                "resurfaced": [],
                "thumbnail_url": "",
                "duplicate": True,
                "message": "This link already exists in your memory vault!",
            }

        # ── Step 1: Extract content from the URL ─────────────────
        logger.info(f"[Pipeline] Extracting content from {url}")
        extracted = extract_from_url(url)

        combined_text = f"{extracted.title} {extracted.content}".strip()
        if not combined_text:
            combined_text = url

        # ── Step 2: Generate embedding ───────────────────────────
        logger.info("[Pipeline] Generating embedding")
        embedding_bytes = generate_embedding(combined_text)

        # ── Step 3: Classify and summarize ───────────────────────
        logger.info("[Pipeline] Classifying content")
        classification = await classify_content(combined_text, url)

        # ── Step 4: Save to database ─────────────────────────────
        memory = Memory(
            source_url=url,
            source=extracted.platform,
            title=extracted.title or classification.summary[:100],
            original_input=extracted.content,
            summary=classification.summary,
            category=classification.category,
            tags=classification.tags, # models.py uses JSONB
            embedding=embedding_bytes,
            user_id=user_id,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        logger.info(f"[Pipeline] Saved memory #{memory.id}")
    # Lock released — heavy graph/importance work runs concurrently

    # ── Step 5: Build knowledge graph connections ────────────
    logger.info("[Pipeline] Building knowledge graph connections")
    connections = build_connections(memory, db)

    # ── Step 6: Compute importance score ─────────────────────
    logger.info("[Pipeline] Computing importance score")
    importance = compute_importance(memory, db)
    memory.importance_score = importance.score
    memory.importance_reasons = importance.reasons # JSONB
    db.commit()

    # ── Step 7: Check for resurfaceable memories ─────────────
    logger.info("[Pipeline] Checking for resurfaceable memories")
    resurfaced = find_resurfaceable(memory, db)

    # ── Build result ─────────────────────────────────────────
    result = {
        "memory_id": memory.id,
        "url": url,
        "platform": extracted.platform,
        "title": memory.title,
        "summary": classification.summary,
        "category": classification.category,
        "tags": classification.tags,
        "topic_graph": classification.topic_graph,
        "importance_score": importance.score,
        "importance_reasons": importance.reasons,
        "connections": connections,
        "resurfaced": resurfaced,
        "thumbnail_url": extracted.thumbnail_url,
    }

    logger.info(
        f"[Pipeline] Complete — Memory #{memory.id} | "
        f"Category: {classification.category} | "
        f"Importance: {importance.score} | "
        f"Connections: {len(connections)} | "
        f"Resurfaced: {len(resurfaced)}"
    )

    return result


# ── NEW: Async Video Processing Pipeline ──────────────────────────────────────


async def process_video_url_async(
    url: str,
    user_id: str,
    db: Session,
) -> Dict[str, Any]:
    """
    ASYNC VIDEO PIPELINE: Extract → Transcribe (short/long) → Structure with LLM →
    Embed → Classify → Save → Graph → Score → Resurface
    
    Handles both instant (short video) and queued (long video) transcription.
    """
    logger.info(f"[VIDEO PIPELINE] Starting: {url}")
    
    # ── Step 0: Validate & Duplicate check ───────────────────
    url = url.strip()
    if not url:
        raise ValueError("URL cannot be empty")
    
    with _process_lock:
        normalized_url = url.rstrip("/")
        stripped_url = normalized_url.split("?")[0] if not any(
            p in url.lower() for p in ["youtube.com", "youtu.be"]
        ) else normalized_url
        
        # Get user ID from phone
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User {user_id} not found")
        user_id = user.id

        existing = (
            db.query(Memory)
            .filter(
                Memory.user_id == user_id,
                (Memory.source_url == url) | (Memory.source_url == normalized_url) | (Memory.source_url == stripped_url),
            )
            .first()
        )
        
        if existing:
            logger.info(f"[VIDEO PIPELINE] Duplicate detected: Memory #{existing.id}")
            return {
                "memory_id": str(existing.id),
                "duplicate": True,
                "message": "This link already exists in your memory vault!",
            }
        
        # ── Step 1: Extract metadata ─────────────────────────────
        logger.info("[VIDEO PIPELINE] Extracting metadata...")
        extracted = extract_from_url(url)
        
        # ── Step 2: Create Memory record with pending status ─────
        memory = Memory(
            source_url=url,
            source=extracted.platform,
            title=extracted.title,
            original_input=extracted.content,
            user_id=user_id,
            # video_duration=extracted.duration_seconds, # Check if field exists in models.py
            # is_video=True,
            # transcription_status='pending',
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        logger.info(f"[VIDEO PIPELINE] Created memory record #{memory.id}")
    
    # ── Step 3: Process video (transcribe) ───────────────────
    logger.info("[VIDEO PIPELINE] Processing video transcription...")
    transcription_result = await process_video(url, user_id, db)
    
    # ── Handle transcription result ──────────────────────────
    if transcription_result['status'] == 'completed':
        # SHORT VIDEO: We got transcript immediately
        logger.info(f"[VIDEO PIPELINE] Short video transcribed ({len(transcription_result['transcript'])} chars)")
        
        transcript = transcription_result['transcript']
        memory.transcript = transcript
        memory.transcript_length = len(transcript)
        memory.transcript_source = 'local'
        memory.transcription_status = 'completed'
        
        # ── Step 4: Structure with LLM ──────────────────────────
        logger.info("[VIDEO PIPELINE] Processing with Groq LLM...")
        user = db.query(User).filter(User.id == user_id).first()
        existing_buckets = []  # TODO: Get from user.buckets if available
        
        structured = await process_with_groq(
            text=transcript,
            existing_buckets=existing_buckets,
            platform=extracted.platform
        )
        
        if structured:
            memory.cognitive_mode = structured.cognitive_mode
            memory.title_generated = structured.title
            memory.summary = structured.summary
            memory.key_points = json.dumps(structured.key_points)
            memory.bucket = structured.bucket
            memory.tags = json.dumps(structured.tags)
            memory.actionability_score = structured.actionability_score
            memory.emotional_tone = structured.emotional_tone
            memory.confidence_score = structured.confidence_score
            logger.info(f"[VIDEO PIPELINE] ✅ LLM structured: {structured.cognitive_mode} → {structured.bucket}")
        else:
            # Fallback
            fallback = await fallback_classification(transcript)
            memory.cognitive_mode = fallback.cognitive_mode
            memory.summary = fallback.summary
            memory.bucket = fallback.bucket
            logger.warning("[VIDEO PIPELINE] LLM failed, using fallback")
        
        memory.processed_at = datetime.utcnow()
        
    elif transcription_result['status'] == 'processing':
        # LONG VIDEO: Queued for async processing
        logger.info(f"[VIDEO PIPELINE] Long video queued: Job {transcription_result['job_id'][:8]}...")
        
        memory.transcription_job_id = transcription_result['job_id']
        memory.transcription_status = 'processing'
        memory.transcript_source = 'async_queued'
        
        return {
            "memory_id": memory.id,
            "status": "processing",
            "job_id": transcription_result['job_id'],
            "message": transcription_result.get('message', 'Processing long video...'),
        }
    
    else:
        # FAILED
        logger.error(f"[VIDEO PIPELINE] Transcription failed: {transcription_result.get('error')}")
        memory.transcription_status = 'failed'
        memory.processing_error = transcription_result.get('error')
        db.commit()
        
        return {
            "memory_id": memory.id,
            "status": "failed",
            "error": transcription_result.get('error'),
        }
    
    # ── Step 5: Generate embedding ──────────────────────────
    logger.info("[VIDEO PIPELINE] Generating embedding...")
    combined_text = f"{memory.summary} {' '.join(memory.key_points)}" if memory.key_points else memory.summary
    embedding_bytes = generate_embedding(combined_text)
    memory.embedding = embedding_bytes
    
    # ── Step 6: Build knowledge graph ───────────────────────
    logger.info("[VIDEO PIPELINE] Building knowledge graph...")
    db.commit()  # Save before graph
    connections = build_connections(memory, db)
    
    # ── Step 7: Compute importance ──────────────────────────
    logger.info("[VIDEO PIPELINE] Computing importance score...")
    importance = compute_importance(memory, db)
    memory.importance_score = importance.score
    memory.importance_reasons = json.dumps(importance.reasons)
    
    # ── Step 8: Check for resurfacing ───────────────────────
    logger.info("[VIDEO PIPELINE] Checking resurfacing...")
    resurfaced = find_resurfaceable(memory, db)
    
    db.commit()
    
    logger.info(
        f"[VIDEO PIPELINE] ✅ COMPLETE — Memory #{memory.id} | "
        f"Mode: {memory.cognitive_mode} | "
        f"Bucket: {memory.bucket} | "
        f"Actionability: {memory.actionability_score:.1%}"
    )
    
    return {
        "memory_id": memory.id,
        "status": "completed",
        "url": url,
        "platform": extracted.platform,
        "title": memory.title_generated or memory.title,
        "summary": memory.summary,
        "cognitive_mode": memory.cognitive_mode,
        "bucket": memory.bucket,
        "tags": json.loads(memory.tags) if memory.tags else [],
        "actionability_score": memory.actionability_score,
        "emotional_tone": memory.emotional_tone,
        "confidence_score": memory.confidence_score,
        "transcript_length": memory.transcript_length,
        "importance_score": importance.score,
        "connections": connections,
        "resurfaced": resurfaced,
    }

