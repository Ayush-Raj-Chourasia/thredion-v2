"""
Thredion Engine — Background Worker
Processes queued transcription jobs from Azure Queue Storage.
Handles long videos (>5 min) that were queued for async processing.

Runs as:
- Azure Functions (Timer Trigger every 5 seconds)
- Docker container with infinite polling loop
- Separate process/thread
"""

import asyncio
import json
import logging
from datetime import datetime

from azure.storage.queue import QueueClient, QueueMessage
from sqlalchemy.orm import Session

from core.config import settings
from db.database import SessionLocal
from db.models import Memory, User
from services.transcriber import transcribe_short_video
from services.llm_processor import process_with_groq, fallback_classification

logger = logging.getLogger(__name__)


async def process_queue_message(message: QueueMessage) -> bool:
    """
    Process a single transcription job from the queue.
    Returns True if successful, False otherwise.
    """
    try:
        job_data = json.loads(message.content)
        job_id = job_data.get('job_id')
        url = job_data.get('url')
        user_id = job_data.get('user_id')
        
        logger.info(f"[WORKER] Processing job {str(job_id)[:8]}... for {user_id}")
        
        db = SessionLocal()
        try:
            # Find the memory record
            memory = db.query(Memory).filter(
                Memory.transcription_job_id == job_id,
                Memory.user_id == user_id
            ).first()
            
            if not memory:
                logger.error(f"[WORKER] Memory record not found for job {job_id}")
                return False
            
            # Mark as processing
            memory.transcription_status = 'processing'
            db.commit()
            
            logger.info(f"[WORKER] Transcribing: {url}")
            
            # Transcribe (use local faster-whisper for consistency)
            # For very long videos, this might timeout, but that's OK
            try:
                transcript = await transcribe_short_video(url)
            except Exception as e:
                logger.error(f"[WORKER] Transcription error: {e}")
                memory.transcription_status = 'failed'
                memory.processing_error = f"Transcription failed: {str(e)}"
                db.commit()
                db.close()
                return False
            
            logger.info(f"[WORKER] ✅ Transcribed: {len(transcript)} chars")
            
            # Update memory
            memory.transcript = transcript
            memory.transcript_length = len(transcript)
            memory.transcript_source = 'local_async'
            
            # Structure with LLM
            user = db.query(User).filter(User.id == user_id).first()
            existing_buckets = []  # TODO: Get from user.buckets if available
            
            logger.info(f"[WORKER] Structuring with LLM...")
            structured = await process_with_groq(
                text=transcript,
                existing_buckets=existing_buckets,
                platform=memory.platform
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
                logger.info(f"[WORKER] ✅ LLM structured: {structured.cognitive_mode}")
            else:
                # Fallback
                fallback = await fallback_classification(transcript)
                memory.cognitive_mode = fallback.cognitive_mode
                memory.summary = fallback.summary
                memory.bucket = fallback.bucket
                logger.warning(f"[WORKER] LLM failed, using fallback")
            
            memory.transcription_status = 'completed'
            memory.processed_at = datetime.utcnow()
            
            db.commit()
            
            logger.info(f"[WORKER] ✅ Job {str(job_id)[:8]}... COMPLETE")
            return True
        
        except Exception as e:
            logger.error(f"[WORKER] Unexpected error: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()
    
    except json.JSONDecodeError as e:
        logger.error(f"[WORKER] Invalid JSON in message: {e}")
        return False
    except Exception as e:
        logger.error(f"[WORKER] Unexpected error processing message: {e}", exc_info=True)
        return False


async def poll_queue():
    """
    Poll Azure Queue Storage for transcription jobs and process them.
    Runs in an infinite loop.
    """
    if not settings.AZURE_QUEUE_CONNECTION_STRING:
        logger.error("❌ AZURE_QUEUE_CONNECTION_STRING not configured!")
        return
    
    logger.info("🚀 Worker started: polling for transcription jobs...")
    
    queue_client = QueueClient.from_connection_string(
        settings.AZURE_QUEUE_CONNECTION_STRING,
        settings.AZURE_QUEUE_NAME
    )
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            # Get up to 5 messages (batch processing)
            messages = queue_client.receive_messages(max_messages=5, visibility_timeout=600)
            
            message_count = 0
            for message in messages:
                message_count += 1
                success = await process_queue_message(message)
                
                if success:
                    # Delete message from queue
                    queue_client.delete_message(message)
                    consecutive_errors = 0
                else:
                    # Leave in queue (will be retried after visibility_timeout)
                    logger.warning(f"Message processing failed, will retry")
            
            if message_count == 0:
                # No messages, wait before polling again
                await asyncio.sleep(5)
                consecutive_errors = min(consecutive_errors + 1, max_consecutive_errors)
            else:
                consecutive_errors = 0
        
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Queue polling error: {e} (attempt {consecutive_errors}/{max_consecutive_errors})")
            
            if consecutive_errors >= max_consecutive_errors:
                logger.error("Too many consecutive errors, exiting worker")
                break
            
            await asyncio.sleep(10 * consecutive_errors)


async def process_pending_jobs():
    """
    One-time function to process all pending jobs (for testing or startup).
    """
    db = SessionLocal()
    try:
        pending = db.query(Memory).filter(
            Memory.transcription_status == 'processing',
            Memory.transcription_job_id.isnot(None)
        ).all()
        
        logger.info(f"Found {len(pending)} pending jobs")
        
        for memory in pending:
            job_data = {
                'job_id': memory.transcription_job_id,
                'url': memory.url,
                'user_id': memory.user_id,
            }
            
            # Simulate message
            class FakeMessage:
                def __init__(self, data):
                    self.content = json.dumps(data)
                    self.id = data['job_id']
            
            fake_msg = FakeMessage(job_data)
            await process_queue_message(fake_msg)
    finally:
        db.close()


def run_worker_sync():
    """
    Synchronous entry point for running the worker.
    Use this for Azure Functions or CLI.
    """
    asyncio.run(poll_queue())


async def run_worker_async():
    """
    Asynchronous entry point.
    Use this in async contexts.
    """
    await poll_queue()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("Starting Thredion background worker...")
    run_worker_sync()
