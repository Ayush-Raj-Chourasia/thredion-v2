"""
Thredion Engine — Pipeline & Duplicate Detection Tests
Tests the full cognitive pipeline and the duplicate detection / normalization logic.
Run:  cd thredion-engine && python -m pytest tests/test_pipeline.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from services.pipeline import process_url
from db.models import Memory
from tests.conftest import make_memory, make_embedding


# ── Duplicate Detection ───────────────────────────────────────

class TestDuplicateDetection:
    """The pipeline must prevent re-processing of already-saved URLs."""

    def test_exact_url_duplicate(self, db_session):
        make_memory(db_session, url="https://example.com/post")
        result = process_url("https://example.com/post", "test", db_session)
        assert result["duplicate"] is True
        assert "already exists" in result["message"]

    def test_trailing_slash_duplicate(self, db_session):
        make_memory(db_session, url="https://example.com/post")
        result = process_url("https://example.com/post/", "test", db_session)
        assert result["duplicate"] is True

    def test_query_param_stripping_for_articles(self, db_session):
        make_memory(db_session, url="https://example.com/blog-post")
        result = process_url("https://example.com/blog-post?ref=twitter", "test", db_session)
        assert result["duplicate"] is True

    def test_youtube_preserves_query_params(self, db_session):
        """YouTube URLs with different video IDs must NOT be treated as duplicates."""
        make_memory(db_session, url="https://youtube.com/watch?v=abc123")
        # Different video — should NOT be duplicate (new URL, will try to process)
        # We mock the extractor to avoid a real HTTP call
        with patch("services.pipeline.extract_from_url") as mock_ext:
            mock_ext.return_value = MagicMock(
                platform="youtube", title="New Video", content="content",
                thumbnail_url="", url="https://youtube.com/watch?v=xyz789",
            )
            with patch("services.pipeline.generate_embedding", return_value=make_embedding("new")):
                with patch("services.pipeline.classify_content") as mock_cls:
                    mock_cls.return_value = MagicMock(
                        category="Entertainment", summary="Sum", tags=["tag"],
                        topic_graph=["Entertainment"],
                    )
                    with patch("services.pipeline.build_connections", return_value=[]):
                        with patch("services.pipeline.compute_importance") as mock_imp:
                            mock_imp.return_value = MagicMock(score=50, reasons=["ok"])
                            with patch("services.pipeline.find_resurfaceable", return_value=[]):
                                result = process_url(
                                    "https://youtube.com/watch?v=xyz789", "test", db_session
                                )
                                assert result.get("duplicate") is not True

    def test_duplicate_returns_existing_data(self, db_session):
        m = make_memory(
            db_session,
            url="https://example.com/dup",
            title="Original Title",
            category="Design",
            importance_score=72,
        )
        result = process_url("https://example.com/dup", "test", db_session)
        assert result["memory_id"] == m.id
        assert result["title"] == "Original Title"
        assert result["category"] == "Design"
        assert result["importance_score"] == 72


# ── Validation ────────────────────────────────────────────────

class TestPipelineValidation:
    def test_empty_url_raises(self, db_session):
        with pytest.raises(ValueError, match="empty"):
            process_url("", "test", db_session)

    def test_whitespace_url_raises(self, db_session):
        with pytest.raises(ValueError, match="empty"):
            process_url("   ", "test", db_session)


# ── Full Pipeline (mocked network) ───────────────────────────

class TestFullPipeline:
    """Validate the 7-step pipeline produces a correct result structure."""

    @patch("services.pipeline.find_resurfaceable", return_value=[])
    @patch("services.pipeline.compute_importance")
    @patch("services.pipeline.build_connections", return_value=[])
    @patch("services.pipeline.classify_content")
    @patch("services.pipeline.generate_embedding")
    @patch("services.pipeline.extract_from_url")
    def test_pipeline_returns_correct_shape(
        self, mock_ext, mock_emb, mock_cls, mock_conn, mock_imp, mock_res, db_session
    ):
        mock_ext.return_value = MagicMock(
            platform="article",
            title="Test Article",
            content="Article body text here.",
            thumbnail_url="https://img.com/thumb.jpg",
            url="https://blog.com/article",
        )
        mock_emb.return_value = make_embedding("article body")
        mock_cls.return_value = MagicMock(
            category="Technology",
            summary="A tech article.",
            tags=["tech", "ai"],
            topic_graph=["Technology", "AI"],
        )
        mock_imp.return_value = MagicMock(score=68, reasons=["Good novelty"])

        result = process_url("https://blog.com/article", "demo", db_session)

        # Shape assertions
        assert "memory_id" in result
        assert result["url"] == "https://blog.com/article"
        assert result["platform"] == "article"
        assert result["title"] == "Test Article"
        assert result["category"] == "Technology"
        assert isinstance(result["tags"], list)
        assert isinstance(result["importance_score"], (int, float))
        assert isinstance(result["connections"], list)
        assert isinstance(result["resurfaced"], list)

    @patch("services.pipeline.find_resurfaceable", return_value=[])
    @patch("services.pipeline.compute_importance")
    @patch("services.pipeline.build_connections", return_value=[])
    @patch("services.pipeline.classify_content")
    @patch("services.pipeline.generate_embedding")
    @patch("services.pipeline.extract_from_url")
    def test_pipeline_saves_to_db(
        self, mock_ext, mock_emb, mock_cls, mock_conn, mock_imp, mock_res, db_session
    ):
        mock_ext.return_value = MagicMock(
            platform="instagram", title="Reel", content="caption",
            thumbnail_url="", url="https://instagram.com/p/ABC",
        )
        mock_emb.return_value = make_embedding("reel")
        mock_cls.return_value = MagicMock(
            category="Fitness", summary="Fitness reel", tags=["fit"],
            topic_graph=["Fitness"],
        )
        mock_imp.return_value = MagicMock(score=55, reasons=["Moderate"])

        process_url("https://instagram.com/p/ABC", "user1", db_session)

        assert db_session.query(Memory).count() == 1
        saved = db_session.query(Memory).first()
        assert saved.platform == "instagram"
        assert saved.user_id == "user1"
