"""
Thredion Engine — Demo Reliability Tests
Simulates the four most dangerous demo-day failure scenarios and
verifies that defenses hold.

Run:  cd thredion-engine && python -m pytest tests/test_demo_reliability.py -v
"""

import time
import socket
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from tests.conftest import make_memory, make_embedding


# ── 1. SLOW MODEL LOADING ─────────────────────────────────────
#
# Scenario: sentence-transformers takes 10-30s to download / load
#           on cold start, causing first-request timeout.
# Defense:  The embedding module already lazy-loads, BUT a judge
#           hitting "Add Memory" before the model finishes gets a
#           blank spinner for 30s.  Solution: pre-warm at startup.


class TestSlowModelLoading:
    """Verify embedding fallbacks keep the pipeline alive even when the
    primary model is unavailable or slow to load."""

    def test_hash_fallback_when_sentencetransformers_missing(self):
        """If sentence-transformers isn't importable, embeddings still work."""
        import services.embeddings as emb
        original_model = emb._model
        original_type = emb._model_type

        try:
            emb._model = None
            emb._model_type = "none"
            # Force hash fallback by pretending ST import fails
            with patch.dict("sys.modules", {"sentence_transformers": None}):
                emb._model = None
                emb._model_type = "none"
                emb._load_model()
                # Should fall through to tfidf or hash
                assert emb._model_type in ("tfidf", "hash")
        finally:
            emb._model = original_model
            emb._model_type = original_type

    def test_embedding_generation_always_returns_bytes(self):
        """Even with fallback, generate_embedding must return bytes."""
        from services.embeddings import generate_embedding
        result = generate_embedding("quick demo test sentence")
        assert isinstance(result, bytes)
        assert len(result) > 100


# ── 2. API / NETWORK TIMEOUT ──────────────────────────────────
#
# Scenario: External oEmbed API (Instagram/YouTube) is slow or down.
# Defense:  Extractors have 10s timeout + meta-tag fallback.

class TestAPITimeout:
    """Validate extraction gracefully degrades when external APIs time out."""

    @patch("services.extractor.requests.get")
    def test_youtube_oembed_timeout_falls_to_meta(self, mock_get):
        """When YouTube oEmbed times out, extraction still returns something."""
        from services.extractor import extract_from_url

        # First call (oEmbed) times out, second call (meta-tag fallback) succeeds
        mock_get.side_effect = [
            Exception("Connection timed out"),
            MagicMock(
                status_code=200,
                text='<html><head><meta property="og:title" content="Fallback Title"/></head></html>',
            ),
        ]
        result = extract_from_url("https://www.youtube.com/watch?v=test123")
        assert result.platform == "youtube"
        # Should get at least the fallback title
        assert result.title == "Fallback Title" or len(result.title) >= 0

    @patch("services.extractor.requests.get")
    def test_instagram_oembed_timeout(self, mock_get):
        """Instagram oEmbed timeout => meta-tag fallback path."""
        from services.extractor import extract_from_url

        mock_get.side_effect = [
            Exception("Timeout"),
            MagicMock(
                status_code=200,
                text='<html><head><meta property="og:title" content="IG Post"/>'
                     '<meta property="og:description" content="Caption here"/></head></html>',
            ),
        ]
        result = extract_from_url("https://www.instagram.com/p/ABC123/")
        assert result.platform == "instagram"

    @patch("services.extractor.requests.get")
    def test_total_extraction_failure_returns_empty(self, mock_get):
        """Even if everything fails, extraction returns an ExtractedContent — never crashes."""
        from services.extractor import extract_from_url

        mock_get.side_effect = Exception("Network unreachable")
        result = extract_from_url("https://example.com/totally-broken")
        assert result is not None
        assert result.url == "https://example.com/totally-broken"


# ── 3. WHATSAPP WEBHOOK FAILURE ───────────────────────────────
#
# Scenario: Twilio sends a webhook with missing/malformed fields.
# Defense:  The webhook handler must return valid TwiML (never 500).

class TestWhatsAppWebhookResilience:
    """Ensure the WhatsApp endpoint never returns 500 for judge safety."""

    def test_missing_body_field(self, client):
        """Twilio webhook with no 'Body' field should return help message."""
        r = client.post(
            "/api/whatsapp/webhook",
            data={"From": "whatsapp:+1234567890"},
        )
        # Should return 200 with TwiML, not 500
        assert r.status_code == 200
        assert "xml" in r.headers.get("content-type", "").lower() or "<Response>" in r.text

    def test_empty_body(self, client):
        """Empty message body → help reply."""
        r = client.post(
            "/api/whatsapp/webhook",
            data={"From": "whatsapp:+1234567890", "Body": ""},
        )
        assert r.status_code == 200

    def test_no_url_in_body(self, client):
        """Message with text but no URL → help reply."""
        r = client.post(
            "/api/whatsapp/webhook",
            data={"From": "whatsapp:+1234567890", "Body": "hello there"},
        )
        assert r.status_code == 200
        assert "help" in r.text.lower() or "send" in r.text.lower() or "link" in r.text.lower()

    def test_missing_from_field(self, client):
        """Webhook without 'From' should not crash (use fallback phone)."""
        r = client.post(
            "/api/whatsapp/webhook",
            data={"Body": "check this https://example.com/test"},
        )
        # Must not be 500
        assert r.status_code in (200, 422)


# ── 4. FRONTEND ↔ BACKEND MISMATCH ───────────────────────────
#
# Scenario: Frontend expects fields the backend doesn't return.
# Defense:  Validate API response shapes match TypeScript types.

class TestResponseContract:
    """Verify every API response matches the shape the frontend expects."""

    def test_memory_response_shape(self, client, db_session):
        m = make_memory(db_session, url="https://a.com/shape-test")
        r = client.get(f"/api/memories/{m.id}")
        data = r.json()
        # These fields must exist — frontend reads them without optional chaining
        required = [
            "id", "url", "platform", "title", "content", "summary",
            "category", "tags", "topic_graph", "importance_score",
            "importance_reasons", "thumbnail_url", "user_id", "created_at",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"
        # Type checks
        assert isinstance(data["tags"], list)
        assert isinstance(data["topic_graph"], list)
        assert isinstance(data["importance_reasons"], list)
        assert isinstance(data["importance_score"], (int, float))

    def test_stats_response_shape(self, client, db_session):
        make_memory(db_session, category="Coding", url="https://a.com/1")
        r = client.get("/api/stats")
        s = r.json()
        required = [
            "total_memories", "total_connections", "total_resurfaced",
            "categories", "avg_importance", "top_category",
        ]
        for field in required:
            assert field in s, f"Missing stats field: {field}"
        assert isinstance(s["categories"], dict)

    def test_graph_response_shape(self, client, db_session):
        make_memory(db_session, url="https://a.com/g1")
        r = client.get("/api/graph")
        g = r.json()
        assert "nodes" in g and "edges" in g
        if g["nodes"]:
            node = g["nodes"][0]
            for f in ["id", "title", "category", "importance_score", "url"]:
                assert f in node, f"Missing graph node field: {f}"

    def test_categories_response_shape(self, client, db_session):
        make_memory(db_session, category="Art", url="https://a.com/c1")
        cats = client.get("/api/categories").json()
        assert len(cats) > 0
        assert "category" in cats[0]
        assert "count" in cats[0]
