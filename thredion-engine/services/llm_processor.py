"""
Thredion Engine — LLM Processor Service
Uses Groq Cloud (FREE TIER) for structured cognitive analysis.

Groq provides:
- 100x faster inference than OpenAI
- Free tier: 30 requests/min, sufficient for most use cases
- Structured JSON output
- Cost: $0 (free tier)
"""

import json
import logging
from typing import Optional, List, Literal
from dataclasses import dataclass, asdict

from groq import Groq
from openai import OpenAI
from pydantic import BaseModel, Field

from core.config import settings

logger = logging.getLogger(__name__)

# ── Pydantic Models for Structured Output ──────────────────


class CognitiveStructure(BaseModel):
    """Structured output from LLM cognitive analysis."""
    
    cognitive_mode: Literal["learn", "think", "reflect"] = Field(
        description="Classification: learn (external content), think (user ideas), reflect (personal)"
    )
    title: str = Field(max_length=200, description="Concise title (10 words max)")
    summary: str = Field(max_length=500, description="2-3 sentence summary")
    key_points: List[str] = Field(max_items=5, description="Up to 5 key insights")
    bucket: str = Field(max_length=50, description="Semantic bucket/category")
    tags: List[str] = Field(max_items=5, description="Up to 5 relevant tags")
    actionability_score: float = Field(ge=0.0, le=1.0, description="0-1 score")
    emotional_tone: Optional[str] = Field(
        max_length=20,
        description="neutral/curious/excited/anxious/motivated/frustrated/reflective/hopeful"
    )
    confidence_score: float = Field(ge=0.0, le=1.0, description="0-1 confidence in analysis")


# ── Groq Client ────────────────────────────────────────────


def get_groq_client() -> Groq:
    """Get or create Groq client."""
    if not settings.GROQ_API_KEY:
        logger.warning("⚠️ GROQ_API_KEY not set, LLM processing will fail")
        return None
    
    return Groq(api_key=settings.GROQ_API_KEY)


def get_openai_client() -> OpenAI:
    """Get or create OpenAI client."""
    if not settings.OPENAI_API_KEY:
        logger.warning("⚠️ OPENAI_API_KEY not set, OpenAI processing will fail")
        return None
    
    return OpenAI(api_key=settings.OPENAI_API_KEY)


# ── LLM Processing ────────────────────────────────────────


async def process_with_groq(
    text: str,
    existing_buckets: Optional[List[str]] = None,
    platform: str = "unknown",
) -> Optional[CognitiveStructure]:
    """
    Process content with Groq LLM for structured cognitive analysis.
    
    Args:
        text: Input text to analyze (transcript, description, idea, etc.)
        existing_buckets: List of user's existing bucket names
        platform: Source platform (youtube, instagram, twitter, etc.)
    
    Returns:
        CognitiveStructure with analyzed data, or None on failure
    """
    
    client = get_groq_client()
    if not client:
        logger.error("Groq not configured")
        return None
    
    existing_buckets = existing_buckets or []
    text_preview = text[:3000]  # Limit to 3000 chars for cost
    
    logger.info("🧠 Processing with Groq LLM...")
    
    # Build system prompt
    system_prompt = f"""You are Thredion's cognitive structuring engine.

Your job is to analyze content and classify it into one of three cognitive modes:
- "learn": External content user consumed (YouTube videos, articles, podcasts, reels, posts)
- "think": User's own original ideas, observations, startup concepts, frameworks
- "reflect": Personal reflections, dreams, emotional entries, diary thoughts, life logs

BUCKET RULES:
- User's existing buckets: {', '.join(existing_buckets) if existing_buckets else 'None yet'}
- ALWAYS prefer using an existing bucket if content fits
- Only suggest a new bucket if truly nothing matches
- Keep bucket names simple and broad (1-2 words): "Marketing", "AI Tools", "Startup Ideas", "Health", etc.
- Avoid overly specific or redundant buckets

ANALYSIS RULES:
- Identify main themes and actionable insights
- Emotional tone: Pick ONE (neutral, curious, excited, anxious, motivated, frustrated, reflective, hopeful)
- Actionability: How much can user ACT on this? (0=purely informational, 1=highly actionable)
- Confidence: How confident are you in this classification? (0=low, 1=high)

OUTPUT: Return ONLY valid JSON, no markdown, no extra text."""

    user_message = f"""Analyze this {platform} content:

{text_preview}

Return ONLY this JSON structure (no markdown):{{
    "cognitive_mode": "learn"|"think"|"reflect",
    "title": "...",
    "summary": "...",
    "key_points": ["...", "..."],
    "bucket": "...",
    "tags": ["...", "..."],
    "actionability_score": 0.X,
    "emotional_tone": "...",
    "confidence_score": 0.X
}}"""

    try:
        logger.info("📡 Calling Groq API...")
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",  # Available active model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=500,
            top_p=0.9,
        )
        
        result_text = response.choices[0].message.content.strip()
        
        logger.info(f"✅ Groq response received ({len(result_text)} chars)")
        
        # Parse JSON
        if result_text.startswith("```"):
            # Remove markdown code blocks if present
            result_text = result_text.replace("```json\n", "").replace("```\n", "").replace("```", "")
        
        data = json.loads(result_text)
        
        # Validate with Pydantic
        structured = CognitiveStructure(**data)
        
        logger.info(f"✅ Analysis complete: {structured.cognitive_mode} → {structured.bucket}")
        
        return structured
    
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON parse error: {e}\nResponse: {result_text[:200]}")
        return None
    except Exception as e:
        logger.error(f"❌ Groq processing failed: {e}")
        return None


async def fallback_classification(text: str) -> CognitiveStructure:
    """
    Fallback keyword-based classification when LLM fails.
    Simple heuristic-based approach.
    """
    logger.warning("⚠️ Using fallback classification (LLM failed or not configured)")
    
    text_lower = text.lower()
    
    # Detect cognitive mode
    if any(word in text_lower for word in ["i think", "idea", "what if", "should", "could"]):
        mode = "think"
    elif any(word in text_lower for word in ["feel", "felt", "dream", "reflection", "emotional", "anxiety", "anxious", "happy"]):
        mode = "reflect"
    else:
        mode = "learn"
    
    # Simple bucket detection
    bucket_keywords = {
        "AI": ["ai", "machine learning", "neural", "llm", "gpt", "groq"],
        "Marketing": ["marketing", "growth", "strategy", "campaign", "branding"],
        "Coding": ["code", "python", "javascript", "api", "github", "react"],
        "Business": ["business", "startup", "entrepreneur", "revenue", "pitch"],
        "Health": ["health", "fitness", "workout", "mental", "wellness"],
        "Travel": ["travel", "trip", "destination", "flight", "hotel"],
    }
    
    bucket = "Uncategorized"
    for bucket_name, keywords in bucket_keywords.items():
        if any(kw in text_lower for kw in keywords):
            bucket = bucket_name
            break
    
    return CognitiveStructure(
        cognitive_mode=mode,
        title=text[:50].strip(),
        summary=text[:150].strip(),
        key_points=[],
        bucket=bucket,
        tags=[],
        actionability_score=0.5,
        emotional_tone="neutral",
        confidence_score=0.3,
    )


async def process_with_openai(
    text: str,
    existing_buckets: Optional[List[str]] = None,
    platform: str = "unknown",
) -> Optional[CognitiveStructure]:
    """
    Process content with OpenAI LLM for structured cognitive analysis.
    """
    client = get_openai_client()
    if not client:
        logger.error("OpenAI not configured")
        return None
    
    existing_buckets = existing_buckets or []
    text_preview = text[:4000]
    
    logger.info("🧠 Processing with OpenAI LLM...")
    
    system_prompt = f"""You are Thredion's cognitive structuring engine.
Analyze content and classify it:
- "learn": External content
- "think": User's own ideas
- "reflect": Personal reflections

Existing buckets: {', '.join(existing_buckets)}
Prefer existing buckets if they fit. Suggest new one only if necessary.
Return ONLY valid JSON."""

    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze this {platform} content:\n\n{text_preview}"}
            ],
            response_format=CognitiveStructure,
        )
        
        structured = response.choices[0].message.parsed
        logger.info(f"✅ OpenAI Analysis complete: {structured.cognitive_mode} → {structured.bucket}")
        return structured
        
    except Exception as e:
        logger.error(f"❌ OpenAI processing failed: {e}")
        return None
