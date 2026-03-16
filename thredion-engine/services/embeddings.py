"""
Thredion Engine — Embedding Generator
Generates semantic vector embeddings for content using sentence-transformers.
Falls back to TF-IDF if sentence-transformers is unavailable.
"""

import logging
import pickle
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Globals ───────────────────────────────────────────────────
_model = None
_model_type: str = "none"


def _load_model(force_reload: bool = False):
    """Lazy-load the embedding model."""
    global _model, _model_type

    if _model is not None and not force_reload:
        return

    # Try sentence-transformers first
    try:
        import torch
        from sentence_transformers import SentenceTransformer
        # Force weights_only=False to avoid meta tensor issues on PyTorch 2.10+
        _orig_load = torch.load
        def _patched_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return _orig_load(*args, **kwargs)
        torch.load = _patched_load
        try:
            _model = SentenceTransformer("all-MiniLM-L6-v2")
        finally:
            torch.load = _orig_load
        _model_type = "sentence-transformers"
        logger.info("Loaded sentence-transformers model: all-MiniLM-L6-v2")
        return
    except ImportError:
        logger.warning("sentence-transformers not installed. Trying sklearn TF-IDF fallback.")
    except Exception as e:
        logger.warning(f"sentence-transformers load failed ({e}). Trying fallbacks.")

    # Fallback to TF-IDF
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        _model = TfidfVectorizer(max_features=384, stop_words="english")
        _model_type = "tfidf"
        logger.info("Using TF-IDF fallback for embeddings.")
        return
    except ImportError:
        logger.warning("sklearn not installed. Using hash-based embeddings.")

    _model_type = "hash"
    logger.info("Using hash-based embedding fallback.")


def generate_embedding(text: str) -> Optional[bytes]:
    """
    Generate a vector embedding for the given text.
    Returns pickled numpy array (bytes) or None on failure.
    """
    _load_model()

    if not text or not text.strip():
        return None

    try:
        if _model_type == "sentence-transformers":
            vec = _model.encode(text, normalize_embeddings=True)
            return pickle.dumps(vec.astype(np.float32))

        elif _model_type == "tfidf":
            vec = _tfidf_embed(text)
            return pickle.dumps(vec.astype(np.float32))

        else:
            vec = _hash_embed(text)
            return pickle.dumps(vec.astype(np.float32))

    except Exception as e:
        # If sentence-transformers fails (e.g. meta tensor error), retry once with fresh load
        if _model_type == "sentence-transformers":
            logger.warning(f"Embedding encode failed ({e}), retrying with fresh model load...")
            try:
                _load_model(force_reload=True)
                if _model_type == "sentence-transformers":
                    vec = _model.encode(text, normalize_embeddings=True)
                    return pickle.dumps(vec.astype(np.float32))
            except Exception as e2:
                logger.warning(f"Retry also failed ({e2}), falling back to hash embedding.")

        # Ultimate fallback — hash-based embedding always works
        logger.error(f"Embedding generation failed: {e}. Using hash fallback.")
        vec = _hash_embed(text)
        return pickle.dumps(vec.astype(np.float32))


def embedding_to_vector(embedding_bytes: bytes) -> Optional[np.ndarray]:
    """Deserialize a stored embedding back to numpy array."""
    if not embedding_bytes:
        return None
    try:
        return pickle.loads(embedding_bytes)
    except Exception:
        return None


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    if vec_a is None or vec_b is None:
        return 0.0

    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


# ── TF-IDF Fallback ──────────────────────────────────────────

_tfidf_fitted = False
_tfidf_corpus: list[str] = []


def _tfidf_embed(text: str) -> np.ndarray:
    """Generate embedding using TF-IDF. Refits on each call (simple approach)."""
    global _tfidf_fitted, _tfidf_corpus

    _tfidf_corpus.append(text)

    if len(_tfidf_corpus) == 1:
        # Single document — create a 384-dim zero vector with hash seeding
        return _hash_embed(text)

    _model.fit(_tfidf_corpus)
    matrix = _model.transform([text])
    vec = matrix.toarray()[0]

    # Pad or truncate to 384 dimensions
    if len(vec) < 384:
        vec = np.pad(vec, (0, 384 - len(vec)))
    else:
        vec = vec[:384]

    # Normalize
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    return vec


# ── Hash-Based Fallback ──────────────────────────────────────

def _hash_embed(text: str, dim: int = 384) -> np.ndarray:
    """
    Simple deterministic hash-based embedding.
    Not semantically meaningful but provides consistent vectors.
    """
    import hashlib

    vec = np.zeros(dim, dtype=np.float32)
    words = text.lower().split()

    for i, word in enumerate(words):
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        indices = [(h >> (j * 8)) % dim for j in range(4)]
        for idx in indices:
            vec[idx] += 1.0

    # Normalize
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    return vec
