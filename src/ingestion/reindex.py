# src/ingestion/reindex.py
"""
Automated Re-indexing Pipeline (Innovation Feature)

This module implements a live re-indexing capability that allows the system to
accept new document uploads via the API, clear the existing Qdrant collection,
regenerate all embeddings, and rebuild the knowledge base — all without
restarting the server.

Flow:
    POST /api/v1/ingest/reindex (upload N .txt files)
    → Validate files
    → Clear existing Qdrant collection
    → Generate embeddings in batches
    → Upload new vectors to Qdrant
    → Return detailed report
"""

import uuid
import time
from typing import List, Tuple

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer

from src.utils.config import settings
from src.utils.logger import get_logger
from src.ingestion.embedder import TextEmbedder
from src.ingestion.indexer import VectorIndexer

logger = get_logger(__name__)


def run_reindex(
    files: List[Tuple[str, str]],   # list of (filename, text_content)
    qdrant_client: QdrantClient,
    embedding_model: SentenceTransformer,
    batch_size: int = 32,
) -> dict:
    """
    Core re-indexing function.

    Args:
        files:           List of (filename, text_content) tuples from uploaded files.
        qdrant_client:   Shared Qdrant client (injected from FastAPI dependency).
        embedding_model: Shared SentenceTransformer model.
        batch_size:      Number of texts to embed per batch.

    Returns:
        dict with keys: files_received, vectors_added, collection_cleared,
                        processing_time_seconds, errors
    """
    start = time.time()
    errors: List[str] = []
    vectors_added = 0

    logger.info(
        "🔄 Re-index pipeline started | files={} | collection={}",
        len(files),
        settings.COLLECTION_NAME,
    )

    # -----------------------------------------------------------------------
    # Step 1 — Validate inputs
    # -----------------------------------------------------------------------
    valid_files: List[Tuple[str, str]] = []
    for filename, text in files:
        if not text.strip():
            msg = f"Skipped empty file: {filename}"
            logger.warning(msg)
            errors.append(msg)
        else:
            valid_files.append((filename, text.strip()))

    if not valid_files:
        raise ValueError("No valid (non-empty) files provided for re-indexing.")

    # -----------------------------------------------------------------------
    # Step 2 — Clear existing collection
    # -----------------------------------------------------------------------
    try:
        qdrant_client.delete_collection(settings.COLLECTION_NAME)
        logger.info("🗑️  Cleared existing collection: {}", settings.COLLECTION_NAME)
        collection_cleared = True
    except Exception as e:
        # Collection may not exist on first run — that is fine
        logger.warning("Collection not found or delete failed (may be first run): {}", str(e))
        collection_cleared = False

    # -----------------------------------------------------------------------
    # Step 3 — Generate embeddings
    # -----------------------------------------------------------------------
    logger.info("🧠 Generating embeddings for {} documents...", len(valid_files))
    embedder = TextEmbedder(batch_size=batch_size)
    embedder.model = embedding_model  # reuse the already-loaded model

    all_texts = [text for _, text in valid_files]
    all_filenames = [fname for fname, _ in valid_files]

    embeddings = embedder.encode_texts(all_texts)
    logger.info("✅ Generated {} embeddings", len(embeddings))

    # -----------------------------------------------------------------------
    # Step 4 — Re-create collection and upload vectors
    # -----------------------------------------------------------------------
    indexer = VectorIndexer()
    indexer.client = qdrant_client

    vector_dim = len(embeddings[0])
    indexer.ensure_collection(vector_size=vector_dim)

    points: List[PointStruct] = []
    for i, (filename, text) in enumerate(valid_files):
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, filename))
        points.append(
            PointStruct(
                id=point_id,
                vector=embeddings[i],
                payload={
                    "text": text,
                    "source": filename,
                    "reindexed_at": time.time(),
                    "char_count": len(text),
                },
            )
        )

    vectors_added = indexer.upload_points(points=points, batch_size=100)
    logger.info(
        "☁️  Uploaded {} vectors to collection '{}'",
        vectors_added,
        settings.COLLECTION_NAME,
    )

    elapsed = round(time.time() - start, 2)
    logger.info("🎉 Re-index complete in {}s", elapsed)

    return {
        "files_received": len(files),
        "files_indexed": len(valid_files),
        "vectors_added": vectors_added,
        "collection_cleared": collection_cleared,
        "processing_time_seconds": elapsed,
        "errors": errors,
    }
