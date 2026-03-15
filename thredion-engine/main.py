"""
Thredion Engine — Main Application
FastAPI entry point for the AI Cognitive Memory Engine.

IMPORTANT: Railway must have SUPABASE_DB_PASSWORD environment variable set.
"""

import logging
import sys
import os
from contextlib import asynccontextmanager
from datetime import datetime

# Add the project root to path so imports work correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from db.database import init_db
from api.routes import router as api_router
from api.whatsapp import router as whatsapp_router
from api.auth import router as auth_router
from app.api.cognitive import router as cognitive_router

# ── Logging ───────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("thredion")

# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown events."""
    logger.info("=" * 60)
    logger.info("  THREDION ENGINE — AI Cognitive Memory Engine")
    logger.info("=" * 60)
    logger.info("✓ Application started (database initialization deferred until first use)")
    logger.info(f"Embedding model: {settings.EMBEDDING_MODEL}")
    logger.info(f"OpenAI configured: {'Yes' if settings.OPENAI_API_KEY else 'No (using fallback)'}")
    logger.info(f"Twilio configured: {'Yes' if settings.TWILIO_ACCOUNT_SID else 'No'}")
    logger.info(f"Frontend URL: {settings.FRONTEND_URL}")
    logger.info(f"Docs: http://localhost:{settings.PORT}/docs")
    # Pre-warm the embedding model in a background thread so the server starts fast
    import threading
    def _prewarm():
        try:
            from services.embeddings import generate_embedding
            generate_embedding("warmup")
            logger.info("Embedding model pre-warmed ✓")
        except Exception as e:
            logger.warning(f"Embedding pre-warm failed (will lazy-load later): {e}")
    threading.Thread(target=_prewarm, daemon=True).start()
    logger.info("=" * 60)
    yield
    logger.info("Thredion Engine shutting down.")

# ── FastAPI App ───────────────────────────────────────────────

app = FastAPI(
    title="Thredion Engine",
    description=(
        "AI Cognitive Memory Engine — transforms social media saves "
        "into an intelligent, searchable, self-organizing knowledge system."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:3000",
        "http://localhost:3001",
        "https://thredion-v2.vercel.app",
        "https://thredion-ayush-raj-chourasias-projects.vercel.app",
    ],
    allow_origin_regex=r"https://thredion.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(api_router)
app.include_router(whatsapp_router)
app.include_router(cognitive_router)

# ── Health Endpoint (for Render FREE & monitoring) ──────────

@app.get("/health")
def health_check():
    """
    Simple health endpoint for deployment platforms (Render, Railway, etc).
    Used to:
    - Keep Render from spinning down if pinged regularly
    - Monitor uptime status
    - Quick startup verification
    """
    return {
        "status": "healthy",
        "service": "thredion-engine",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
    }


# ── Root Endpoint ─────────────────────────────────────────────


@app.get("/")
def root():
    return {
        "name": "Thredion Engine",
        "version": "1.0.0",
        "status": "running",
        "description": "AI Cognitive Memory Engine",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "auth_send_otp": "/auth/send-otp",
            "auth_verify_otp": "/auth/verify-otp",
            "auth_me": "/auth/me",
            "memories": "/api/memories",
            "graph": "/api/graph",
            "resurfaced": "/api/resurfaced",
            "stats": "/api/stats",
            "categories": "/api/categories",
            "random": "/api/random",
            "process": "/api/process",
            "whatsapp_webhook": "/api/whatsapp/webhook",
        },
    }


# ── Run ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
