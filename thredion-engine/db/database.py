"""
Thredion Engine — Database Setup
SQLite database connection and session management.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import settings

# Build connection args based on database type
# check_same_thread is SQLite-only; PostgreSQL doesn't accept it
connect_args = {}
if "sqlite" in settings.DATABASE_URL.lower():
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """
    Dependency: yields a database session (with lazy init_db on first use).
    This ensures database tables exist before the session is used.
    """
    # Lazy initialize database on first use
    init_db()
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Track if database has been initialized
_db_init_attempted = False


def init_db():
    """
    Lazily initialize database tables (called on first use, not on app startup).
    This allows the app to start even if database is not immediately available.
    """
    import os
    import logging
    
    global _db_init_attempted
    
    # Only attempt initialization once
    if _db_init_attempted:
        return
    
    logger = logging.getLogger("thredion")
    is_production = os.getenv("ENVIRONMENT") == "production" or "railway" in os.getenv("HOSTNAME", "").lower()
    
    # SQLite-specific reset (delete file)
    if os.getenv("RESET_DATABASE") == "true" and "sqlite" in settings.DATABASE_URL.lower():
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        if os.path.exists(db_path):
            logger.info(f"RESET_DATABASE=true: Deleting SQLite database {db_path}")
            os.remove(db_path)
        else:
            logger.warning(f"RESET_DATABASE=true: SQLite file not found: {db_path}")
    
    # PostgreSQL reset would require dropping tables via SQL (not implemented for safety)
    if os.getenv("RESET_DATABASE") == "true" and "postgresql" in settings.DATABASE_URL.lower():
        logger.warning("RESET_DATABASE=true: PostgreSQL reset not implemented (manual drop required for safety)")
    
    try:
        from db.models import User, OTPCode, Memory, Connection, ResurfacedMemory  # noqa: F401
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables ensured to exist")

        # ── Auto-migrations: add columns introduced after initial deploy ──
        _run_auto_migrations(engine, settings.DATABASE_URL)

        _db_init_attempted = True
    except Exception as e:
        _db_init_attempted = True  # Mark as attempted to avoid repeated failures
        if is_production:
            # In production (Railway/Supabase), tables should already exist from migration
            # Log the error but don't crash the app
            logger.warning(f"⚠ Could not create/verify database tables (expected in production): {type(e).__name__}: {str(e)}")
            logger.warning("  Tables should exist from Supabase migration. If missing, run migrations manually.")
            logger.warning("  App can function without this - database will be used when first needed.")
        else:
            # In development, this is a real error
            logger.error(f"✗ Failed to initialize database: {e}", exc_info=True)
            raise


def _run_auto_migrations(engine, db_url: str):
    """Apply incremental schema changes that are safe to run on every startup.
    Uses IF NOT EXISTS / IF EXISTS guards so they are idempotent.
    """
    import logging as _logging
    _logger = _logging.getLogger("thredion")

    if "postgresql" not in db_url.lower():
        # SQLite: create_all() above already handles new columns via ORM
        return

    pg_migrations = [
        # Migration 003 – thumbnail_url on memories
        "ALTER TABLE memories ADD COLUMN IF NOT EXISTS thumbnail_url VARCHAR(2048) DEFAULT '';",
        # Migration 003 – cognitive_entries & buckets tables (created by ORM but guard here too)
        # (no-op if already present)
    ]

    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            for stmt in pg_migrations:
                try:
                    conn.execute(text(stmt))
                except Exception as col_err:
                    _logger.warning(f"Auto-migration step skipped ({col_err}): {stmt[:80]}")
            conn.commit()
        _logger.info("✓ Auto-migrations applied")
    except Exception as e:
        _logger.warning(f"⚠ Auto-migrations failed (non-fatal): {e}")
