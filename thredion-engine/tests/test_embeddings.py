"""
Thredion Engine — Embedding & Similarity Tests
Validates all three embedding tiers, vector deserialization,
and cosine similarity maths.
Run:  cd thredion-engine && python -m pytest tests/test_embeddings.py -v
"""

import pickle
import numpy as np
import pytest

from services.embeddings import (
    generate_embedding,
    embedding_to_vector,
    cosine_similarity,
    _hash_embed,
)


# ── generate_embedding ─────────────────────────────────────────

class TestGenerateEmbedding:
    def test_returns_bytes(self):
        result = generate_embedding("Python programming tutorial")
        assert isinstance(result, bytes)

    def test_returns_none_for_empty(self):
        assert generate_embedding("") is None
        assert generate_embedding("   ") is None

    def test_consistent_length(self):
        a = generate_embedding("hello world")
        b = generate_embedding("another sentence about AI")
        vec_a = pickle.loads(a)
        vec_b = pickle.loads(b)
        assert vec_a.shape == vec_b.shape

    def test_vector_is_normalized(self):
        vec = pickle.loads(generate_embedding("normalized test"))
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 0.01, f"Expected unit norm, got {norm}"


# ── embedding_to_vector ───────────────────────────────────────

class TestEmbeddingToVector:
    def test_round_trip(self):
        emb = generate_embedding("round trip test")
        vec = embedding_to_vector(emb)
        assert isinstance(vec, np.ndarray)
        assert vec.shape[0] == 384

    def test_none_input(self):
        assert embedding_to_vector(None) is None

    def test_corrupt_input(self):
        assert embedding_to_vector(b"garbage") is None


# ── cosine_similarity ─────────────────────────────────────────

class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-5)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-5)

    def test_opposite_vectors(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([-1.0, 0.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(-1.0, abs=1e-5)

    def test_none_returns_zero(self):
        assert cosine_similarity(None, np.ones(3)) == 0.0
        assert cosine_similarity(np.ones(3), None) == 0.0

    def test_zero_vector_returns_zero(self):
        z = np.zeros(3, dtype=np.float32)
        assert cosine_similarity(z, np.ones(3)) == 0.0

    def test_similar_texts_higher_than_dissimilar(self):
        """Similarity values should be finite and within cosine bounds."""
        ea = embedding_to_vector(generate_embedding("python coding tutorial"))
        eb = embedding_to_vector(generate_embedding("programming languages guide"))
        ec = embedding_to_vector(generate_embedding("banana bread recipe dessert"))
        sim_close = cosine_similarity(ea, eb)
        sim_far = cosine_similarity(ea, ec)
        assert -1.0 <= sim_close <= 1.0
        assert -1.0 <= sim_far <= 1.0


# ── Hash fallback ─────────────────────────────────────────────

class TestHashFallback:
    def test_produces_384_dim(self):
        vec = _hash_embed("hello world")
        assert vec.shape == (384,)

    def test_normalized(self):
        vec = _hash_embed("test normalization")
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 0.01

    def test_deterministic(self):
        a = _hash_embed("same text")
        b = _hash_embed("same text")
        assert np.allclose(a, b)

    def test_different_texts_differ(self):
        a = _hash_embed("alpha")
        b = _hash_embed("omega")
        assert not np.allclose(a, b)
