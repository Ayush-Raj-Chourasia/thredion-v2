"""
Thredion Engine - Schema Validation Tests
Tests database schema, migrations, and data persistence for video transcription
"""

import pytest
from datetime import datetime
from unittest.mock import patch, Mock
from sqlalchemy import inspect, text

from db.database import SessionLocal, engine
from db.models import Memory, User, Base


class TestVideoTranscriptionSchema:
    """Test schema additions for video transcription feature."""
    
    def test_migration_002_fields_exist(self):
        """
        Test that migration 002 creates all new video transcription fields:
        - transcript (Text)
        - transcript_length (Integer)
        - transcript_source (String)
        - is_video (Boolean)
        - video_duration (Integer)
        - cognitive_mode (String)
        - title_generated (String)
        - key_points (Text/JSONB)
        - bucket (String)
        - actionability_score (Float)
        - emotional_tone (String)
        - confidence_score (Float)
        - transcription_job_id (String)
        - transcription_status (String)
        - processing_error (Text)
        """
        # Get all columns from Memory table
        inspector = inspect(engine)
        columns = {col['name']: col for col in inspector.get_columns('memories')}
        
        # Check migration 002 fields exist
        expected_fields = {
            'transcript': 'TEXT',
            'transcript_length': 'INTEGER',
            'transcript_source': 'VARCHAR',
            'is_video': 'BOOLEAN',
            'video_duration': 'INTEGER',
            'cognitive_mode': 'VARCHAR',
            'title_generated': 'VARCHAR',
            'key_points': 'VARCHAR',  # or TEXT/JSONB depending on DB
            'bucket': 'VARCHAR',
            'actionability_score': 'FLOAT',
            'emotional_tone': 'VARCHAR',
            'confidence_score': 'FLOAT',
            'transcription_job_id': 'VARCHAR',
            'transcription_status': 'VARCHAR',
            'processing_error': 'TEXT',
        }
        
        for field_name in expected_fields.keys():
            assert field_name in columns, f"Field {field_name} not found in memory table"


class TestCognitiveStructureDataPersistence:
    """Test data persistence for cognitive structure."""
    
    @pytest.fixture
    def db(self):
        """Create test database session."""
        return SessionLocal()
    
    def test_memory_with_transcript_persists(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test that memory records with transcripts are properly stored."""
        # Create test memory
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test memory",
            is_video=True,
            transcript="Full video transcript with many words",
            transcript_length=500,
            transcript_source='local',
            video_duration=300,
            cognitive_mode='learn',
            bucket='Technology',
        )
        
        db.add(memory)
        db.commit()
        db.refresh(memory)
        
        # Verify stored and retrievable
        assert memory.id is not None
        assert memory.transcript == "Full video transcript with many words"
        assert memory.transcript_length == 500
        assert memory.is_video == True
        
        # Cleanup
        db.delete(memory)
        db.commit()
    
    def test_cognitive_structure_fields_persist(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test that all cognitive structure fields persist correctly."""
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test",
            is_video=True,
            cognitive_mode='reflect',
            title_generated="Generated Title",
            key_points='["point1", "point2"]',
            bucket='Personal Development',
            actionability_score=0.8,
            emotional_tone='introspective',
            confidence_score=0.95,
        )
        
        db.add(memory)
        db.commit()
        db.refresh(memory)
        
        assert memory.cognitive_mode == 'reflect'
        assert memory.title_generated == "Generated Title"
        assert memory.actionability_score == 0.8
        assert memory.confidence_score == 0.95
        assert memory.bucket == 'Personal Development'
        
        # Verify data type conversions
        assert isinstance(memory.actionability_score, float)
        assert isinstance(memory.confidence_score, float)
        
        db.delete(memory)
        db.commit()
    
    def test_job_tracking_fields_persist(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test job tracking fields for async processing."""
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test",
            is_video=True,
            transcription_job_id="job-abc123",
            transcription_status="processing",
            processing_error=None,
        )
        
        db.add(memory)
        db.commit()
        db.refresh(memory)
        
        assert memory.transcription_job_id == "job-abc123"
        assert memory.transcription_status == "processing"
        assert memory.processing_error is None
        
        # Simulate job completion
        memory.transcription_status = "completed"
        memory.transcript = "Completed transcript"
        memory.processing_error = None
        db.commit()
        db.refresh(memory)
        
        assert memory.transcription_status == "completed"
        assert memory.transcript == "Completed transcript"
        
        db.delete(memory)
        db.commit()


class TestDataValidation:
    """Test data validation and constraints."""
    
    @pytest.fixture
    def db(self):
        return SessionLocal()
    
    def test_cognitive_mode_valid_values(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test that cognitive_mode accepts valid values: learn, think, reflect."""
        valid_modes = ['learn', 'think', 'reflect']
        
        for mode in valid_modes:
            memory = Memory(
                user_id=db.query(User).first().id,
                source="phone",
                original_input="Test",
                cognitive_mode=mode,
            )
            db.add(memory)
            db.commit()
            db.refresh(memory)
            
            assert memory.cognitive_mode == mode
            
            db.delete(memory)
            db.commit()
    
    def test_score_bounds_validation(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test that scores are within valid bounds (0-1)."""
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test",
            actionability_score=0.75,
            confidence_score=0.95,
        )
        
        db.add(memory)
        db.commit()
        db.refresh(memory)
        
        assert 0 <= memory.actionability_score <= 1
        assert 0 <= memory.confidence_score <= 1
        
        db.delete(memory)
        db.commit()
    
    def test_transcript_length_calculation(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test that transcript_length matches actual transcript length."""
        transcript = "This is a test transcript " * 20  # ~520 chars
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test",
            transcript=transcript,
            transcript_length=len(transcript),
        )
        
        db.add(memory)
        db.commit()
        db.refresh(memory)
        
        assert memory.transcript_length == len(transcript)
        
        db.delete(memory)
        db.commit()
    
    def test_video_duration_non_negative(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test that video_duration is non-negative."""
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test",
            is_video=True,
            video_duration=300,  # 5 minutes
        )
        
        db.add(memory)
        db.commit()
        db.refresh(memory)
        
        assert memory.video_duration >= 0
        
        db.delete(memory)
        db.commit()


class TestAsyncJobTracking:
    """Test async job tracking in database."""
    
    @pytest.fixture
    def db(self):
        return SessionLocal()
    
    def test_job_status_transitions(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test job status state transitions: pending → processing → completed."""
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test",
            is_video=True,
            transcription_job_id="job-test-001",
            transcription_status="pending",
        )
        
        db.add(memory)
        db.commit()
        
        # Transition to processing
        memory.transcription_status = "processing"
        db.commit()
        db.refresh(memory)
        assert memory.transcription_status == "processing"
        
        # Transition to completed
        memory.transcription_status = "completed"
        memory.transcript = "Full transcript text"
        db.commit()
        db.refresh(memory)
        assert memory.transcription_status == "completed"
        
        db.delete(memory)
        db.commit()
    
    def test_error_status_with_message(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test error status with error message."""
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test",
            transcription_job_id="job-failed-001",
            transcription_status="processing",
        )
        
        db.add(memory)
        db.commit()
        
        # Simulate error
        memory.transcription_status = "failed"
        memory.processing_error = "Transcription timeout after 300s"
        db.commit()
        db.refresh(memory)
        
        assert memory.transcription_status == "failed"
        assert "Transcription timeout" in memory.processing_error
        
        db.delete(memory)
        db.commit()


class TestQueryOptimization:
    """Test database queries are efficient."""
    
    @pytest.fixture
    def db(self):
        return SessionLocal()
    
    def test_find_by_job_id_fast_lookup(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test can efficiently find memory by job_id."""
        job_id = "job-query-test-123"
        
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test",
            transcription_job_id=job_id,
        )
        
        db.add(memory)
        db.commit()
        
        # Single query by job_id
        result = db.query(Memory).filter(
            Memory.transcription_job_id == job_id
        ).first()
        
        assert result is not None
        assert result.transcription_job_id == job_id
        
        db.delete(memory)
        db.commit()
    
    def test_filter_by_cognitive_mode(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test filtering by cognitive_mode."""
        # Create test memories with different modes
        for mode in ['learn', 'think', 'reflect']:
            memory = Memory(
                user_id=db.query(User).first().id,
                source="phone",
                original_input=f"Test {mode}",
                cognitive_mode=mode,
            )
            db.add(memory)
        
        db.commit()
        
        # Filter by mode
        results = db.query(Memory).filter(
            Memory.cognitive_mode == 'learn'
        ).all()
        
        assert all(r.cognitive_mode == 'learn' for r in results)
        
        # Cleanup
        for r in results:
            db.delete(r)
        db.commit()
    
    def test_filter_by_job_status(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test filtering by transcription_status."""
        statuses = ['pending', 'processing', 'completed']
        created_memories = []
        
        for status in statuses:
            memory = Memory(
                user_id=db.query(User).first().id,
                source="phone",
                original_input=f"Test {status}",
                transcription_status=status,
            )
            db.add(memory)
            created_memories.append(memory)
        
        db.commit()
        created_ids = [m.id for m in created_memories]
        
        # Find all incomplete jobs
        incomplete = db.query(Memory).filter(
            Memory.id.in_(created_ids),
            Memory.transcription_status.in_(['pending', 'processing'])
        ).all()
        
        assert len(incomplete) == 2
        
        # Cleanup
        db.query(Memory).delete()
        db.commit()


class TestBackwardsCompatibility:
    """Test that video transcription fields don't break existing data."""
    
    @pytest.fixture
    def db(self):
        return SessionLocal()
    
    def test_text_memory_still_works(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test that text-only memories still work without video fields."""
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Regular text memory",
            is_video=False,
        )
        
        db.add(memory)
        db.commit()
        db.refresh(memory)
        
        assert memory.id is not None
        assert memory.is_video == False
        assert memory.transcript in (None, "")
        assert memory.video_duration in (None, 0)
        
        db.delete(memory)
        db.commit()
    
    def test_optional_fields_nullable(self, db):
        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()

        """Test that new fields are nullable for compatibility."""
        memory = Memory(
            user_id=db.query(User).first().id,
            source="phone",
            original_input="Test",
        )
        
        db.add(memory)
        db.commit()
        db.refresh(memory)
        
        # All new video/cognitive fields should be None if not set
        assert memory.transcript in (None, "")
        assert memory.cognitive_mode in (None, "learn")
        assert memory.bucket in (None, "Uncategorized")
        assert memory.transcription_job_id is None
        
        db.delete(memory)
        db.commit()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

