import pprint
import re

with open('api/routes.py', 'r', encoding='utf-8') as f:
    c = f.read()

# Create safe json loads
replacement = '''def _safe_json_loads(value, default):
    import json
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default

def _serialize_memory(memory: Memory) -> dict:
    return {
        "id": memory.id,
        "title": getattr(memory, "title", None),
        "summary": getattr(memory, "summary", None),
        "content": getattr(memory, "content", getattr(memory, "cleaned_text", "")) or "",
        "category": getattr(memory, "category", None),
        "bucket": getattr(memory, "bucket", None),
        "tags": _safe_json_loads(getattr(memory, "tags", None), []),
        "importance_score": getattr(memory, "importance_score", None),
        "importance_reasons": _safe_json_loads(getattr(memory, "importance_reasons", None), []),
        "platform": getattr(memory, "platform", None),
        "source_url": getattr(memory, "source_url", getattr(memory, "url", None)),
        "thumbnail_url": getattr(memory, "thumbnail_url", None),
        "user_id": getattr(memory, "user_id", None),
        "created_at": (memory.created_at.isoformat() + "Z") if getattr(memory, "created_at", None) else "",
        "content_quality": getattr(memory, "content_quality", None),
        "cognitive_mode": getattr(memory, "cognitive_mode", None),
    }

def _get_user_buckets'''

c = re.sub(r'def _serialize_memory\(memory: Memory\) -> dict:.*?def _get_user_buckets', replacement, c, flags=re.DOTALL)

# Let's fix user_phone/user.phone in process_cognitive_endpoint and anything else
c = c.replace('user_phone: str', 'user_id')
c = c.replace('user.phone', 'user.id')

with open('api/routes.py', 'w', encoding='utf-8') as f:
    f.write(c)

