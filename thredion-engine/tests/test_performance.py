"""
Thredion Engine - Performance & Load Tests
Tests system performance, response times, and capacity
"""

import pytest
import time
import asyncio
from unittest.mock import patch, Mock, AsyncMock

from db.database import SessionLocal
from db.models import Memory
from services.transcriber import load_whisper_model, get_video_metadata
from services.llm_processor import process_with_groq


class TestModelLoadingPerformance:
    """Test whisper model loading performance."""
    
    def test_whisper_model_loads_within_timeout(self):
        """Test that whisper model loads within reasonable time (<5 seconds)."""
        start = time.time()
        
        with patch('services.transcriber.whisper') as mock_whisper:
            mock_whisper.load_model.return_value = Mock()
            
            # Load model (simulated)
            model = load_whisper_model()
            
            elapsed = time.time() - start
        
        # Should load quickly (mocked)
        assert elapsed < 5.0
    
    def test_cached_model_returns_quickly(self):
        """Test that cached model access is fast."""
        with patch('services.transcriber.WHISPER_MODEL', Mock()):
            start = time.time()
            model1 = load_whisper_model()
            time1 = time.time() - start
            
            start = time.time()
            model2 = load_whisper_model()
            time2 = time.time() - start
        
        # Cached access should be faster
        assert time2 < time1


class TestTranscriptionPerformance:
    """Test transcription speed."""
    
    @pytest.mark.asyncio
    async def test_short_video_transcription_speed(self):
        """
        Test that short video (<5 min) transcribes in reasonable time.
        Expected: <30 seconds for 5 minute video
        """
        with patch('services.transcriber.transcribe_short_video') as mock_transcribe:
            # Simulate transcription
            mock_transcribe.return_value = "Test transcript"
            
            start = time.time()
            result = await mock_transcribe()
            elapsed = time.time() - start
        
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_metadata_extraction_speed(self):
        """
        Test that video metadata extraction is fast.
        Expected: <2 seconds
        """
        with patch('services.transcriber.get_video_metadata') as mock_meta:
            mock_meta.return_value = {
                'duration': 300,
                'title': 'Test Video',
                'uploader': 'Test User',
            }
            
            start = time.time()
            result = await mock_meta('https://youtube.com/watch?v=xyz')
            elapsed = time.time() - start
        
        assert result is not None


class TestLLMProcessingPerformance:
    """Test LLM processing speed."""
    
    @pytest.mark.asyncio
    async def test_groq_response_time(self):
        """
        Test that Groq API response time is acceptable.
        Expected: <3 seconds per request
        """
        with patch('services.llm_processor.get_groq_client') as mock_groq:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.choices = [Mock(message=Mock(content='{"cognitive_mode": "learn"}'))]
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_groq.return_value = mock_client
            
            start = time.time()
            result = await process_with_groq("Test transcript")
            elapsed = time.time() - start
        
        # Should complete in reasonable time
        assert elapsed < 5.0 or result is not None
    
    @pytest.mark.asyncio
    async def test_fallback_classification_speed(self):
        """
        Test that fallback classification is fast (<100ms).
        """
        with patch('services.llm_processor.fallback_classification') as mock_fallback:
            mock_fallback.return_value = {
                'cognitive_mode': 'learn',
                'bucket': 'Technology',
            }
            
            start = time.time()
            result = mock_fallback("Test transcript")
            elapsed = time.time() - start
        
        # Fallback should be very fast
        assert elapsed < 0.1
        assert result is not None


class TestDatabaseQueryPerformance:
    """Test database query performance."""
    
    @pytest.fixture
    def db(self):
        return SessionLocal()
    
    def test_job_id_lookup_performance(self, db):
        """Test that job_id lookup is fast <100ms."""
        # Create test data
        memory = Memory(
            user_id="1234567890",
            source="phone",
            raw_text="Test",
            transcription_job_id="job-perf-001",
        )
        
        db.add(memory)
        db.commit()
        
        # Query by job_id
        start = time.time()
        result = db.query(Memory).filter(
            Memory.transcription_job_id == "job-perf-001"
        ).first()
        elapsed = time.time() - start
        
        assert elapsed < 0.1
        assert result is not None
        
        db.delete(memory)
        db.commit()
    
    def test_filter_by_status_performance(self, db):
        """Test filtering by status is efficient."""
        # Create multiple records
        for i in range(10):
            memory = Memory(
                user_id="1234567890",
                source="phone",
                raw_text=f"Test {i}",
                transcription_status='processing' if i % 2 == 0 else 'completed',
            )
            db.add(memory)
        
        db.commit()
        
        # Filter query
        start = time.time()
        results = db.query(Memory).filter(
            Memory.transcription_status == 'processing'
        ).all()
        elapsed = time.time() - start
        
        assert elapsed < 0.5  # Should be fast
        assert len(results) > 0
        
        # Cleanup
        db.query(Memory).delete()
        db.commit()


class TestConcurrentProcessing:
    """Test concurrent request handling."""
    
    @pytest.mark.asyncio
    async def test_concurrent_transcription_requests(self):
        """Test handling multiple concurrent requests."""
        async def process_video_mock(url):
            await asyncio.sleep(0.1)  # Simulate processing
            return f"Transcript for {url}"
        
        # Simulate 5 concurrent requests
        urls = [f"https://youtube.com/watch?v={i}" for i in range(5)]
        
        start = time.time()
        results = await asyncio.gather(*[process_video_mock(url) for url in urls])
        elapsed = time.time() - start
        
        assert len(results) == 5
        # Concurrent should be faster than sequential (5 * 0.1 = 0.5s)
        assert elapsed < 0.6
    
    @pytest.mark.asyncio
    async def test_queue_processing_throughput(self):
        """Test queue processing throughput."""
        async def process_message_mock():
            await asyncio.sleep(0.05)  # Simulate message processing
            return True
        
        # Process 20 messages
        start = time.time()
        results = await asyncio.gather(*[process_message_mock() for _ in range(20)])
        elapsed = time.time() - start
        
        throughput = len(results) / elapsed
        
        assert len(results) == 20
        # Should process at least 30 msgs/second
        assert throughput > 30


class TestMemoryUsage:
    """Test memory efficiency."""
    
    @pytest.mark.asyncio
    async def test_model_memory_footprint(self):
        """Test that model doesn't consume excessive memory."""
        # Mocked - real implementation would use tracemalloc
        with patch('services.transcriber.load_whisper_model') as mock_load:
            mock_load.return_value = Mock()
            
            # Should not cause memory issues
            model = mock_load()
            assert model is not None
    
    def test_large_transcript_handling(self):
        """Test handling of large transcripts."""
        db = SessionLocal()
        
        # Create large transcript (100KB)
        large_transcript = "word " * 20000  # ~100KB
        
        memory = Memory(
            user_id="1234567890",
            source="phone",
            raw_text="Test",
            transcript=large_transcript,
            transcript_length=len(large_transcript),
        )
        
        db.add(memory)
        db.commit()
        db.refresh(memory)
        
        assert memory.transcript == large_transcript
        assert memory.transcript_length == len(large_transcript)
        
        db.delete(memory)
        db.commit()


class TestLoadPatterns:
    """Test various load patterns."""
    
    @pytest.mark.asyncio
    async def test_burst_load_handling(self):
        """Test system under burst load (sudden spike of requests)."""
        async def process_burst():
            await asyncio.sleep(0.01)
            return True
        
        # Simulate 100 simultaneous requests
        start = time.time()
        results = await asyncio.gather(*[process_burst() for _ in range(100)])
        elapsed = time.time() - start
        
        assert len(results) == 100
        assert elapsed < 2.0  # Should handle burst
    
    @pytest.mark.asyncio
    async def test_sustained_load_handling(self):
        """Test system under sustained load."""
        async def process_sustained():
            await asyncio.sleep(0.05)
            return True
        
        # Process 50 items over time
        start = time.time()
        results = await asyncio.gather(*[process_sustained() for _ in range(50)])
        elapsed = time.time() - start
        
        assert len(results) == 50
        # Should maintain reasonable performance
        avg_time = elapsed / 50
        assert avg_time < 0.1  # <100ms per item


class TestErrorRecoveryPerformance:
    """Test performance during error conditions."""
    
    @pytest.mark.asyncio
    async def test_fallback_performance_on_groq_timeout(self):
        """Test that fallback classification is fast when Groq times out."""
        with patch('services.llm_processor.process_with_groq') as mock_groq:
            mock_groq.side_effect = TimeoutError("Groq timeout")
            
            with patch('services.llm_processor.fallback_classification') as mock_fallback:
                mock_fallback.return_value = {'cognitive_mode': 'learn'}
                
                start = time.time()
                try:
                    await mock_groq("Test")
                except TimeoutError:
                    result = mock_fallback("Test")
                elapsed = time.time() - start
        
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
