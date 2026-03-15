import json
from db.models import Memory

def _serialize_memory(memory: Memory) -> dict:
    return {
        "id": memory.id,
        "title": memory.title,
        "summary": memory.summary,
        "content": getattr(memory, "content", getattr(memory, "cleaned_text", "")),
        "category": memory.category,
        "bucket": getattr(memory, "bucket", None),
        "tags": json.loads(memory.tags) if memory.tags else [],
        "importance_score": memory.importance_score,
        "importance_reasons": (
            json.loads(memory.importance_reasons) if memory.importance_reasons else []
        ),
        "platform": getattr(memory, "platform", None),
        "source_url": getattr(memory, "source_url", getattr(memory, "url", None)),
        "thumbnail_url": getattr(memory, "thumbnail_url", None),
        "user_id": memory.user_id,
        "created_at": (memory.created_at.isoformat() + "Z") if memory.created_at else "",
        "content_quality": getattr(memory, "content_quality", None),
        "cognitive_mode": getattr(memory, "cognitive_mode", None),
    }
