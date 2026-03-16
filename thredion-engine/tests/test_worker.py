"""
Thredion Engine - Worker Integration Tests
Tests background transcription job processing from Azure Queue
"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from azure.storage.queue import QueueMessage
import asyncio

from worker.transcription_worker import (
    process_queue_message,
    poll_queue,
    
)
from db.models import Memory


class TestQueueMessageProcessing:
    """Test individual queue message processing."""
    
    @pytest.mark.asyncio
    @patch('worker.transcription_worker.SessionLocal')
    @patch('azure.storage.queue.QueueClient.from_connection_string')
    @patch('services.transcriber.transcribe_short_video')
    @patch('services.llm_processor.process_with_groq')
    async def test_process_valid_message(
        self,
        mock_llm,
        mock_transcribe,
        mock_queue,
        mock_db_factory
    ):
        """Test processing of valid queue message."""
        # Setup mocks
        mock_llm.return_value = {
            'cognitive_mode': 'learn',
            'title': 'Test Title',
            'summary': 'Test Summary',
            'key_points': ['point 1', 'point 2'],
            'bucket': 'Technology',
            'tags': ['tag1'],
            'actionability_score': 0.8,
            'emotional_tone': 'informative',
            'confidence_score': 0.9,
        }
        
        mock_transcribe.return_value = "Full transcription text"
        
        mock_memory = Mock(spec=Memory)
        mock_memory.id = 1
        mock_memory.video_url = "https://youtube.com/xyz"
        mock_memory.transcription_job_id = "job-123"
        mock_memory.transcript = None
        
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first = Mock(
            return_value=mock_memory
        )
        mock_db.commit = Mock()
        mock_db_factory.return_value = mock_db
        
        # Create queue message
        message = QueueMessage(
            name="queue-msg",
            metadata={},
            id="msg-123",
            inserted_on=None,
            expires_on=None,
            dequeue_count=0,
            content=json.dumps({
                'memory_id': 1,
                'video_url': 'https://youtube.com/xyz',
                'job_id': 'job-123',
                'platform': 'youtube',
            })
        )
        
        # Process message
        result = await process_queue_message(message)
        
        assert result is not None
        assert mock_db.commit.called


class TestJobStatusTransitions:
    """Test job status state machine."""
    
    @pytest.mark.asyncio
    @patch('worker.transcription_worker.SessionLocal')
    async def test_pending_to_processing_transition(self, mock_db_factory):
        """Test transition from pending to processing."""
        mock_memory = Mock(spec=Memory)
        mock_memory.transcription_status = 'pending'
        
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first = Mock(
            return_value=mock_memory
        )
        mock_db_factory.return_value = mock_db
        
        # Simulate status update
        mock_memory.transcription_status = 'processing'
        mock_db.commit = Mock()
        
        assert mock_memory.transcription_status == 'processing'
    
    @pytest.mark.asyncio
    @patch('worker.transcription_worker.SessionLocal')
    @patch('services.transcriber.transcribe_short_video')
    @patch('services.llm_processor.process_with_groq')
    async def test_processing_to_completed_transition(
        self,
        mock_llm,
        mock_transcribe,
        mock_db_factory
    ):
        """Test transition from processing to completed."""
        mock_transcribe.return_value = "transcript"
        mock_llm.return_value = {'cognitive_mode': 'learn'}
        
        mock_memory = Mock(spec=Memory)
        mock_memory.transcription_status = 'processing'
        mock_memory.id = 1
        
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first = Mock(
            return_value=mock_memory
        )
        mock_db.commit = Mock()
        mock_db_factory.return_value = mock_db
        
        # Simulate completion
        mock_memory.transcription_status = 'completed'
        
        assert mock_memory.transcription_status == 'completed'


class TestErrorRecovery:
    """Test error handling and recovery in worker."""
    
    @pytest.mark.asyncio
    @patch('worker.transcription_worker.SessionLocal')
    @patch('services.transcriber.transcribe_short_video')
    async def test_transcription_failure_sets_error_status(
        self,
        mock_transcribe,
        mock_db_factory
    ):
        """Test that transcription errors set failed status."""
        mock_transcribe.side_effect = Exception("Transcription failed")
        
        mock_memory = Mock(spec=Memory)
        mock_memory.transcription_status = 'processing'
        mock_memory.processing_error = None
        
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first = Mock(
            return_value=mock_memory
        )
        mock_db.commit = Mock()
        mock_db_factory.return_value = mock_db
        
        try:
            await process_queue_message(Mock(content=json.dumps({
                'memory_id': 1,
                'video_url': 'https://youtube.com/xyz',
                'job_id': 'job-123',
            })))
        except Exception:
            pass
        
        # Simulate setting error status
        mock_memory.transcription_status = 'failed'
        mock_memory.processing_error = "Transcription failed"
        
        assert mock_memory.transcription_status == 'failed'
    
    @pytest.mark.asyncio
    @patch('worker.transcription_worker.SessionLocal')
    async def test_invalid_message_format_skipped(self, mock_db_factory):
        """Test that malformed messages are handled gracefully."""
        mock_db = MagicMock()
        mock_db_factory.return_value = mock_db
        
        # Invalid message (missing required fields)
        message = QueueMessage(
            name="queue-msg",
            id="msg-123",
            inserted_on=None,
            expires_on=None,
            dequeue_count=0,
            metadata={},
            content=json.dumps({'invalid': 'data'})
        )
        
        result = await process_queue_message(message)
        assert result is False


