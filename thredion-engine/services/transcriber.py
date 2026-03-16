"""
Thredion Engine — Video Transcriber Service
Dual-mode transcription:
- SHORT videos (<5 min): Local faster-whisper (free, instant)
- LONG videos (>5 min): Queue for async Groq processing (free, background)
"""

import asyncio
import logging
import os
import json
import uuid
import tempfile
import re
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass

import yt_dlp
import requests
try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception:  # pragma: no cover
    WhisperModel = None
whisper = WhisperModel

from core.config import settings

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Global Whisper Model Cache ─────────────────────────────
_whisper_model: Optional[Any] = None
WHISPER_MODEL: Optional[Any] = None
_model_lock = asyncio.Lock()


@dataclass
class TranscriptionResult:
    """Result of audio transcription."""
    transcript: str = ""
    content_quality: str = "pending"  # full_transcript|subtitle_only|caption_only|metadata_only
    duration_seconds: int = 0
    language: str = "en"
    success: bool = False
    error: str = ""


def _load_whisper_model_sync() -> Any:
    """Load faster-whisper model synchronously (safe for thread executors)."""
    global _whisper_model, WHISPER_MODEL
    
    if WHISPER_MODEL is not None:
        _whisper_model = WHISPER_MODEL
        return WHISPER_MODEL
    if _whisper_model is not None:
        return _whisper_model
    
    logger.info("Loading faster-whisper model (%s)...", settings.WHISPER_MODEL_SIZE)
    try:
        model_cls = WhisperModel
        if model_cls is None:
            from faster_whisper import WhisperModel as model_cls
        _whisper_model = model_cls(
            model_size_or_path=settings.WHISPER_MODEL_SIZE,
            device="cpu",
            compute_type="int8",
            num_workers=1,
            cpu_threads=2
        )
        WHISPER_MODEL = _whisper_model
        logger.info("Whisper model loaded successfully")
        return _whisper_model
    except Exception as e:
        logger.error(f"Failed to load Whisper model: {e}")
        raise


async def load_whisper_model() -> Any:
    """
    Lazy-load faster-whisper model (async-safe).
    Uses locking to prevent multiple concurrent loads.
    """
    global _whisper_model
    
    if _whisper_model is not None:
        return _whisper_model
    
    async with _model_lock:
        if _whisper_model is not None:
            return _whisper_model
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _load_whisper_model_sync)


def detect_platform(url: str) -> str:
    """Detect video platform from URL."""
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "instagram.com" in url_lower or "instagr.am" in url_lower:
        return "instagram"
    elif "tiktok.com" in url_lower or "vm.tiktok.com" in url_lower:
        return "tiktok"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    elif "reddit.com" in url_lower:
        return "reddit"
    else:
        return "unknown"


async def get_video_metadata(url: str) -> Dict[str, Any]:
    """
    Extract video metadata (duration, title, thumbnail, description).
    Non-blocking: uses thread executor to avoid blocking event loop.
    """
    logger.info(f"[METADATA] Extracting from {url}")
    
    def _extract():
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'socket_timeout': 30,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                return {
                    'duration_seconds': int(info.get('duration', 0)),
                    'title': info.get('title', 'Unknown')[:200],
                    'platform': detect_platform(url),
                    'thumbnail': info.get('thumbnail', ''),
                    'description': info.get('description', '')[:500],
                    'uploader': info.get('uploader', '')[:100],
                    'view_count': info.get('view_count', 0),
                    'success': True,
                }
        except Exception as e:
            logger.warning(f"[METADATA] Extraction failed: {e}")
            # Return conservative estimate for unknown videos
            return {
                'duration_seconds': 600,  # Assume 10 min
                'title': 'Unknown',
                'platform': detect_platform(url),
                'description': '',
                'uploader': '',
                'view_count': 0,
                'success': False,
                'error': str(e),
            }
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _extract)


async def download_audio(url: str) -> Optional[str]:
    """
    Download audio from any video URL (YouTube, Instagram, Twitter).
    Returns path to downloaded audio file, or None on failure.
    Platform-agnostic: yt-dlp handles YouTube, Instagram, Twitter, TikTok etc.
    """
    tmp_dir = tempfile.gettempdir()
    output_template = os.path.join(tmp_dir, f"thredion_audio_{uuid.uuid4().hex[:8]}.%(ext)s")
    
    def _download():
        ffmpeg_path = os.getenv('FFMPEG_PATH', 'ffmpeg')

        attempt_options = [
            {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '192',
                }],
                'ffmpeg_location': ffmpeg_path,
                'quiet': True,
                'no_warnings': True,
                'outtmpl': output_template,
                'socket_timeout': 30,
                'retries': 3,
                'fragment_retries': 3,
                'noplaylist': True,
                'http_headers': HEADERS,
            },
            {
                # Fallback profile for fragile social platforms
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '192',
                }],
                'ffmpeg_location': ffmpeg_path,
                'quiet': True,
                'no_warnings': True,
                'outtmpl': output_template,
                'socket_timeout': 45,
                'retries': 5,
                'fragment_retries': 5,
                'noplaylist': True,
                'http_headers': HEADERS,
            },
        ]

        for idx, ydl_opts in enumerate(attempt_options, start=1):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)

                    base = output_template.replace('.%(ext)s', '')
                    for ext in ['wav', 'mp3', 'ogg', 'opus', 'webm', 'm4a']:
                        candidate = f"{base}.{ext}"
                        if os.path.exists(candidate):
                            logger.info(f"Audio downloaded (attempt {idx}): {candidate}")
                            return candidate

                    prepared = ydl.prepare_filename(info)
                    wav_path = os.path.splitext(prepared)[0] + '.wav'
                    if os.path.exists(wav_path):
                        logger.info(f"Audio downloaded (attempt {idx}): {wav_path}")
                        return wav_path
                    if os.path.exists(prepared):
                        logger.info(f"Audio downloaded (attempt {idx}): {prepared}")
                        return prepared
            except Exception as e:
                logger.warning(f"Audio download attempt {idx} failed for {url}: {e}")

        logger.warning(f"Audio file not found after all download attempts for {url}")
        return None
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download)


async def transcribe_audio_file(audio_path: str) -> TranscriptionResult:
    """
    Transcribe a local audio file using faster-whisper.
    """
    def _transcribe():
        try:
            model = _load_whisper_model_sync()
            
            logger.info(f"Transcribing: {audio_path}")
            segments, info = model.transcribe(
                audio_path,
                language="en",
                beam_size=5,
            )
            
            transcript_parts = []
            for segment in segments:
                transcript_parts.append(segment.text.strip())
            
            transcript = " ".join(transcript_parts)
            
            logger.info(f"Transcription complete: {len(transcript)} chars")
            
            return TranscriptionResult(
                transcript=transcript,
                content_quality="full_transcript",
                language=info.language if hasattr(info, 'language') else "en",
                success=bool(transcript and len(transcript.strip()) > 10),
            )
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return TranscriptionResult(
                transcript="",
                content_quality="metadata_only",
                success=False,
                error=str(e),
            )
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _transcribe)


async def transcribe_short_video(url: str) -> str:
    """
    LOCAL TRANSCRIPTION: faster-whisper (synchronous, free, instant).
    For videos <5 minutes. Returns transcript text.
    """
    logger.info(f"[SHORT] Transcribing locally: {url}")
    
    audio_path = await download_audio(url)
    if not audio_path:
        raise RuntimeError(f"Audio download failed for {url}")
    
    try:
        result = await transcribe_audio_file(audio_path)
        if result.success:
            return result.transcript
        else:
            raise RuntimeError(f"Transcription produced no output: {result.error}")
    finally:
        # Cleanup
        try:
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception:
            pass


async def transcribe_url_full(url: str) -> TranscriptionResult:
    """
    Full transcription pipeline: download audio + transcribe.
    Returns TranscriptionResult with content_quality tracking.
    Used by the cognitive pipeline.
    """
    logger.info(f"Full transcription pipeline for: {url}")
    
    audio_path = await download_audio(url)
    if not audio_path:
        return TranscriptionResult(
            transcript="",
            content_quality="metadata_only",
            success=False,
            error="Audio download failed",
        )
    
    try:
        result = await transcribe_audio_file(audio_path)
        return result
    finally:
        try:
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception:
            pass


async def queue_long_video_job(
    url: str,
    user_id: str,
    db_session,
) -> str:
    """
    ASYNC TRANSCRIPTION: Queue job for background worker.
    For videos >5 minutes.
    Returns job_id for tracking.
    """
    from azure.storage.queue import QueueClient, BinaryBase64EncodePolicy
    
    logger.info(f"[LONG] Queueing async job: {url}")
    
    job_id = str(uuid.uuid4())
    
    try:
        # Check if Azure Queue is configured
        if not settings.AZURE_QUEUE_CONNECTION_STRING:
            logger.warning("[LONG] Azure Queue not configured, cannot queue job")
            return job_id
        
        queue_client = QueueClient.from_connection_string(
            settings.AZURE_QUEUE_CONNECTION_STRING,
            settings.AZURE_QUEUE_NAME
        )
        
        # Create message
        message_data = {
            'job_id': job_id,
            'url': url,
            'user_id': user_id,
            'type': 'video_transcription',
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        # Send to queue
        queue_client.send_message(json.dumps(message_data))
        logger.info(f"[LONG] ✅ Job queued: {job_id}")
        
        return job_id
    
    except Exception as e:
        logger.error(f"[LONG] ❌ Queue failed: {e}")
        raise


async def process_video(
    url: str,
    user_id: str,
    db_session,
) -> Dict[str, Any]:
    """
    MAIN ROUTER: Detect video length → route to local OR async.
    Returns metadata about processing decision.
    """
    logger.info(f"[ROUTER] Processing video: {url}")
    
    # Step 1: Get metadata (includes duration)
    metadata = await get_video_metadata(url)
    duration = metadata.get('duration_seconds', 600)
    
    logger.info(f"[ROUTER] Duration: {duration}s ({duration//60}m)")

    async def _paid_youtube_fallback() -> Optional[Dict[str, Any]]:
        """Try paid transcript providers for YouTube when local transcription fails."""
        platform = detect_platform(url)
        if platform != "youtube":
            return None

        video_id = None
        patterns = [
            r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})",
            r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
        ]
        for p in patterns:
            m = re.search(p, url)
            if m:
                video_id = m.group(1)
                break
        if not video_id:
            return None

        # Supadata
        if settings.SUPADATA_API_KEY:
            try:
                supa_url = f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}&text=true"
                resp = requests.get(supa_url, headers={"x-api-key": settings.SUPADATA_API_KEY}, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("content", "")
                    if content and len(content.strip()) > 40:
                        return {
                            'status': 'completed',
                            'job_id': None,
                            'transcript': content,
                            'transcript_length': len(content),
                            'transcript_source': 'supadata_api',
                            'duration': duration,
                            'metadata': metadata,
                            'message': '✅ Transcription complete via Supadata!',
                        }
            except Exception as e:
                logger.warning(f"[ROUTER] Supadata paid fallback failed: {e}")

        # Transcript24
        t24_key = getattr(settings, "TRANSCRIPT24_API_KEY", "")
        if t24_key:
            try:
                resp = requests.post(
                    "https://api.transcript24.com/v1/transcribe",
                    headers={"Authorization": f"Bearer {t24_key}"},
                    json={"url": url},
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("transcript", "")
                    if content and len(content.strip()) > 40:
                        return {
                            'status': 'completed',
                            'job_id': None,
                            'transcript': content,
                            'transcript_length': len(content),
                            'transcript_source': 'transcript24_api',
                            'duration': duration,
                            'metadata': metadata,
                            'message': '✅ Transcription complete via Transcript24!',
                        }
            except Exception as e:
                logger.warning(f"[ROUTER] Transcript24 paid fallback failed: {e}")

        return None
    
    # Step 2: Route based on duration
    if duration <= settings.SHORT_VIDEO_MAX_DURATION:
        # SHORT: Use local faster-whisper
        logger.info(f"[ROUTER] SHORT video ({duration}s): using local transcription")
        
        try:
            transcript = await transcribe_short_video(url)
            
            return {
                'status': 'completed',
                'job_id': None,
                'transcript': transcript,
                'transcript_length': len(transcript),
                'transcript_source': 'local',
                'duration': duration,
                'metadata': metadata,
                'message': '✅ Transcription complete!',
            }
        except Exception as e:
            logger.error(f"[ROUTER] Local transcription failed: {e}")

            paid = await _paid_youtube_fallback()
            if paid:
                return paid

            return {
                'status': 'failed',
                'error': str(e),
                'transcript_source': 'failed',
                'duration': duration,
                'metadata': metadata,
            }
    
    else:
        # LONG: Queue for async processing
        logger.info(f"[ROUTER] LONG video ({duration}s): queueing for async")
        
        try:
            job_id = await queue_long_video_job(url, user_id, db_session)
            
            return {
                'status': 'processing',
                'job_id': job_id,
                'transcript_source': 'async_queued',
                'duration': duration,
                'metadata': metadata,
                'message': f'🔄 Long video detected! Transcription in progress (Job: {job_id[:8]}...). You\'ll get an update on your dashboard!',
            }
        except Exception as e:
            logger.error(f"[ROUTER] Queue failed: {e}")
            return {
                'status': 'failed',
                'error': str(e),
                'transcript_source': 'failed',
                'duration': duration,
                'metadata': metadata,
            }


# Utility: Clean up old audio files
async def cleanup_temp_audio():
    """Periodically clean up downloaded audio files from temp dir."""
    import glob
    tmp_dir = tempfile.gettempdir()
    try:
        for pattern in ['thredion_audio_*.wav', 'thredion_audio_*.mp3', 'thredion_audio_*.ogg']:
            for f in glob.glob(os.path.join(tmp_dir, pattern)):
                try:
                    os.remove(f)
                    logger.info(f"Cleaned up: {f}")
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")
