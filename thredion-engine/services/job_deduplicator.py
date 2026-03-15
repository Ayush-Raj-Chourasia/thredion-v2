"""
Job Deduplicator — URL De-duplication & Job Management

Prevents processing the same URL multiple times:
- Check if URL already processed for this user
- Return existing result if completed
- Return existing job_id if currently processing
- Skip if known permanent failure

This is the first check before ANY processing starts.
"""

import logging
import hashlib
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

from db.models import Memory

logger = logging.getLogger(__name__)


@dataclass
class DeduplicationResult:
    """Result of calling should_process_url()."""
    action: str  # "process_new"|"return_existing"|"return_existing_job"|"skip_permanent_failure"
    memory_id: Optional[int] = None
    job_id: Optional[str] = None
    reason: Optional[str] = None
    source_type: Optional[str] = None
    created_at: Optional[datetime] = None
    job_status: Optional[str] = None


def normalize_url(url: str, platform: str) -> str:
    """
    Normalize URL to canonical form for deduplication.
    
    Examples:
    - YouTube: https://youtu.be/abc → https://www.youtube.com/watch?v=abc
    - Instagram: https://instagram.com/p/xyz/ → https://www.instagram.com/p/xyz/
    - Twitter: https://x.com/usr/status/123 → https://twitter.com/usr/status/123
    """
    url = url.strip().lower()
    
    if platform == "youtube":
        # Handle all YouTube URL variants
        if "youtu.be/" in url:
            # youtu.be/abc → extract video ID
            video_id = url.split("youtu.be/")[-1].split("?")[0]
            return f"https://www.youtube.com/watch?v={video_id}"
        elif "/shorts/" in url:
            # /shorts/abc → /watch?v=abc
            video_id = url.split("/shorts/")[-1].split("?")[0]
            return f"https://www.youtube.com/watch?v={video_id}"
        else:
            # Extract just the video ID, reconstruct
            import re
            match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
            if match:
                video_id = match.group(1)
                return f"https://www.youtube.com/watch?v={video_id}"
    
    elif platform == "instagram":
        # Normalize to www.instagram.com and remove query params
        url = url.replace("instegram.am", "instagram.com")
        url = url.replace("instagram.com", "www.instagram.com")
        # Remove query params and ?igsh=...
        url = url.split("?")[0]
        # Ensure trailing slash
        if not url.endswith("/"):
            url += "/"
        return url
    
    elif platform == "twitter":
        # Normalize x.com to twitter.com, remove params
        url = url.replace("x.com", "twitter.com")
        url = url.replace("twitter.com", "twitter.com")  # Already good
        url = url.split("?")[0]  # Remove params
        return url
    
    # Default: return as-is but lowercase and trimmed
    return url


def compute_content_hash(content: str) -> str:
    """
    Compute SHA256 hash of content for deduplication.
    
    Useful for detecting if same content appears twice with different URLs.
    """
    return hashlib.sha256(content.encode()).hexdigest()


class JobDeduplicator:
    """
    Check before processing to avoid duplicate work.
    
    In production, this would query the database:
    - Memory table for (user_id, canonical_url, job_status)
    - CostLog table for billing history
    """
    
    def __init__(self, db_session=None):
        """Initialize (in production, would get DB session)."""
        self.db = db_session
    
    def should_process_url(
        self,
        url: str,
        user_id: str,
        platform: str,
    ) -> DeduplicationResult:
        """
        Main deduplication check.
        
        Returns:
            DeduplicationResult with action and details
        
        Actions:
            - "process_new": Safe to process
            - "return_existing": URL already completed, return result
            - "return_existing_job": URL being processed, return job_id
            - "skip_permanent_failure": Known permanent failure, skip
        """
        
        # Step 1: Normalize URL
        canonical_url = normalize_url(url, platform)
        
        logger.info(f"Dedup check: {platform} / {user_id} / {canonical_url}")
        
        # Step 2: Check if already completed
        # In real code: 
        # memory = db.query(Memory).filter(
        #     Memory.user_id == user_id,
        #     Memory.canonical_url == canonical_url,
        #     Memory.job_status == "completed"
        # ).first()
        
        # Placeholder for now - would query database
        existing_completed = None  # self._query_completed(user_id, canonical_url)
        
        if existing_completed:
            return DeduplicationResult(
                action="return_existing",
                memory_id=existing_completed.get("id"),
                source_type=existing_completed.get("source_type"),
                created_at=existing_completed.get("created_at"),
                reason=f"URL already processed on {existing_completed.get('created_at').date()}",
            )
        
        # Step 3: Check if currently processing
        # In real code:
        # processing = db.query(Memory).filter(
        #     Memory.user_id == user_id,
        #     Memory.canonical_url == canonical_url,
        #     Memory.job_status.in_(["queued", "extracting", "transcribing", "classifying"])
        # ).first()
        
        existing_processing = None  # self._query_processing(user_id, canonical_url)
        
        if existing_processing:
            return DeduplicationResult(
                action="return_existing_job",
                job_id=existing_processing.get("job_id"),
                job_status=existing_processing.get("job_status"),
                reason=f"URL already being processed (status: {existing_processing.get('job_status')})",
            )
        
        # Step 4: Check for recent permanent failures
        # In real code:
        # recent_failure = db.query(Memory).filter(
        #     Memory.user_id == user_id,
        #     Memory.canonical_url == canonical_url,
        #     Memory.failure_class == "permanent",
        #     Memory.last_failure_at > datetime.utcnow() - timedelta(hours=24)
        # ).first()
        
        recent_failure = None  # self._query_recent_failure(user_id, canonical_url)
        
        if recent_failure:
            return DeduplicationResult(
                action="skip_permanent_failure",
                reason=f"Known permanent failure: {recent_failure.get('failure_reason')}",
            )
        
        # Step 5: OK to process
        logger.info(f"✅ {user_id} / {canonical_url}: Safe to process")
        
        return DeduplicationResult(
            action="process_new",
            reason="URL is new or safe to retry",
        )
    
    def check_bulk_urls(
        self,
        urls: list[str],
        user_id: str,
        platform: str,
    ) -> Dict[str, DeduplicationResult]:
        """
        Check multiple URLs at once (batch operation).
        
        Useful when user submits multiple links.
        """
        results = {}
        for url in urls:
            results[url] = self.should_process_url(url, user_id, platform)
        return results
    
    # ── Placeholder database query methods ────────────────────────────
    
    def _query_completed(self, user_id: str, canonical_url: str) -> Optional[Dict]:
        """Query for completed job."""
        if not self.db:
            return None
        try:
            memory = self.db.query(Memory).filter(
                Memory.user_id == user_id,
                Memory.canonical_url == canonical_url,
                Memory.job_status == "completed"
            ).first()
            if memory:
                return {
                    "id": memory.id,
                    "source_type": memory.source_type,
                    "created_at": memory.created_at,
                }
        except Exception as e:
            logger.debug(f"Dedup completed query error: {e}")
        return None
    
    def _query_processing(self, user_id: str, canonical_url: str) -> Optional[Dict]:
        """Query for job in progress."""
        if not self.db:
            return None
        try:
            memory = self.db.query(Memory).filter(
                Memory.user_id == user_id,
                Memory.canonical_url == canonical_url,
                Memory.job_status.in_(["queued", "extracting", "transcribing", "classifying"])
            ).first()
            if memory:
                return {
                    "job_id": memory.job_id,
                    "job_status": memory.job_status,
                }
        except Exception as e:
            logger.debug(f"Dedup processing query error: {e}")
        return None
    
    def _query_recent_failure(self, user_id: str, canonical_url: str) -> Optional[Dict]:
        """Query for recent permanent failure."""
        if not self.db:
            return None
        try:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            memory = self.db.query(Memory).filter(
                Memory.user_id == user_id,
                Memory.canonical_url == canonical_url,
                Memory.failure_class == "permanent",
                Memory.last_failure_at > cutoff
            ).first()
            if memory:
                return {
                    "failure_reason": memory.failure_reason,
                    "last_failure_at": memory.last_failure_at,
                }
        except Exception as e:
            logger.debug(f"Dedup failure query error: {e}")
        return None


# Global instance
deduplicator = JobDeduplicator()
