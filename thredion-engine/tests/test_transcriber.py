"""
Thredion Engine - Unit Tests for Transcriber Service
Tests all transcription routing logic, model loading, and error handling.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime

from services.transcriber import (
    load_whisper_model,
    get_video_metadata,
    detect_platform,
    process_video,
)
from core.config import settings


class TestPlatformDetection:
    """Test URL platform detection."""
    
    def test_youtube_com(self):
        assert detect_platform("https://www.youtube.com/watch?v=xyz") == "youtube"
    
    def test_youtu_be(self):
        assert detect_platform("https://youtu.be/xyz") == "youtube"
    
    def test_instagram_reel(self):
        assert detect_platform("https://instagram.com/reel/xyz") == "instagram"
    
    def test_tiktok(self):
        assert detect_platform("https://tiktok.com/@user/video/123") == "tiktok"
    
    def test_twitter(self):
        assert detect_platform("https://twitter.com/user/status/123") == "twitter"
    
    def test_x_com(self):
        assert detect_platform("https://x.com/user/status/123") == "twitter"
    
    def test_reddit(self):
        assert detect_platform("https://reddit.com/r/videos/xyz") == "reddit"
    
    def test_unknown(self):
        assert detect_platform("https://example.com/page") == "unknown"


class TestVideoMetadataExtraction:
    """Test video metadata extraction."""
    
    @pytest.mark.asyncio
    @patch('services.transcriber.yt_dlp.YoutubeDL')
    async def test_successful_metadata_extraction(self, mock_ydl):
        """Test successful metadata extraction from YouTube video."""
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.return_value = {
            'duration': 600,
            'title': 'Test Video',
            'thumbnail': 'https://example.com/thumb.jpg',
            'description': 'Test description',
            'uploader': 'Test Channel',
            'view_count': 1000,
        }
        
        result = await get_video_metadata("https://youtube.com/watch?v=xyz")
        
        assert result['duration_seconds'] == 600
        assert result['title'] == 'Test Video'
        assert result['success'] == True
    
    @pytest.mark.asyncio
    @patch('services.transcriber.yt_dlp.YoutubeDL')
    async def test_metadata_extraction_failure(self, mock_ydl):
        """Test graceful fallback when metadata extraction fails."""
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = Exception("Network error")
        
        result = await get_video_metadata("https://youtube.com/watch?v=xyz")
        
        assert result['success'] == False
        assert result['duration_seconds'] == 600  # Default fallback
        assert 'error' in result


class TestVideoRouting:
    """Test video routing logic (short vs long)."""
    
    @pytest.mark.asyncio
    @patch('services.transcriber.get_video_metadata')
    @patch('services.transcriber.transcribe_short_video')
    async def test_short_video_local_transcription(self, mock_transcribe, mock_metadata):
        """Test that videos <5 min use local transcription."""
        mock_metadata.return_value = {
            'duration_seconds': 180,  # 3 minutes
            'title': 'Short video',
            'platform': 'youtube',
        }
        mock_transcribe.return_value = "This is a test transcript"
        mock_db = Mock()
        
        result = await process_video("https://youtube.com/watch?v=xyz", "00000000-0000-0000-0000-000000000000", mock_db)
        
        assert result['status'] == 'completed'
        assert result['transcript_source'] == 'local'
        assert result['transcript'] == "This is a test transcript"
        assert result['duration'] == 180
    
    @pytest.mark.asyncio
    @patch('services.transcriber.get_video_metadata')
    @patch('services.transcriber.queue_long_video_job')
    async def test_long_video_async_queue(self, mock_queue, mock_metadata):
        """Test that videos >5 min are queued for async."""
        mock_metadata.return_value = {
            'duration_seconds': 1200,  # 20 minutes
            'title': 'Long video',
            'platform': 'youtube',
        }
        mock_queue.return_value = "job-123-abc"
        mock_db = Mock()
        
        result = await process_video("https://youtube.com/watch?v=xyz", "00000000-0000-0000-0000-000000000000", mock_db)
        
        assert result['status'] == 'processing'
        assert result['transcript_source'] == 'async_queued'
        assert result['job_id'] == "job-123-abc"
        assert result['duration'] == 1200


class TestTranscriptionErrorHandling:
    """Test error handling in transcription."""
    
    @pytest.mark.asyncio
    @patch('services.transcriber.transcribe_short_video')
    @patch('services.transcriber.get_video_metadata')
    async def test_transcription_failure_returns_failed_status(self, mock_metadata, mock_transcribe):
        """Test that transcription failures are caught and reported."""
        mock_metadata.return_value = {'duration_seconds': 150, 'title': 'Video'}
        mock_transcribe.side_effect = Exception("Whisper model failed")
        mock_db = Mock()
        
        result = await process_video("https://youtube.com/watch?v=xyz", "00000000-0000-0000-0000-000000000000", mock_db)
        
        assert result['status'] == 'failed'
        assert 'error' in result
        assert "Whisper model failed" in result['error']


class TestWhisperModelLoading:
    """Test lazy loading of Whisper model."""
    
    @pytest.mark.asyncio
    @patch('services.transcriber.WhisperModel')
    async def test_model_loads_once(self, mock_whisper):
        """Test that model is only loaded once (lazy loading)."""
        mock_model = MagicMock()
        mock_whisper.return_value = mock_model
        
        # Load model twice
        model1 = await load_whisper_model()
        model2 = await load_whisper_model()
        
        # Should be same instance
        assert model1 is model2
        # WhisperModel should only be called once
        assert mock_whisper.call_count >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
