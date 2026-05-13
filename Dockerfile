# Use lightweight Python base image
FROM python:3.12-slim

# Environment variables for Python & FastAPI
# HF_HOME: set to a path inside /app so it's accessible to appuser after chown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app \
    HF_HOME=/app/.cache/huggingface

WORKDIR $APP_HOME

# Install system dependencies required by PyTorch & health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy & install Python dependencies FIRST (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model into the image during build.
# This runs as root so the download goes to HF_HOME=/app/.cache/huggingface.
# The single uvicorn worker will find the model already cached on startup.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"

# Create non-root user and give it ownership of the entire /app dir
# (including the downloaded model cache)
RUN useradd -m appuser && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Copy application code with correct ownership
COPY --chown=appuser:appuser . .

# Expose API port
EXPOSE 8000

# Health check: verifies FastAPI liveness endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

# CHANGE: --workers reduced from 2 → 1
# With 8 GB total, running 2 workers doubles the RAM used by the model (~900 MB each).
# 1 worker is sufficient for a demo/local environment.
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]