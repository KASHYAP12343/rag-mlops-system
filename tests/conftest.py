import os
import sys
from unittest.mock import MagicMock

# ── Mock heavy dependencies before any app import ────────────────────────────
# These are not installed in CI (requirements-ci.txt is lightweight).
# We mock them here so FastAPI app imports succeed without PyTorch or Qdrant.

# sentence-transformers + torch
sys.modules['sentence_transformers'] = MagicMock()
sys.modules['torch'] = MagicMock()

# groq LLM client
sys.modules['groq'] = MagicMock()

# qdrant_client — full module tree needed because routes.py does:
#   from qdrant_client import QdrantClient
#   from qdrant_client.models import Distance, VectorParams, PointStruct
_qdrant_mock = MagicMock()
_qdrant_mock.models = MagicMock()
sys.modules['qdrant_client'] = _qdrant_mock
sys.modules['qdrant_client.models'] = _qdrant_mock.models
sys.modules['qdrant_client.http'] = MagicMock()
sys.modules['qdrant_client.http.models'] = MagicMock()

# ── Ensure required env vars exist for tests ─────────────────────────────────
os.environ.setdefault("GROQ_API_KEY", "test-key-ci")
os.environ.setdefault("QDRANT_HOST", "localhost")
os.environ.setdefault("QDRANT_PORT", "6333")

# ── Now import the FastAPI app and create test client ────────────────────────
from fastapi.testclient import TestClient
from src.api.app import app

client = TestClient(app)
