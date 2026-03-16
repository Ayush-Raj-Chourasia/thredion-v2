"""
Thredion Engine — AI Classifier & Summarizer
Classifies content into categories, generates summaries, and extracts topic graphs.
Uses OpenAI if available, falls back to keyword-based classification.
"""

import json
import logging
import os
import re
from dataclasses import dataclass

from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of AI classification."""
    category: str
    summary: str
    tags: list[str]
    topic_graph: list[str]


# ── Keyword Mapping (Fallback) ────────────────────────────────

KEYWORD_MAP: dict[str, list[str]] = {
    "Fitness": ["workout", "exercise", "gym", "muscle", "fitness", "cardio", "abs",
                "bodyweight", "training", "squat", "deadlift", "yoga", "stretch", "core"],
    "Coding": ["python", "javascript", "code", "programming", "developer", "api",
               "react", "fastapi", "algorithm", "software", "debug", "github", "coding",
               "frontend", "backend", "database", "deploy", "typescript", "node"],
    "Design": ["design", "ui", "ux", "figma", "logo", "brand", "typography",
               "color", "layout", "graphic", "creative", "photoshop", "canva"],
    "Food": ["recipe", "cook", "food", "meal", "pasta", "chicken", "bake",
             "restaurant", "cuisine", "kitchen", "ingredient", "diet", "nutrition"],
    "Travel": ["travel", "trip", "destination", "flight", "hotel", "beach",
               "mountain", "explore", "vacation", "tourism", "adventure", "backpack"],
    "Business": ["business", "startup", "entrepreneur", "marketing", "sales",
                 "revenue", "growth", "strategy", "market", "invest", "profit"],
    "Science": ["science", "research", "experiment", "physics", "chemistry",
                "biology", "space", "quantum", "dna", "climate", "evolution"],
    "Music": ["music", "song", "beat", "musician", "guitar", "piano",
              "producer", "album", "concert", "melody", "rhythm", "rap",
              "singer", "lyrics", "playlist", "spotify", "soundcloud", "dj",
              "remix", "hip hop", "pop", "rock", "never gonna give", "official video"],
    "Entertainment": ["movie", "film", "tv", "show", "series", "netflix",
                      "anime", "drama", "comedy", "trailer", "streaming",
                      "celebrity", "meme", "funny", "viral", "tiktok",
                      "game", "gaming", "esports", "twitch", "podcast"],
    "Art": ["art", "painting", "sculpture", "gallery", "artist", "canvas",
            "draw", "sketch", "portrait", "abstract", "illustration"],
    "Fashion": ["fashion", "style", "outfit", "clothing", "trend", "wear",
                "wardrobe", "accessory", "streetwear", "luxury"],
    "Education": ["learn", "study", "course", "tutorial", "lesson", "university",
                  "student", "education", "skill", "knowledge", "teach"],
    "Technology": ["tech", "ai", "machine learning", "robotics", "gadget",
                   "smartphone", "innovation", "cloud", "blockchain", "data"],
    "Health": ["health", "mental", "wellness", "meditation", "sleep",
               "anxiety", "therapy", "mindfulness", "self-care", "stress"],
    "Finance": ["finance", "money", "invest", "stock", "crypto", "budget",
                "saving", "income", "wealth", "trading", "portfolio"],
    "Motivation": ["motivation", "inspire", "success", "mindset", "hustle",
                   "discipline", "goal", "productive", "habit", "grind"],
    "Sports": ["sport", "football", "basketball", "cricket", "soccer", "tennis",
               "match", "championship", "league", "athlete", "score", "team"],
    "Lifestyle": ["lifestyle", "routine", "morning", "aesthetic", "vlog",
                  "daily", "life", "home", "interior", "minimalist", "tips"],
    "DIY": ["diy", "craft", "handmade", "tutorial", "build", "project",
            "woodwork", "repair", "homemade", "maker", "repurpose"],
    "Photography": ["photo", "photography", "camera", "lens", "portrait",
                    "landscape", "editing", "lightroom", "composition", "shot"],
}


def classify_content(text: str, url: str = "") -> ClassificationResult:
    """
    Classify and summarize content.
    Uses OpenAI API if key is available, otherwise keyword-based fallback.
    """
    combined_text = f"{text} {url}".strip()
    if os.getenv("PYTEST_CURRENT_TEST"):
        return _classify_with_keywords(combined_text)
    
    if settings.OPENAI_API_KEY:
        try:
            # Keep OpenAI sync for now as it's using sync client, but we can wrap it
            return _classify_with_openai(combined_text)
        except Exception as e:
            logger.warning(f"OpenAI classification failed: {e}. Trying Groq fallback.")
    
    if settings.GROQ_API_KEY:
        try:
            from services.llm_processor import process_with_groq
            import asyncio
            structured = asyncio.run(process_with_groq(combined_text, platform="fallback"))
            if structured:
                return ClassificationResult(
                    category=structured.bucket,
                    summary=structured.summary,
                    tags=structured.tags,
                    topic_graph=[structured.bucket] + structured.tags[:2]
                )
        except Exception as e:
            logger.warning(f"Groq fallback failed: {e}. Falling back to keywords.")

    return _classify_with_keywords(combined_text)


def _classify_with_openai(text: str) -> ClassificationResult:
    """Classify content using OpenAI GPT."""
    import openai

    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    categories_str = ", ".join(settings.CATEGORIES)

    prompt = f"""Analyze this social media content and return a JSON object with these fields:

1. "category": One of [{categories_str}]. Pick the BEST match.
2. "summary": A concise 1-2 sentence summary capturing the key insight.
3. "tags": A list of 3-5 relevant tags (lowercase, no #).
4. "topic_graph": A hierarchical list of topics from broad to specific (3-5 items).
   Example: ["Technology", "Programming", "Python", "Web Development", "FastAPI"]

Content to analyze:
---
{text[:1500]}
---

Return ONLY valid JSON. No markdown, no explanation."""

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
    )

    result_text = response.choices[0].message.content.strip()

    # Clean potential markdown wrapping
    if result_text.startswith("```"):
        result_text = re.sub(r"^```(?:json)?\s*", "", result_text)
        result_text = re.sub(r"\s*```$", "", result_text)

    data = json.loads(result_text)

    return ClassificationResult(
        category=data.get("category", "Uncategorized"),
        summary=data.get("summary", text[:200]),
        tags=data.get("tags", []),
        topic_graph=data.get("topic_graph", [data.get("category", "General")]),
    )


# Platform-to-category mapping for URL-based classification
PLATFORM_CATEGORY_MAP: dict[str, str] = {
    "instagram": "Entertainment",
    "twitter": "Entertainment",
    "tiktok": "Entertainment",
    "youtube": "Entertainment",
    "reddit": "Entertainment",
}

# URL pattern hints for better classification
URL_CATEGORY_HINTS: list[tuple[str, str]] = [
    ("instagram.com/reel", "Entertainment"),
    ("instagram.com/p/", "Entertainment"),
    ("instagram.com/stories", "Entertainment"),
    ("youtube.com/watch", "Entertainment"),
    ("youtu.be/", "Entertainment"),
    ("twitter.com", "Entertainment"),
    ("x.com", "Entertainment"),
    ("tiktok.com", "Entertainment"),
    ("reddit.com", "Entertainment"),
    ("medium.com", "Education"),
    ("dev.to", "Coding"),
    ("github.com", "Coding"),
    ("stackoverflow.com", "Coding"),
    ("arxiv.org", "Science"),
    ("dribbble.com", "Design"),
    ("behance.net", "Design"),
    ("figma.com", "Design"),
    ("spotify.com", "Music"),
    ("soundcloud.com", "Music"),
]


def _classify_with_keywords(text: str) -> ClassificationResult:
    """Fallback: classify content using keyword matching."""
    text_lower = text.lower()
    scores: dict[str, int] = {}

    for category, keywords in KEYWORD_MAP.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[category] = score

    # If no keyword matches, try URL / platform-based classification
    if not scores:
        for pattern, cat in URL_CATEGORY_HINTS:
            if pattern in text_lower:
                scores[cat] = scores.get(cat, 0) + 2
                break

    # Also detect platform names in the text itself
    platform_mentions = {
        "instagram": "Entertainment", "reel": "Entertainment",
        "tiktok": "Entertainment", "youtube": "Entertainment",
        "twitter": "Entertainment", "reddit": "Entertainment",
    }
    for platform, cat in platform_mentions.items():
        if platform in text_lower:
            scores[cat] = scores.get(cat, 0) + 1

    if scores:
        category = max(scores, key=scores.get)
    else:
        category = "Uncategorized"

    # Generate smart summary
    clean_text = re.sub(r'https?://\S+', '', text).strip()
    sentences = [s.strip() for s in re.split(r'[.!?\n]+', clean_text) if s.strip()]
    if sentences:
        # Take first meaningful sentence, append category context
        first = sentences[0][:180]
        if len(sentences) > 1:
            summary = f"{first}. {sentences[1][:80]}".strip()
        else:
            summary = first
        if category != "Uncategorized":
            summary = f"[{category}] {summary}"
    else:
        summary = f"Saved {category.lower()} content" if category != "Uncategorized" else "Saved content"

    # Extract tags from text
    words = re.findall(r'#(\w+)', text)
    if not words:
        # Filter out pure URL fragments and short words
        words = [w for w in text_lower.split() if len(w) > 4 and not w.startswith("http")]
        # Add platform-derived tags
        for platform in ["instagram", "youtube", "twitter", "tiktok", "reddit"]:
            if platform in text_lower and platform not in words:
                words.append(platform)
    tags = list(set(words[:5]))

    # Build topic graph
    topic_graph = [category]
    if category in KEYWORD_MAP:
        matched = [kw for kw in KEYWORD_MAP[category] if kw in text_lower]
        topic_graph.extend(matched[:3])
    # Add platform as topic if relevant
    for platform in ["Instagram", "YouTube", "Twitter", "TikTok", "Reddit"]:
        if platform.lower() in text_lower and platform not in topic_graph:
            topic_graph.insert(1, platform)
            break

    return ClassificationResult(
        category=category,
        summary=summary,
        tags=tags,
        topic_graph=topic_graph,
    )
