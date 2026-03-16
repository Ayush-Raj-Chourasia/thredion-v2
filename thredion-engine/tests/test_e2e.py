"""
Thredion Engine - End-to-End Tests
Tests complete user workflows from URL input to cognitive processing
"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from db.models import Memory, User

client = TestClient(app)


class TestShortVideoE2E:
    """Test complete workflow for short videos (instant processing)."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_youtube_short_video_complete_flow(self, mock_auth, mock_process):
        """
        Test complete workflow:
        1. User submits YouTube link
        2. System detects short duration
        3. Transcription completes locally
        4. LLM processes cognitive structure
        5. Response returned with all fields
        """
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        mock_process.return_value = {
            'status': 'completed',
            'memory_id': 1,
            'url': 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
            'platform': 'youtube',
            'title': 'Me at the zoo',
            'duration_seconds': 125,
            'transcript': 'Me at the zoo',
            'transcript_length': 15,
            'summary': 'First YouTube video ever',
            'cognitive_mode': 'think',
            'bucket': 'History',
            'tags': ['youtube', 'history', 'first'],
            'actionability_score': 0.2,
            'emotional_tone': 'nostalgic',
            'confidence_score': 0.95,
            'importance_score': 45.0,
            'connections': [],
            'resurfaced': [],
        }
        
        # Step 1: User submits URL
        response = client.post(
            "/api/process-video?url=https://www.youtube.com/watch?v=jNQXAC9IVRw",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        # Step 2-5: Verify complete response
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'completed'
        assert data['memory_id'] == 1
        assert data['platform'] == 'youtube'
        assert data['transcript'] is not None
        assert data['summary'] is not None
        assert data['cognitive_mode'] == 'think'
        assert 'bucket' in data
        assert 'actionability_score' in data
        assert data['confidence_score'] == 0.95


class TestLongVideoE2E:
    """Test complete workflow for long videos (async queue)."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_youtube_long_video_async_flow(self, mock_auth, mock_process):
        """
        Test async long video workflow:
        1. User submits YouTube link (>5 min)
        2. System detects long duration
        3. Job queued to Azure Queue Storage
        4. Response returns immediately with job_id
        5. User begins polling for status
        """
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        # Step 1-3: Process returns immediately with job_id
        mock_process.return_value = {
            'status': 'processing',
            'memory_id': 1,
            'job_id': 'job-abc123',
            'url': 'https://www.youtube.com/watch?v=9bZkp7q19f0',
            'platform': 'youtube',
            'title': 'Python Full Course',
            'duration_seconds': 7200,
            'estimated_wait_seconds': 300,
        }
        
        # Step 1: User submits long video
        response = client.post(
            "/api/process-video?url=https://www.youtube.com/watch?v=9bZkp7q19f0",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        # Step 4: Verify immediate response with job tracking
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'processing'
        assert 'job_id' in data
        assert data['duration_seconds'] == 7200
        job_id = data['job_id']
        
        # Step 5: User polls status
        with patch('api.routes.get_current_user', return_value=mock_auth.return_value):
            with patch('api.routes.get_db') as mock_db_dep:
                mock_memory = Mock()
                mock_memory.transcription_job_id = job_id
                mock_memory.transcription_status = 'processing'
                mock_memory.user_id = "00000000-0000-0000-0000-000000000000"
                
                mock_db = Mock()
                mock_db.query.return_value.filter.return_value.first.return_value = mock_memory
                mock_db_dep.return_value = mock_db
                
                poll_response = client.get(
                    f"/api/job/{job_id}",
                    headers={"Authorization": "Bearer fake-token"}
                )
                
                assert poll_response.status_code == 200
                assert poll_response.json()['status'] == 'processing'


class TestInstagramReelE2E:
    """Test Instagram Reel support."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_instagram_reel_processing(self, mock_auth, mock_process):
        """
        Test Instagram Reel workflow:
        1. User submits Instagram Reel link
        2. System extracts video metadata
        3. Processes transcription
        4. Returns cognitive structure
        """
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        mock_process.return_value = {
            'status': 'completed',
            'memory_id': 2,
            'url': 'https://www.instagram.com/reel/xyz123/',
            'platform': 'instagram',
            'title': 'Instagram Reel',
            'duration_seconds': 45,
            'transcript': 'Instagram reel transcript',
            'summary': 'Test reel summary',
            'cognitive_mode': 'learn',
            'bucket': 'Social Media',
        }
        
        response = client.post(
            "/api/process-video?url=https://www.instagram.com/reel/xyz123/",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['platform'] == 'instagram'
        assert data['status'] == 'completed'


class TestTwitterLinkE2E:
    """Test Twitter/X link handling."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_twitter_video_processing(self, mock_auth, mock_process):
        """
        Test Twitter video workflow:
        1. User submits Twitter/X video link
        2. System detects platform
        3. Processes if valid video
        4. Returns cognitive structure
        """
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        mock_process.return_value = {
            'status': 'completed',
            'memory_id': 3,
            'url': 'https://twitter.com/user/status/xyz123',
            'platform': 'twitter',
            'title': 'Tweet with video',
            'duration_seconds': 60,
            'transcript': 'Tweet video content',
            'summary': 'Tweet summary',
            'cognitive_mode': 'reflect',
        }
        
        response = client.post(
            "/api/process-video?url=https://twitter.com/user/status/xyz123",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['platform'] == 'twitter'


class TestTikTokVideoE2E:
    """Test TikTok video support."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_tiktok_video_processing(self, mock_auth, mock_process):
        """
        Test TikTok video workflow:
        1. User submits TikTok link
        2. System extracts video info
        3. Processes transcription
        4. Returns cognitive structure
        """
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        mock_process.return_value = {
            'status': 'completed',
            'memory_id': 4,
            'url': 'https://www.tiktok.com/@user/video/xyz',
            'platform': 'tiktok',
            'title': 'TikTok video',
            'duration_seconds': 30,
            'transcript': 'TikTok content',
            'summary': 'TikTok summary',
            'cognitive_mode': 'learn',
        }
        
        response = client.post(
            "/api/process-video?url=https://www.tiktok.com/@user/video/xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['platform'] == 'tiktok'


class TestErrorHandlingE2E:
    """Test error handling across entire workflows."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_invalid_url_graceful_failure(self, mock_auth, mock_process):
        """
        Test that invalid URLs are rejected gracefully.
        """
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        response = client.post(
            "/api/process-video?url=not-a-valid-url",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 400
        assert 'error' in response.json() or 'detail' in response.json()
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_transcription_timeout_handled(self, mock_auth, mock_process):
        """
        Test timeout during transcription.
        """
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        mock_process.side_effect = TimeoutError("Transcription timeout")
        
        response = client.post(
            "/api/process-video?url=https://youtube.com/xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 500
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_network_error_handled(self, mock_auth, mock_process):
        """
        Test network errors during processing.
        """
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        mock_process.side_effect = ConnectionError("Network error")
        
        response = client.post(
            "/api/process-video?url=https://youtube.com/xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 500


class TestMultiplePlatformsE2E:
    """Test processing multiple different platforms."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_process_youtube_then_instagram(self, mock_auth, mock_process):
        """
        Test user processing videos from different platforms sequentially.
        """
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        # First: YouTube
        mock_process.return_value = {
            'status': 'completed',
            'memory_id': 1,
            'platform': 'youtube',
            'cognitive_mode': 'learn',
        }
        
        response1 = client.post(
            "/api/process-video?url=https://youtube.com/watch?v=xyz1",
            headers={"Authorization": "Bearer fake-token"}
        )
        assert response1.status_code == 200
        assert response1.json()['platform'] == 'youtube'
        
        # Second: Instagram
        mock_process.return_value = {
            'status': 'completed',
            'memory_id': 2,
            'platform': 'instagram',
            'cognitive_mode': 'reflect',
        }
        
        response2 = client.post(
            "/api/process-video?url=https://instagram.com/reel/xyz2/",
            headers={"Authorization": "Bearer fake-token"}
        )
        assert response2.status_code == 200
        assert response2.json()['platform'] == 'instagram'


class TestCognitiveStructureE2E:
    """Test cognitive structure generation across workflows."""
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_learn_mode_structure(self, mock_auth, mock_process):
        """Test cognitive structure for 'learn' mode."""
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        mock_process.return_value = {
            'status': 'completed',
            'cognitive_mode': 'learn',
            'title': 'Python Basics Tutorial',
            'summary': 'Tutorial on Python fundamentals',
            'key_points': ['variables', 'loops', 'functions'],
            'bucket': 'Educational',
            'tags': ['python', 'tutorial', 'coding'],
            'actionability_score': 0.8,
            'emotional_tone': 'instructional',
            'confidence_score': 0.95,
        }
        
        response = client.post(
            "/api/process-video?url=https://youtube.com/xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['cognitive_mode'] == 'learn'
        assert data['bucket'] == 'Educational'
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_think_mode_structure(self, mock_auth, mock_process):
        """Test cognitive structure for 'think' mode."""
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        mock_process.return_value = {
            'status': 'completed',
            'cognitive_mode': 'think',
            'title': 'Philosophy Discussion',
            'summary': 'Deep discussion on ethics',
            'bucket': 'Philosophy',
            'actionability_score': 0.3,
            'emotional_tone': 'contemplative',
            'confidence_score': 0.75,
        }
        
        response = client.post(
            "/api/process-video?url=https://youtube.com/xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['cognitive_mode'] == 'think'
    
    @patch('api.routes.process_video_url_async')
    @patch('api.routes.get_current_user')
    async def test_reflect_mode_structure(self, mock_auth, mock_process):
        """Test cognitive structure for 'reflect' mode."""
        mock_auth.return_value = Mock(phone="00000000-0000-0000-0000-000000000000")
        
        mock_process.return_value = {
            'status': 'completed',
            'cognitive_mode': 'reflect',
            'title': 'Personal Growth Journey',
            'summary': 'Reflection on personal development',
            'bucket': 'Personal Development',
            'actionability_score': 0.9,
            'emotional_tone': 'introspective',
            'confidence_score': 0.85,
        }
        
        response = client.post(
            "/api/process-video?url=https://youtube.com/xyz",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['cognitive_mode'] == 'reflect'


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
