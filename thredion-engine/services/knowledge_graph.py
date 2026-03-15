"""
Thredion Engine — Knowledge Graph Builder
Automatically connects related memories based on semantic similarity.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from core.config import settings
from db.models import Memory, Connection
from services.embeddings import embedding_to_vector, cosine_similarity

logger = logging.getLogger(__name__)


def build_connections(new_memory: Memory, db: Session) -> list[dict]:
    """
    Find and create connections between a new memory and existing ones.
    Returns list of created connections with details.
    """
    if not new_memory.embedding:
        logger.warning(f"Memory {new_memory.id} has no embedding — skipping graph build.")
        return []

    new_vec = embedding_to_vector(new_memory.embedding)
    if new_vec is None:
        return []

    # Fetch other memories with embeddings belonging to the same user
    existing = (
        db.query(Memory)
        .filter(Memory.id != new_memory.id)
        .filter(Memory.user_id == new_memory.user_id)
        .filter(Memory.embedding.isnot(None))
        .all()
    )

    connections_created = []
    similarities = []

    for memory in existing:
        existing_vec = embedding_to_vector(memory.embedding)
        if existing_vec is None:
            continue

        sim = cosine_similarity(new_vec, existing_vec)

        if sim >= settings.SIMILARITY_THRESHOLD:
            similarities.append((memory, sim))

    # Sort by similarity and keep top N
    similarities.sort(key=lambda x: x[1], reverse=True)
    top_connections = similarities[: settings.MAX_CONNECTIONS]

    for memory, sim in top_connections:
        # Check if connection already exists
        existing_conn = (
            db.query(Connection)
            .filter(
                ((Connection.source_id == new_memory.id) & (Connection.target_id == memory.id))
                | ((Connection.source_id == memory.id) & (Connection.target_id == new_memory.id))
            )
            .first()
        )

        if existing_conn:
            continue

        conn = Connection(
            user_id=new_memory.user_id,
            source_id=new_memory.id,
            target_id=memory.id,
            similarity_score=round(sim, 4),
        )
        db.add(conn)
        connections_created.append({
            "connected_memory_id": memory.id,
            "connected_memory_title": memory.title or memory.summary[:50],
            "connected_memory_category": memory.category,
            "similarity_score": round(sim, 4),
        })

    if connections_created:
        db.commit()
        logger.info(
            f"Created {len(connections_created)} connections for memory {new_memory.id}"
        )

    return connections_created


def get_full_graph(db: Session, user_id = None) -> dict:
    """
    Build the knowledge graph for the dashboard, scoped to a user.
    Returns nodes and edges.
    """
    q = db.query(Memory)
    if user_id:
        q = q.filter(Memory.user_id == user_id)
    memories = q.all()
    mem_ids = {m.id for m in memories}
    connections = [
        c for c in db.query(Connection).all()
        if c.source_id in mem_ids and c.target_id in mem_ids
    ]

    nodes = [
        {
            "id": m.id,
            "title": m.title or (m.summary[:40] if m.summary else f"Memory #{m.id}"),
            "category": m.category,
            "importance_score": m.importance_score,
            "url": m.url,
        }
        for m in memories
    ]

    edges = [
        {
            "source": c.source_id,
            "target": c.target_id,
            "weight": c.similarity_score,
        }
        for c in connections
    ]

    return {"nodes": nodes, "edges": edges}


def get_memory_connections(memory_id: int, db: Session) -> list[dict]:
    """Get all connections for a specific memory."""
    connections = (
        db.query(Connection)
        .filter(
            (Connection.source_id == memory_id) | (Connection.target_id == memory_id)
        )
        .all()
    )

    result = []
    for conn in connections:
        # Determine the connected memory (the other end)
        if conn.source_id == memory_id:
            other = db.query(Memory).filter(Memory.id == conn.target_id).first()
        else:
            other = db.query(Memory).filter(Memory.id == conn.source_id).first()

        if other:
            result.append({
                "connected_memory_id": other.id,
                "connected_memory_title": other.title or other.summary[:50],
                "connected_memory_summary": other.summary,
                "connected_memory_category": other.category,
                "similarity_score": conn.similarity_score,
            })

    return result
