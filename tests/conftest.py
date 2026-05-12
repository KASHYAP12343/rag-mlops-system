import sys
from unittest.mock import MagicMock

sys.modules['sentence_transformers'] = MagicMock()
sys.modules['groq'] = MagicMock()

from fastapi.testclient import TestClient
from src.api.app import app

client = TestClient(app)
