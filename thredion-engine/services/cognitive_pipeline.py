"""
Thredion Engine — Cognitive Pipeline
The unified orchestrator: URL -> extract -> transcribe -> LLM structure -> save

This is the core pipeline that makes Thredion a cognitive memory system.
For any URL (YouTube, Instagram reel, Twitter video, article):
1. Extract metadata + captions (fast, free)
2. Download audio and transcribe speech (full understanding)
3. Combine best available content
4. Send to LLM for cognitive structuring (learn/think/reflect, bucketing, summary)
5. Save structured cognitive entry to database

Content quality hierarchy:
  full_transcript > subtitle_only > caption_only > metadata_only
"""

import logging
import hashlib
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

from services.transcriber import (
    transcribe_url_full,
    TranscriptionResult,
    detect_platform,
    get_video_metadata,
)
from services.llm_processor import process_with_groq, fallback_classification, CognitiveStructure
from services.youtube_extractor import extract_youtube
from services.instagram_extractor import extract_instagram
from services.twitter_extractor import extract_twitter

logger = logging.getLogger(__name__)


# ── Result Dataclass ─────────────────────────────────────────────

@dataclass
class CognitiveEntry:
    """Complete cognitive entry ready for database storage."""
    # Source
    url: str = ""
    platform: str = ""
    canonical_url: str = ""
    
    # Content (best available)
    title: str = ""
    content: str = ""  # The actual text content (transcript or caption)
    transcript: str = ""  # Raw transcript if available
    caption: str = ""  # Caption/description if available
    thumbnail_url: str = ""
    
    # Quality tracking
    content_quality: str = "pending"  # full_transcript|subtitle_only|caption_only|metadata_only
    source_type: str = ""  # How we got the content
    
    # Cognitive structure (from LLM)
    cognitive_mode: str = "learn"  # learn|think|reflect
    summary: str = ""
    key_points: list = None
    bucket: str = "Uncategorized"
    tags: list = None
    actionability_score: float = 0.0
    emotional_tone: str = "neutral"
    confidence_score: float = 0.0
    
    # Metadata
    duration_seconds: int = 0
    content_hash: str = ""
    extraction_time_ms: int = 0
    success: bool = False
    error: str = ""
    
    def __post_init__(self):
        if self.key_points is None:
            self.key_points = []
        if self.tags is None:
            self.tags = []


# ── Main Pipeline ────────────────────────────────────────────────

async def process_cognitive_entry(
    url: str,
    user_id: str = "",
    db_session=None,
    existing_buckets: Optional[List[str]] = None,
) -> CognitiveEntry:
    """
    Full cognitive pipeline: URL -> understand -> structure -> return.
    
    This is the main entry point. It:
    1. Detects the platform
    2. Extracts metadata + captions (fast)
    3. Attempts full audio transcription (best quality)
    4. Picks the best available content
    5. Sends to LLM for cognitive structuring
    6. Returns a complete CognitiveEntry
    """
    start_time = time.time()
    entry = CognitiveEntry(url=url)
    
    try:
        # Step 1: Detect platform
        platform = detect_platform(url)
        entry.platform = platform
        logger.info(f"[COGNITIVE] Processing {platform} URL: {url}")
        
        # Step 2: Extract metadata + captions (fast, always succeeds partially)
        caption, metadata = await _extract_metadata(url, platform)
        entry.title = metadata.get("title", "")
        entry.thumbnail_url = metadata.get("thumbnail_url", "")
        entry.duration_seconds = metadata.get("duration_seconds", 0)
        entry.caption = caption
        entry.source_type = metadata.get("source_type", "unknown")
        
        # Step 3: Attempt full audio transcription (best quality)
        if entry.source_type in ["supadata_api", "transcript24_api"]:
            logger.info(f"[COGNITIVE] Skipping audio transcription, already have {entry.source_type} transcript.")
            transcript_result = None
        else:
            transcript_result = await _try_transcription(url, platform)
        
        if transcript_result and transcript_result.success:
            entry.transcript = transcript_result.transcript
            entry.content_quality = "full_transcript"
            entry.content = transcript_result.transcript
            logger.info(f"[COGNITIVE] Full transcript obtained: {len(entry.transcript)} chars")
        elif entry.source_type in ["supadata_api", "transcript24_api"]:
            entry.content_quality = "full_transcript"
            entry.content = caption
            logger.info(f"[COGNITIVE] Using premium API transcript: {len(caption)} chars")
        elif entry.source_type in ["yt_transcript_api", "yt_subtitle"]:
            # YouTube subtitles = subtitle quality (not full audio but close)
            entry.content_quality = "subtitle_only"
            entry.content = caption
            logger.info(f"[COGNITIVE] Using YouTube subtitles: {len(caption)} chars")
        elif entry.source_type == "socialkit_api":
            entry.content_quality = "caption_only"
            entry.content = caption
            logger.info(f"[COGNITIVE] Using SocialKit caption: {len(caption)} chars")
        elif caption and len(caption.strip()) > 10:
            # Caption/description available
            entry.content_quality = "caption_only"
            entry.content = caption
            logger.info(f"[COGNITIVE] Using standard caption: {len(caption)} chars")
        else:
            # Metadata only
            entry.content_quality = "metadata_only"
            entry.content = entry.title or url
            logger.info(f"[COGNITIVE] Metadata only: {entry.title}")
        
        # Step 4: Compute content hash for dedup
        if entry.content:
            entry.content_hash = hashlib.sha256(entry.content.encode()).hexdigest()
        
        # Step 5: LLM cognitive structuring
        if entry.content and len(entry.content.strip()) > 15:
            cognitive = await _structure_with_llm(
                entry.content, platform, existing_buckets
            )
            if cognitive:
                entry.cognitive_mode = cognitive.cognitive_mode
                entry.summary = cognitive.summary
                entry.key_points = cognitive.key_points
                entry.bucket = cognitive.bucket
                entry.tags = cognitive.tags
                entry.actionability_score = cognitive.actionability_score
                entry.emotional_tone = cognitive.emotional_tone
                entry.confidence_score = cognitive.confidence_score
                if not entry.title or entry.title == "Instagram Post":
                    entry.title = cognitive.title
        
        entry.success = True
        entry.extraction_time_ms = int((time.time() - start_time) * 1000)
        
        logger.info(
            f"[COGNITIVE] Complete: quality={entry.content_quality}, "
            f"mode={entry.cognitive_mode}, bucket={entry.bucket}, "
            f"content={len(entry.content)} chars, time={entry.extraction_time_ms}ms"
        )
        
    except Exception as e:
        entry.success = False
        entry.error = str(e)
        entry.extraction_time_ms = int((time.time() - start_time) * 1000)
        logger.error(f"[COGNITIVE] Pipeline failed for {url}: {e}")
    
    return entry


# ── Step 2: Extract Metadata + Captions ──────────────────────────

async def _extract_metadata(url: str, platform: str) -> tuple:
    """
    Extract metadata and captions using the specialized extractors.
    Returns (caption_text, metadata_dict).
    """
    caption = ""
    metadata = {"title": "", "thumbnail_url": "", "duration_seconds": 0, "source_type": "unknown"}
    
    try:
        if platform == "youtube":
            result = extract_youtube(url)
            caption = result.content or ""
            metadata = {
                "title": result.title,
                "thumbnail_url": result.thumbnail_url,
                "duration_seconds": result.duration_seconds,
                "source_type": result.source_type,
            }
        
        elif platform == "instagram":
            result = extract_instagram(url)
            caption = result.content or ""
            metadata = {
                "title": result.title,
                "thumbnail_url": result.thumbnail_url,
                "duration_seconds": 0,
                "source_type": result.source_type,
            }
        
        elif platform == "twitter":
            result = extract_twitter(url)
            caption = result.content or ""
            metadata = {
                "title": result.title or f"Tweet by {result.author_name}",
                "thumbnail_url": result.thumbnail_url,
                "duration_seconds": 0,
                "source_type": result.source_type,
            }
        
        else:
            # Generic: try yt-dlp metadata
            meta = await get_video_metadata(url)
            caption = meta.get("description", "")
            metadata = {
                "title": meta.get("title", ""),
                "thumbnail_url": meta.get("thumbnail", ""),
                "duration_seconds": meta.get("duration_seconds", 0),
                "source_type": "generic",
            }
    
    except Exception as e:
        logger.warning(f"Metadata extraction failed for {url}: {e}")
    
    return caption, metadata


# ── Step 3: Transcription ────────────────────────────────────────

async def _try_transcription(url: str, platform: str) -> Optional[TranscriptionResult]:
    """
    Attempt full audio transcription. 
    Only try for platforms where audio makes sense (video content).
    """
    # Skip transcription for non-video content
    if platform not in ("youtube", "instagram", "twitter"):
        return None
    
    # For YouTube, if we already got subtitles via transcript-api, 
    # audio transcription is redundant. Skip it.
    # The caller will check if the caption is from yt_transcript_api and set quality accordingly.
    
    try:
        logger.info(f"[COGNITIVE] Attempting audio transcription for {platform}: {url}")
        result = await transcribe_url_full(url)
        return result
    except Exception as e:
        logger.warning(f"[COGNITIVE] Audio transcription failed for {url}: {e}")
        return None


# ── Step 5: LLM Cognitive Structuring ────────────────────────────

async def _structure_with_llm(
    content: str,
    platform: str,
    existing_buckets: Optional[List[str]] = None,
) -> Optional[CognitiveStructure]:
    """
    Send content to LLM for cognitive analysis.
    Returns structured output (mode, bucket, summary, score, etc.)
    Falls back to keyword classification if LLM is unavailable.
    """
    try:
        result = await process_with_groq(
            text=content,
            existing_buckets=existing_buckets,
            platform=platform,
        )
        if result:
            return result
    except Exception as e:
        logger.warning(f"Groq LLM failed: {e}")
    
    # Fallback to keyword-based classification
    try:
        return await fallback_classification(content)
    except Exception as e:
        logger.warning(f"Fallback classification also failed: {e}")
        return None


# ── Batch Processing ─────────────────────────────────────────────

# Per-platform rate limits (seconds between requests)
PLATFORM_RATE_LIMITS = {
    "youtube": 3.0,
    "instagram": 1.5,
    "twitter": 0.5,
    "unknown": 1.0,
}


async def process_batch(
    urls: List[str],
    user_id: str = "",
    db_session=None,
    existing_buckets: Optional[List[str]] = None,
    max_concurrent: int = 3,
) -> List[CognitiveEntry]:
    """
    Process multiple URLs with rate limiting.
    Handles the scenario: user forwards 10-20 reels from Instagram.
    
    Groups by platform, processes with rate limits, deduplicates.
    Returns list of CognitiveEntry results.
    """
    import asyncio
    
    if not urls:
        return []
    
    # Cap at 20 URLs per batch
    urls = urls[:20]
    
    # Deduplicate
    seen = set()
    unique_urls = []
    for url in urls:
        normalized = url.strip().rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            unique_urls.append(url.strip())
    
    logger.info(f"[BATCH] Processing {len(unique_urls)} unique URLs (from {len(urls)} input)")
    
    # Group by platform for rate limiting
    by_platform: Dict[str, List[str]] = {}
    for url in unique_urls:
        platform = detect_platform(url)
        by_platform.setdefault(platform, []).append(url)
    
    results = []
    
    for platform, platform_urls in by_platform.items():
        rate_limit = PLATFORM_RATE_LIMITS.get(platform, 1.0)
        logger.info(f"[BATCH] Processing {len(platform_urls)} {platform} URLs (delay={rate_limit}s)")
        
        for i, url in enumerate(platform_urls):
            if i > 0:
                await asyncio.sleep(rate_limit)
            
            try:
                entry = await process_cognitive_entry(
                    url, user_id, db_session, existing_buckets
                )
                results.append(entry)
                
                # Update existing buckets for better bucketing of subsequent items
                if entry.bucket and entry.bucket != "Uncategorized":
                    if existing_buckets is None:
                        existing_buckets = []
                    if entry.bucket not in existing_buckets:
                        existing_buckets.append(entry.bucket)
                
            except Exception as e:
                logger.error(f"[BATCH] Failed for {url}: {e}")
                results.append(CognitiveEntry(
                    url=url,
                    platform=platform,
                    success=False,
                    error=str(e),
                ))
    
    # Log batch summary
    succeeded = sum(1 for r in results if r.success)
    logger.info(f"[BATCH] Complete: {succeeded}/{len(results)} succeeded")
    
    # Group by bucket for user feedback
    bucket_counts: Dict[str, int] = {}
    for r in results:
        if r.success:
            bucket_counts[r.bucket] = bucket_counts.get(r.bucket, 0) + 1
    
    if bucket_counts:
        summary_parts = [f"{count} about {bucket}" for bucket, count in sorted(bucket_counts.items(), key=lambda x: -x[1])]
        logger.info(f"[BATCH] Summary: {', '.join(summary_parts)}")
    
    return results
