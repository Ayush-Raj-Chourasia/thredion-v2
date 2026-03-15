"""
Thredion Engine — Shared Test Fixtures
Provides an in-memory SQLite database, a FastAPI TestClient, and helper
factories so every test module starts from a clean, deterministic state.
"""

import json
import os
import sys
import pickle
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

# Ensure thredion-engine root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------- Database Fixtures ---------- #

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.database as _db_module
from db.database import Base, get_db
from db.models import Memory, Connection, ResurfacedMemory

# Shared test engine (in-memory, StaticPool ensures single connection so all
# sessions see the same database — critical for in-memory SQLite)
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_test_engine)


@pytest.fixture()
def db_session():
    """Provide a fresh in-memory DB with tables for each test."""
    Base.metadata.create_all(bind=_test_engine)
    session = _TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=_test_engine)


# ---------- FastAPI TestClient ---------- #

from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app


@pytest.fixture()
def client(db_session):
    """Provide a TestClient wired to the in-memory database."""
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db

    # Patch init_db so the lifespan creates tables on the TEST engine
    with patch.object(_db_module, "init_db", lambda: Base.metadata.create_all(bind=_test_engine)):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


# ---------- Helper Factories ---------- #

def make_embedding(text: str = "hello world", dim: int = 384) -> bytes:
    """Produce a deterministic pickled numpy embedding."""
    np.random.seed(hash(text) % (2**31))
    vec = np.random.randn(dim).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return pickle.dumps(vec)


def make_memory(
    db_session,
    url: str = "https://example.com/post",
    platform: str = "article",
    title: str = "Test Memory",
    content: str = "Some content for testing.",
    summary: str = "Test summary",
    category: str = "Technology",
    tags: list | None = None,
    topic_graph: list | None = None,
    importance_score: float = 50.0,
    importance_reasons: list | None = None,
    thumbnail_url: str = "",
    user_id: str = "test",
    created_at: datetime | None = None,
    embedding_text: str | None = None,
) -> Memory:
    """Insert and return a fully-formed Memory row."""
    m = Memory(
        url=url,
        platform=platform,
        title=title,
        content=content,
        summary=summary,
        category=category,
        tags=json.dumps(tags or ["test"]),
        topic_graph=json.dumps(topic_graph or [category]),
        embedding=make_embedding(embedding_text or title),
        importance_score=importance_score,
        importance_reasons=json.dumps(importance_reasons or ["testing"]),
        thumbnail_url=thumbnail_url,
        user_id=user_id,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    return m
