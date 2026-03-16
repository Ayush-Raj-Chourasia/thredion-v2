"""
Thredion Engine - Integration Tests
Tests complete pipeline: extraction → transcription → LLM → database
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime

from services.pipeline import process_video_url_async
from db.models import Memory
from sqlalchemy.orm import Session


class TestVideoProcessingPipeline:
    """Test complete video processing pipeline."""
    
    @pytest.mark.asyncio
    @patch('services.pipeline.extract_from_url')
    @patch('services.pipeline.process_video')
    @patch('services.pipeline.process_with_groq')
    @patch('services.pipeline.generate_embedding')
    @patch('services.pipeline.build_connections')
    @patch('services.pipeline.compute_importance')
    @patch('services.pipeline.find_resurfaceable')
    async def test_short_video_complete_pipeline(
        self,
        mock_resurface,
        mock_importance,
        mock_connections,
        mock_embedding,
        mock_llm,
        mock_transcribe,
        mock_extract,
        monkeypatch
    ):
        """Test complete pipeline for short video."""
        # Setup mocks
        mock_extract.return_value = MagicMock(
            platform="youtube",
            title="Test Video",
            content="Description",
            thumbnail_url="https://example.com/thumb.jpg",
            duration_seconds=180,
            is_video=True,
        )
        
        mock_transcribe.return_value = {
            'status': 'completed',
            'transcript': 'This is a test transcript',
            'transcript_length': 24,
            'transcript_source': 'local',
            'duration': 180,
        }
        
        mock_llm.return_value = MagicMock(
            cognitive_mode='learn',
            title='AI Discussion',
            summary='A discussion about AI',
            key_points=['Point 1', 'Point 2'],
            bucket='AI Tools',
            tags=['AI', 'Tech'],
            actionability_score=0.7,
            emotional_tone='curious',
            confidence_score=0.85,
        )
        
        mock_embedding.return_value = b'fake_embedding'
        mock_connections.return_value = []
        mock_importance.return_value = MagicMock(score=85.0, reasons=['reason1'])
        mock_resurface.return_value = []
        
        # Create mock database
        mock_db = MagicMock(spec=Session)
        mock_memory = MagicMock(spec=Memory)
        mock_memory.id = 1
        mock_memory.summary = 'A discussion about AI'
        mock_memory.key_points = '["Point 1", "Point 2"]'
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add = Mock()
        mock_db.commit = Mock()
        mock_db.refresh = Mock()
        
        # Mock commit to update the memory object
        def update_memory(*args, **kwargs):
            mock_memory.transcript = 'This is a test transcript'
            mock_memory.transcript_length = 24
            mock_memory.transcript_source = 'local'
            mock_memory.cognitive_mode = 'learn'
            mock_memory.title_generated = 'AI Discussion'
            mock_memory.summary = 'A discussion about AI'
            mock_memory.key_points = '["Point 1", "Point 2"]'
            mock_memory.bucket = 'AI Tools'
            mock_memory.tags = '["AI", "Tech"]'
            mock_memory.actionability_score = 0.7
            mock_memory.emotional_tone = 'curious'
            mock_memory.confidence_score = 0.85
            mock_memory.processed_at = datetime.utcnow()
        
        mock_db.commit.side_effect = update_memory
        
        # Patch Memory creation
        with patch('services.pipeline.Memory', return_value=mock_memory):
            result = await process_video_url_async(
                "https://youtube.com/watch?v=xyz",
                "00000000-0000-0000-0000-000000000000",
                mock_db
            )
        
        # Assertions
        assert result['status'] == 'completed'
        assert result['cognitive_mode'] == 'learn'
        assert result['bucket'] == 'AI Tools'
        assert result['actionability_score'] == 0.7
        assert result['transcript_length'] == 24


class TestDuplicateDetection:
    """Test duplicate URL detection."""
    
    @pytest.mark.asyncio
    async def test_duplicate_url_returns_existing_memory(self):
        """Test that duplicate URLs return existing memory instead of reprocessing."""
        # Create mock existing memory
        existing_memory = MagicMock(spec=Memory)
        existing_memory.id = 42
        existing_memory.title = "Existing Title"
        existing_memory.summary = "Existing summary"
        
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = existing_memory
        
        with patch('services.pipeline.Memory'):
            result = await process_video_url_async(
                "https://youtube.com/watch?v=xyz",
                "00000000-0000-0000-0000-000000000000",
                mock_db
            )
        
        assert result['duplicate'] == True
        assert result['memory_id'] == 42


class TestPipelineErrorHandling:
    """Test error handling throughout pipeline."""
    
    @pytest.mark.asyncio
    @patch('services.pipeline.extract_from_url')
    async def test_invalid_url_raises_error(self, mock_extract):
        """Test that invalid URL raises appropriate error."""
        mock_db = MagicMock(spec=Session)
        
        with pytest.raises(ValueError):
            await process_video_url_async("   ", "00000000-0000-0000-0000-000000000000", mock_db)


class TestMemoryDatabaseIntegration:
    """Test database persistence."""
    
    @pytest.mark.asyncio
    @patch('services.pipeline.extract_from_url')
    @patch('services.pipeline.process_video')
    @patch('services.pipeline.process_with_groq')
    async def test_memory_record_saved_with_transcript(
        self,
        mock_llm,
        mock_transcribe,
        mock_extract
    ):
        """Test that complete memory record is saved to database."""
        mock_extract.return_value = MagicMock(
            platform="youtube",
            title="Test",
            content="Test",
            thumbnail_url="",
            duration_seconds=100,
        )
        
        mock_transcribe.return_value = {
            'status': 'completed',
            'transcript': 'Full transcript text',
            'transcript_length': 18,
            'transcript_source': 'local',
        }
        
        mock_llm.return_value = MagicMock(
            cognitive_mode='learn',
            title='Title',
            summary='Summary',
            key_points=[],
            bucket='Tech',
            tags=[],
            actionability_score=0.5,
            emotional_tone='neutral',
            confidence_score=0.9,
        )
        
        mock_db = MagicMock(spec=Session)
        mock_memory = MagicMock(spec=Memory)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add = Mock()
        mock_db.commit = Mock()
        mock_db.refresh = Mock()
        
        with patch('services.pipeline.Memory', return_value=mock_memory):
            with patch('services.pipeline.generate_embedding', return_value=b'emb'):
                with patch('services.pipeline.build_connections', return_value=[]):
                    with patch('services.pipeline.compute_importance', return_value=MagicMock(score=50, reasons=[])):
                        with patch('services.pipeline.find_resurfaceable', return_value=[]):
                            result = await process_video_url_async(
                                "https://youtube.com/watch?v=xyz",
                                "00000000-0000-0000-0000-000000000000",
                                mock_db
                            )
        
        # Verify memory was saved
        assert mock_db.add.called
        assert mock_db.commit.call_count >= 1


class TestLongVideoQueueing:
    """Test async queuing for long videos."""
    
    @pytest.mark.asyncio
    @patch('services.pipeline.extract_from_url')
    @patch('services.pipeline.process_video')
    async def test_long_video_returns_job_id(
        self,
        mock_transcribe,
        mock_extract
    ):
        """Test that long videos return job ID for tracking."""
        mock_extract.return_value = MagicMock(
            platform="youtube",
            title="Long Video",
            content="Description",
            thumbnail_url="",
            duration_seconds=2000,  # >5 min
        )
        
        mock_transcribe.return_value = {
            'status': 'processing',
            'job_id': 'job-123-abc',
            'transcript_source': 'async_queued',
            'duration': 2000,
            'message': 'Processing...',
        }
        
        mock_db = MagicMock(spec=Session)
        mock_memory = MagicMock(spec=Memory)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add = Mock()
        mock_db.commit = Mock()
        mock_db.refresh = Mock()
        
        with patch('services.pipeline.Memory', return_value=mock_memory):
            result = await process_video_url_async(
                "https://youtube.com/watch?v=long",
                "00000000-0000-0000-0000-000000000000",
                mock_db
            )
        
        assert result['status'] == 'processing'
        assert result['job_id'] == 'job-123-abc'


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
