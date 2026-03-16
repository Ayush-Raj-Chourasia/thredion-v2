"""
Thredion Engine — Configuration
Central configuration management for the cognitive memory engine.
Supports: SQLite (local), PostgreSQL (Azure/Supabase), and managed deployments.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# On Azure Linux App Service, /home is persistent across deploys.
# Locally, use ./thredion.db in the current directory.
_default_db_path = "sqlite:///./thredion.db"
if os.path.isdir("/home"):
    os.makedirs("/home/data", exist_ok=True)
    _default_db_path = "sqlite:////home/data/thredion.db"


class Settings:
    # ── Database ──────────────────────────────────────────────
    # Priority: 1) DATABASE_URL env var (explicit, e.g., PostgreSQL password)
    #           2) SUPABASE_URL + SUPABASE_DB_PASSWORD → PostgreSQL
    #           3) SQLite default (local dev, always works)
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    SUPABASE_DB_PASSWORD: str = os.getenv("SUPABASE_DB_PASSWORD", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", _default_db_path)
    
    # Auto-construct PostgreSQL connection string from Supabase if we have REAL password
    # NOTE: SUPABASE_KEY (anon API key) is NOT a valid PostgreSQL password
    if SUPABASE_URL and SUPABASE_DB_PASSWORD:
        from urllib.parse import quote_plus
        # Supabase URL format: https://xxxxxxxxxxxx.supabase.co
        # Extract project ID and construct PostgreSQL connection with REAL password
        _project_id = SUPABASE_URL.split("//")[1].split(".")[0]
        _encoded_pw = quote_plus(SUPABASE_DB_PASSWORD)
        DATABASE_URL = f"postgresql+psycopg2://postgres:{_encoded_pw}@db.{_project_id}.supabase.co:5432/postgres"
    elif SUPABASE_URL and not SUPABASE_DB_PASSWORD:
        # SUPABASE_URL set but no SUPABASE_DB_PASSWORD → use SQLite
        # This allows app to run locally; production use requires real password
        pass  # DATABASE_URL already set to default SQLite

    # ── OpenAI ────────────────────────────────────────────────
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # ── Groq Cloud LLM (FREE TIER) ────────────────────────────
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    # ── HuggingFace (Optional) ────────────────────────────────
    HF_API_TOKEN: str = os.getenv("HF_API_TOKEN", "")
    USE_HF_INFERENCE: bool = os.getenv("USE_HF_INFERENCE", "false").lower() == "true"

    # ── Azure Queue Storage (for async jobs) ──────────────────
    AZURE_QUEUE_CONNECTION_STRING: str = os.getenv("AZURE_QUEUE_CONNECTION_STRING", "")
    AZURE_QUEUE_NAME: str = os.getenv("AZURE_QUEUE_NAME", "video-transcription-jobs")

    # ── Video Processing Thresholds ───────────────────────────
    SHORT_VIDEO_MAX_DURATION: int = int(os.getenv("SHORT_VIDEO_MAX_DURATION", "300"))  # 5 min
    MEDIUM_VIDEO_MAX_DURATION: int = int(os.getenv("MEDIUM_VIDEO_MAX_DURATION", "1800"))  # 30 min
    WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "base")  # base, tiny, small

    # ── Twilio WhatsApp ───────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_NUMBER: str = os.getenv("TWILIO_WHATSAPP_NUMBER", "")

    # ── External Extractors (Premium Fallbacks) ───────────────
    SUPADATA_API_KEY: str = os.getenv("SUPADATA_API_KEY", "")
    SOCIALKIT_API_KEY: str = os.getenv("SOCIALKIT_API_KEY", "")

    # ── Authentication ────────────────────────────────────────
    JWT_SECRET: str = os.getenv("JWT_SECRET", "thredion-secret-change-in-prod")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = int(os.getenv("JWT_EXPIRY_HOURS", "168"))  # 7 days
    OTP_EXPIRY_MINUTES: int = int(os.getenv("OTP_EXPIRY_MINUTES", "5"))

    # ── Embedding Configuration ───────────────────────────────
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers")
    EMBEDDING_DIMENSION: int = 384  # MiniLM-L6-v2 dimension

    # ── Cognitive Thresholds ──────────────────────────────────
    SIMILARITY_THRESHOLD: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.55"))
    RESURFACING_THRESHOLD: float = float(os.getenv("RESURFACING_THRESHOLD", "0.60"))
    MAX_CONNECTIONS: int = int(os.getenv("MAX_CONNECTIONS", "5"))

    # ── Categories ────────────────────────────────────────────
    CATEGORIES: list = [
        "Fitness", "Coding", "Design", "Food", "Travel",
        "Business", "Science", "Music", "Art", "Fashion",
        "Education", "Technology", "Health", "Finance", "Motivation",
        "Entertainment", "Sports", "Lifestyle", "DIY", "Photography",
    ]

    # ── Frontend ──────────────────────────────────────────────
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # ── Server ────────────────────────────────────────────────
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
