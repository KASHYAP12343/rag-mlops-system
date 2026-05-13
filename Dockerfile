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

# ── REMOVED: model pre-download ──────────────────────────────────────────────
# Previously this line added ~20 min to EVERY rebuild:
#   RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"
#
# Now the model downloads ONCE on first container startup into the
# 'hf_cache' Docker volume (see docker-compose.yml).
# Rebuilds are instant. Restarts are instant after the first run.
# ─────────────────────────────────────────────────────────────────────────────

# Create non-root user, pre-create the HuggingFace cache dir with correct
# ownership BEFORE the volume is mounted — this ensures Docker doesn't create
# the volume directory as root on first run.
RUN useradd -m appuser \
    && mkdir -p /app/.cache/huggingface/hub \
    && chown -R appuser:appuser /app

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