"""
Thredion Engine — Database Models
SQLAlchemy ORM models for the cognitive memory engine aligned with Supabase PostgreSQL schema.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, String, Float, Text, DateTime, LargeBinary, ForeignKey,
    UniqueConstraint, Integer, JSON
)
import sqlalchemy.types as types
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship
from db.database import Base

# Safe JSON type that creates JSONB on postgres but normal JSON on SQLite
SafeJSON = JSON().with_variant(JSONB, 'postgresql')

class GUID(types.TypeDecorator):
    """Platform-independent GUID type."""
    impl = types.String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(types.String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name != "postgresql":
            # SQLite tests may use legacy non-UUID ids.
            return str(value)
        if not isinstance(value, uuid.UUID):
            return "%.32x" % uuid.UUID(str(value)).int
        return "%.32x" % value.int

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if dialect.name != "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(value)
        return value

def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    """A registered user, identified by their WhatsApp phone number."""
    __tablename__ = "users"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    phone_number = Column(String(50), unique=True, nullable=False, index=True)
    username = Column(String(200), default="")
    email = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Backwards compatibility alias for older code using .phone
    @property
    def phone(self):
        return self.phone_number
    
    @phone.setter
    def phone(self, value):
        self.phone_number = value


class OTPCode(Base):
    """Temporary OTP codes sent via WhatsApp for authentication."""
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, index=True) # Likely still integer or matches users
    phone = Column(String(50), nullable=False, index=True)
    code = Column(String(6), nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class Memory(Base):
    """A single cognitive memory — a saved link with AI-enriched metadata."""
    __tablename__ = "memories"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, default="test")
    
    source = Column(String(50), default="unknown")       # instagram, twitter, article, youtube
    source_url = Column(String(2048), nullable=True, index=True)
    original_input = Column(Text, nullable=False, default="")
    cleaned_text = Column(Text, default="")
    processing_status = Column(String(20), default="pending")  # pending|processing|completed|failed
    
    title = Column(String(512), default="")
    summary = Column(Text, default="")
    key_points = Column(SafeJSON, default=[])
    category = Column(String(100), default="Uncategorized")
    tags = Column(SafeJSON, default=[])
    importance_score = Column(Float, default=50.0)
    importance_reasons = Column(SafeJSON, default=[])
    embedding = Column(LargeBinary, nullable=True) # bytea in postgres
    
    resurfaced_count = Column(Integer, default=0)
    last_resurfaced_at = Column(DateTime(timezone=True), nullable=True)
    
    # Video Transcription & Job fields
    transcript = Column(Text, default="")
    transcript_length = Column(Integer, default=0)
    transcript_source = Column(String(20), default="pending")
    video_duration = Column(Integer, default=0)
    is_video = Column(Boolean, default=False)
    
    # Extra Cognitive fields
    cognitive_mode = Column(String(20), default="learn")
    title_generated = Column(String(512), default="")
    bucket = Column(String(100), default="Uncategorized")
    actionability_score = Column(Float, default=0.0)
    emotional_tone = Column(String(50), default="")
    confidence_score = Column(Float, default=0.0)

    # Job tracking
    transcription_job_id = Column(String(100), nullable=True, index=True)
    transcription_status = Column(String(20), default="pending", index=True)
    processing_error = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    connections_out = relationship(
        "Connection",
        foreign_keys="Connection.source_id",
        back_populates="source_memory",
        cascade="all, delete-orphan",
    )
    connections_in = relationship(
        "Connection",
        foreign_keys="Connection.target_id",
        back_populates="target_memory",
        cascade="all, delete-orphan",
    )

    # Aliases for compatibility
    @property
    def url(self):
        return self.source_url

    @url.setter
    def url(self, value):
        self.source_url = value
    
    @property
    def content(self):
        return self.original_input

    @content.setter
    def content(self, value):
        self.original_input = value

    @property
    def raw_text(self):
        return self.original_input

    @raw_text.setter
    def raw_text(self, value):
        self.original_input = value

    @property
    def platform(self):
        return self.source

    @platform.setter
    def platform(self, value):
        self.source = value

    @property
    def topic_graph(self):
        return getattr(self, "_topic_graph", "[]")

    @topic_graph.setter
    def topic_graph(self, value):
        self._topic_graph = value

    @property
    def thumbnail_url(self):
        return getattr(self, "_thumbnail_url", "")

    @thumbnail_url.setter
    def thumbnail_url(self, value):
        self._thumbnail_url = value or ""


class Connection(Base):
    """An edge in the knowledge graph — links two related memories."""
    __tablename__ = "connections"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, default="test")
    source_id = Column(GUID, ForeignKey("memories.id", ondelete="CASCADE"), nullable=False)
    target_id = Column(GUID, ForeignKey("memories.id", ondelete="CASCADE"), nullable=False)
    similarity_score = Column(Float, nullable=False, default=0.0)
    connection_type = Column(String(50), default="similar")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    source_memory = relationship("Memory", foreign_keys=[source_id], back_populates="connections_out")
    target_memory = relationship("Memory", foreign_keys=[target_id], back_populates="connections_in")


class ResurfacedMemory(Base):
    """Tracks when an older memory is resurfaced because a new one is similar."""
    __tablename__ = "resurfaced_memories"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, default="test")
    memory_id = Column(GUID, ForeignKey("memories.id", ondelete="CASCADE"), nullable=False)
    triggered_by_id = Column(GUID, ForeignKey("memories.id", ondelete="CASCADE"), nullable=True)
    resurfaced_at = Column(DateTime(timezone=True), default=_utcnow)
    reason = Column(Text, default="")
    similarity_score = Column(Float, default=0.0)
    user_action = Column(Text, default="none")
    created_at = Column(DateTime(timezone=True), default=_utcnow)

class CognitiveEntry(Base):
    """Spec-compliant unified storage for cognitive entries (Learn/Think/Reflect)."""
    __tablename__ = "cognitive_entries"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    input_type = Column(String(50), nullable=False)  # link, voice, text
    cognitive_mode = Column(String(50), nullable=False) # learn, think, reflect
    original_input = Column(Text, nullable=False)
    source_url = Column(String(2048), nullable=True)
    cleaned_text = Column(Text, default="")
    summary = Column(Text, default="")
    title = Column(String(512), default="")
    key_points = Column(SafeJSON, default=[])
    bucket = Column(String(100), default="Uncategorized")
    tags = Column(SafeJSON, default=[])
    actionability_score = Column(Float, default=0.0)
    emotional_tone = Column(String(100), default="")
    confidence_score = Column(Float, default=0.0)
    resurfaced_count = Column(Integer, default=0)
    last_resurfaced_at = Column(DateTime(timezone=True), nullable=True)
    processing_status = Column(String(50), default="pending")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Bucket(Base):
    """Spec-compliant bucket system (Cap at 20 per user)."""
    __tablename__ = "buckets"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    entry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (UniqueConstraint('user_id', 'name', name='_user_bucket_uc'),)
