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

# Create non-root user, pre-create the HuggingFace cache dir with correct
# ownership BEFORE the volume is mounted — this ensures Docker doesn't create
# the volume directory as root on first run.
RUN useradd -m appuser \
    && mkdir -p /app/.cache/huggingface/hub \
    && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# ── Pre-download the embedding model ─────────────────────────────────────────
# WHY THIS IS HERE (and not removed):
#   In Docker Compose, the 'hf_cache' named volume persists models across
#   container restarts — so runtime download worked fine locally.
#
#   In Kubernetes, pods use emptyDir (ephemeral) — there is NO persistent
#   HF cache volume. Every new pod downloads BAAI/bge-base-en-v1.5 (~440MB)
#   from HuggingFace at startup, taking 5–10 minutes.
#   The readiness probe fires at 45s → fails → Ansible rollout times out.
#
# WHY THIS IS FAST IN CI (not "20 min every rebuild"):
#   This layer sits AFTER pip install and BEFORE COPY . .
#   Docker only re-runs it when requirements.txt changes.
#   Code-only changes hit cache → build stays < 10 seconds.
# ─────────────────────────────────────────────────────────────────────────────
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
print('Pre-downloading BAAI/bge-base-en-v1.5 into image layer...'); \
SentenceTransformer('BAAI/bge-base-en-v1.5'); \
print('Model baked into image — K8s pods will start in seconds, not minutes.')"

# Copy application code AFTER the model download layer.
# This ordering is critical: a code-only change (e.g. fixing a typo in routes.py)
# does NOT invalidate the model layer above — Docker reuses it from cache.
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