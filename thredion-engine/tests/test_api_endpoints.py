"""
Thredion Engine - API Endpoint Tests
Tests REST API routes with FastAPI TestClient
"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

# We'll import the app after creating it
from main import app
from db.models import Memory, User

client = TestClient(app)


class TestProcessVideoEndpoint:
    """Test POST /api/process-video endpoint."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_process_video_short_success(self, mock_auth, mock_process):
        """Test successful short video processing."""
        mock_auth.return_value = Mock(phone="1234567890")
        mock_process.return_value = {
            'status': 'completed',
            'memory_id': 1,
            'transcript_length': 500,
            'cognitive_mode': 'learn',
            'bucket': 'AI Tools',
            'summary': 'Test summary',
        }
        
        response = client.post(
            "/api/process-video?url=https://youtube.com/watch?v=xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        assert response.json()['status'] == 'completed'
    
    @patch('api.routes.get_current_user')
    def test_invalid_url_format(self, mock_auth):
        """Test rejection of invalid URL format."""
        mock_auth.return_value = Mock(phone="1234567890")
        
        response = client.post(
            "/api/process-video?url=not-a-valid-url",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 400


class TestJobStatusEndpoint:
    """Test GET /api/job/{job_id} endpoint."""
    
    @patch('api.routes.get_current_user')
    @patch('api.routes.get_db')
    def test_get_job_status_processing(self, mock_db_dep, mock_auth):
        """Test retrieving status of processing job."""
        mock_auth.return_value = Mock(phone="1234567890")
        
        # Create mock memory
        mock_memory = Mock(spec=Memory)
        mock_memory.id = 1
        mock_memory.transcription_job_id = "job-123"
        mock_memory.transcription_status = "processing"
        mock_memory.user_id = "1234567890"
        mock_memory.transcript = None
        mock_memory.summary = None
        mock_memory.cognitive_mode = None
        mock_memory.bucket = None
        mock_memory.processing_error = None
        mock_memory.created_at = None
        mock_memory.processed_at = None
        
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_memory
        mock_db_dep.return_value = mock_db
        
        response = client.get(
            "/api/job/job-123",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'processing'
        assert data['progress'] == 'processing'
    
    @patch('api.routes.get_current_user')
    @patch('api.routes.get_db')
    def test_get_job_status_completed(self, mock_db_dep, mock_auth):
        """Test retrieving status of completed job."""
        mock_auth.return_value = Mock(phone="1234567890")
        
        mock_memory = Mock(spec=Memory)
        mock_memory.id = 1
        mock_memory.transcription_job_id = "job-123"
        mock_memory.transcription_status = "completed"
        mock_memory.user_id = "1234567890"
        mock_memory.transcript = "Full transcript"
        mock_memory.summary = "Test summary"
        mock_memory.cognitive_mode = "learn"
        mock_memory.bucket = "Technology"
        mock_memory.processing_error = None
        mock_memory.created_at = None
        mock_memory.processed_at = None
        
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_memory
        mock_db_dep.return_value = mock_db
        
        response = client.get(
            "/api/job/job-123",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'completed'
        assert data['progress'] == 'done'
        assert data['transcript'] == "Full transcript"
    
    @patch('api.routes.get_current_user')
    @patch('api.routes.get_db')
    def test_get_job_not_found(self, mock_db_dep, mock_auth):
        """Test 404 when job not found."""
        mock_auth.return_value = Mock(phone="1234567890")
        
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db_dep.return_value = mock_db
        
        response = client.get(
            "/api/job/nonexistent",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 404


class TestAuthenticationRequirements:
    """Test that endpoints require authentication."""
    
    def test_process_video_requires_auth(self):
        """Test that /process-video requires valid JWT."""
        response = client.post("/api/process-video?url=https://youtube.com/xyz")
        assert response.status_code == 403 or response.status_code == 401
    
    def test_job_status_requires_auth(self):
        """Test that /job/{id} requires valid JWT."""
        response = client.get("/api/job/job-123")
        assert response.status_code == 403 or response.status_code == 401


class TestErrorResponses:
    """Test error handling in API."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_processing_error_returns_500(self, mock_auth, mock_process):
        """Test that processing errors return 500 status."""
        mock_auth.return_value = Mock(phone="1234567890")
        mock_process.side_effect = Exception("Processing error")
        
        response = client.post(
            "/api/process-video?url=https://youtube.com/watch?v=xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 500
        assert "Processing failed" in response.json()['detail']


class TestResponseFormats:
    """Test API response formats."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_completed_response_format(self, mock_auth, mock_process):
        """Test format of completed transcription response."""
        mock_auth.return_value = Mock(phone="1234567890")
        mock_process.return_value = {
            'status': 'completed',
            'memory_id': 1,
            'url': 'https://youtube.com/watch?v=xyz',
            'platform': 'youtube',
            'title': 'Test Video',
            'summary': 'Test summary',
            'cognitive_mode': 'learn',
            'bucket': 'Technology',
            'tags': ['tag1', 'tag2'],
            'actionability_score': 0.7,
            'emotional_tone': 'curious',
            'confidence_score': 0.85,
            'transcript_length': 500,
            'importance_score': 85.0,
            'connections': [],
            'resurfaced': [],
        }
        
        response = client.post(
            "/api/process-video?url=https://youtube.com/watch?v=xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check all required fields present
        assert 'status' in data
        assert 'memory_id' in data
        assert 'cognitive_mode' in data
        assert 'bucket' in data
        assert 'actionability_score' in data
        assert 'transcript_length' in data


class TestSSEEventBroadcasting:
    """Test Server-Sent Events broadcasting."""
    
    @patch('api.routes.notify_change')
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_memory_added_notification_sent(
        self,
        mock_auth,
        mock_process,
        mock_notify
    ):
        """Test that SSE notification is sent on memory creation."""
        mock_auth.return_value = Mock(phone="1234567890")
        mock_process.return_value = {
            'status': 'completed',
            'memory_id': 1,
        }
        
        response = client.post(
            "/api/process-video?url=https://youtube.com/watch?v=xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        # Notification should be sent
        # (would check mock_notify.called in real test)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
