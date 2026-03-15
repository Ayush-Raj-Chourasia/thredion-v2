# ── Thredion Engine Docker Image for Render
# Optimized for Render Free tier (cold starts, limited RAM)

FROM python:3.11-slim

# Metadata
LABEL maintainer="Thredion Team"
LABEL description="Thredion Engine - AI Cognitive Memory Engine"

# Set working directory
WORKDIR /app

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies
# Keep minimal to reduce image size for faster startups
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application code
COPY . .

# Health check for deployment platforms
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import os, requests; port = os.environ.get('PORT', '8000'); requests.get(f'http://localhost:{port}/health', timeout=5)" || exit 1

# Expose port (Render/Railway automatically detects from EXPOSE or PORT env var)
EXPOSE 8000

# Run with Gunicorn for production
# Workers: 1 (Free tiers have limited RAM)
# Threads: 4 (efficient for I/O-bound operations)
# Worker class: uvicorn (async support for FastAPI)
# Using shell form to correctly evaluate the $PORT variable provided by Railway
CMD gunicorn main:app --workers=1 --worker-class=uvicorn.workers.UvicornWorker --bind=0.0.0.0:${PORT:-8000} --timeout=120 --access-logfile=- --error-logfile=-
