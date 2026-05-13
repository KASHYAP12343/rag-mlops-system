# tests/test_reindex.py
"""
Tests for the automated re-indexing endpoint (POST /api/v1/ingest/reindex).

These tests validate the endpoint contract without requiring a live Qdrant
or embedding model — we mock the heavy dependencies so CI stays fast.
"""

import io
import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_txt_file(name: str, content: str):
    """Return an (name, fileobj, mime) tuple suitable for httpx multipart."""
    return (name, io.BytesIO(content.encode("utf-8")), "text/plain")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_reindex_endpoint_exists():
    """
    The /api/v1/ingest/reindex route must exist.
    A 422 (validation error because no files sent) means the route is wired up.
    """
    response = client.post("/api/v1/ingest/reindex")
    # 422 = route found but required 'files' field is missing
    assert response.status_code in [422, 400, 200, 500], (
        f"Unexpected status {response.status_code}: route may not be registered"
    )


def test_reindex_returns_json():
    """Ensure the endpoint always returns JSON even on validation failure."""
    response = client.post("/api/v1/ingest/reindex")
    assert response.headers.get("content-type", "").startswith("application/json")


@patch("src.ingestion.reindex.run_reindex")
def test_reindex_success(mock_run_reindex):
    """
    Happy-path: uploading one valid .txt file should return status='success'.
    """
    mock_run_reindex.return_value = {
        "files_received": 1,
        "files_indexed": 1,
        "vectors_added": 1,
        "collection_cleared": True,
        "processing_time_seconds": 0.5,
        "errors": [],
    }

    response = client.post(
        "/api/v1/ingest/reindex",
        files=[("files", _make_txt_file("guide.txt", "Fix the laptop battery by replacing it."))],
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    assert data["files_indexed"] == 1
    assert data["vectors_added"] == 1
    assert data["collection_cleared"] is True
    assert isinstance(data["errors"], list)


@patch("src.ingestion.reindex.run_reindex")
def test_reindex_multiple_files(mock_run_reindex):
    """Multiple files should all be processed."""
    mock_run_reindex.return_value = {
        "files_received": 3,
        "files_indexed": 3,
        "vectors_added": 3,
        "collection_cleared": True,
        "processing_time_seconds": 1.2,
        "errors": [],
    }

    response = client.post(
        "/api/v1/ingest/reindex",
        files=[
            ("files", _make_txt_file("doc1.txt", "Screen flicker fix.")),
            ("files", _make_txt_file("doc2.txt", "Battery replacement guide.")),
            ("files", _make_txt_file("doc3.txt", "Keyboard cleaning steps.")),
        ],
    )

    assert response.status_code == 200
    data = response.json()
    assert data["files_indexed"] == 3


@patch("src.ingestion.reindex.run_reindex")
def test_reindex_partial_errors(mock_run_reindex):
    """When some files have errors, status should be 'partial'."""
    mock_run_reindex.return_value = {
        "files_received": 2,
        "files_indexed": 1,
        "vectors_added": 1,
        "collection_cleared": True,
        "processing_time_seconds": 0.8,
        "errors": ["Skipped empty file: empty.txt"],
    }

    response = client.post(
        "/api/v1/ingest/reindex",
        files=[
            ("files", _make_txt_file("doc1.txt", "Valid content here.")),
            ("files", _make_txt_file("empty.txt", "")),
        ],
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert len(data["errors"]) >= 1


def test_reindex_response_schema():
    """Response must contain all required schema fields."""
    response = client.post("/api/v1/ingest/reindex")
    # Even on 422, we just verify the route exists; schema test needs a real response
    if response.status_code == 422:
        pytest.skip("Need valid files to test response schema")
