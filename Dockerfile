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

# ── LAYER SPLIT STRATEGY ──────────────────────────────────────────────────────
# torch CPU is ~700 MB uncompressed. By installing it in its OWN layer BEFORE
# the rest of requirements.txt, Docker caches it separately.
# Result: code changes or dep bumps only re-push the small top layers (~50 MB),
# NOT the torch layer. This cuts push time from ~1 hour → ~2 minutes on most runs.
# ─────────────────────────────────────────────────────────────────────────────
COPY requirements-torch.txt .
RUN pip install --no-cache-dir -f https://download.pytorch.org/whl/torch_stable.html \
    -r requirements-torch.txt

# Install remaining dependencies (changes more often — kept in separate layer)
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

# Copy application code with correct ownership
COPY --chown=appuser:appuser . .

# Expose API port
EXPOSE 8000

# Health check: verifies FastAPI liveness endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]