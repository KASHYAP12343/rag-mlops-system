# src/api/routes.py

import time
import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
from groq import Groq

from src.utils.config import settings
from src.utils.logger import get_logger
from src.utils.timer import timing, timer, format_duration
from src.api.models import (
    IngestRequest, IngestResponse,
    HealthResponse, StatsResponse, ResetRequest, ResetResponse, ErrorResponse,
    AdvancedQueryRequest, AdvancedQueryResponse, AdvancedQueryDebugResponse,
    ClearHistoryResponse, ReindexResponse,
)
from src.api.dependencies import (
    get_embedding_model_dep, get_qdrant_client_dep, get_groq_client_dep,
    check_qdrant_health, check_groq_health, get_reranker_dep,
)

from src.retrieval.multi_retriever import MultiQueryRetriever
from src.retrieval.query_generator import QueryGenerator
from src.retrieval.reranker import Reranker
from src.generation.llm_client import GroqLLMClient
from src.generation.advanced_qa_chain import AdvancedQAPipeline
from src.generation.prompt_templates import FALLBACK_RESPONSE
from src.memory.conversation_memory import memory_store

from src.ingestion.embedder import TextEmbedder
from src.ingestion.indexer import VectorIndexer

router = APIRouter(prefix="/api/v1")
logger = get_logger(__name__)


@router.post("/ingest", response_model=IngestResponse)
@timing
async def ingest_file(
    file: UploadFile = File(...),
    request: IngestRequest = Depends(),
    qdrant_client: QdrantClient = Depends(get_qdrant_client_dep),
    embedding_model: SentenceTransformer = Depends(get_embedding_model_dep)
):
    start_time = time.time()
    logger.info(f"📥 Starting API ingestion: {file.filename}")

    try:
        content = await file.read()
        text = content.decode("utf-8").strip()

        if not text:
            raise ValueError("Uploaded file is empty")

        with timer("Generating embedding"):
            embedder = TextEmbedder()
            embedder.model = embedding_model
            vector = embedder.encode_texts([text])[0]

        with timer("Uploading to Qdrant"):
            indexer = VectorIndexer()
            indexer.client = qdrant_client

            vector_dim = len(vector)
            indexer.ensure_collection(vector_size=vector_dim)

            # Use deterministic UUID from filename so re-uploading replaces the same vector
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, file.filename))

            point = PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "text": text,
                    "source": file.filename,
                    "ingested_at": time.time(),
                    "char_count": len(text)
                }
            )

            qdrant_client.upsert(
                collection_name=settings.COLLECTION_NAME,
                points=[point]
            )

        elapsed = time.time() - start_time
        logger.info(f"✅ Ingested '{file.filename}' in {elapsed:.2f}s")

        return IngestResponse(
            status="success",
            filename=file.filename,
            chunks_created=1,
            vectors_added=1,
            processing_time_seconds=round(elapsed, 2),
            message="File indexed successfully"
        )

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"❌ Ingestion failed for {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion error: {str(e)}")


# ---------------------------------------------------------------------------
# Automated Re-indexing Endpoint  (Innovation Feature)
# ---------------------------------------------------------------------------

@router.post(
    "/ingest/reindex",
    response_model=ReindexResponse,
    summary="Bulk re-index: clear collection and rebuild from uploaded documents",
    description=(
        "Upload one or more .txt files. The existing Qdrant collection is **cleared** "
        "and all documents are re-embedded and re-uploaded. This enables live knowledge "
        "base updates without restarting the server."
    ),
    tags=["Ingestion"],
)
async def reindex_documents(
    files: List[UploadFile] = File(..., description="One or more .txt files to re-index"),
    qdrant_client: QdrantClient = Depends(get_qdrant_client_dep),
    embedding_model: SentenceTransformer = Depends(get_embedding_model_dep),
):
    """
    Automated re-indexing pipeline (MLOps innovation feature).

    Workflow:
        1. Read and decode all uploaded .txt files
        2. Delete the current Qdrant collection (full rebuild)
        3. Generate fresh embeddings using the live embedding model
        4. Upload all new vectors to Qdrant
        5. Return a detailed pipeline report
    """
    from src.ingestion.reindex import run_reindex

    logger.info("🔄 Re-index request received | file_count={}", len(files))

    # ── Read uploaded files ──────────────────────────────────────────────
    file_contents: List[tuple] = []
    read_errors: List[str] = []

    for upload in files:
        try:
            raw = await upload.read()
            text = raw.decode("utf-8")
            file_contents.append((upload.filename, text))
        except Exception as e:
            msg = f"Failed to read '{upload.filename}': {e}"
            logger.warning(msg)
            read_errors.append(msg)

    if not file_contents:
        raise HTTPException(
            status_code=400,
            detail="No files could be read. Ensure you upload valid UTF-8 .txt files.",
        )

    # ── Run the pipeline ─────────────────────────────────────────────────
    try:
        result = run_reindex(
            files=file_contents,
            qdrant_client=qdrant_client,
            embedding_model=embedding_model,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("❌ Re-index pipeline failed: {}", str(e))
        raise HTTPException(status_code=500, detail=f"Re-index error: {str(e)}")

    all_errors = read_errors + result.get("errors", [])
    status = "success" if not all_errors else "partial"

    return ReindexResponse(
        status=status,
        files_received=result["files_received"],
        files_indexed=result["files_indexed"],
        vectors_added=result["vectors_added"],
        collection_cleared=result["collection_cleared"],
        processing_time_seconds=result["processing_time_seconds"],
        errors=all_errors,
        message=(
            f"Re-indexed {result['files_indexed']} documents successfully."
            if not all_errors
            else f"Re-indexed {result['files_indexed']} documents with {len(all_errors)} error(s)."
        ),
    )



@router.get("/health", response_model=HealthResponse)
async def health_check(
    qdrant_client: QdrantClient = Depends(get_qdrant_client_dep),
    groq_client: Groq = Depends(get_groq_client_dep)
):
    logger.debug("🏥 Running health check")

    qdrant_status = check_qdrant_health(qdrant_client)
    groq_status = check_groq_health(groq_client)

    if qdrant_status["status"] == "connected" and groq_status["status"] == "available":
        overall_status = "healthy"
    elif qdrant_status["status"] == "error" or groq_status["status"] == "error":
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        components={
            "qdrant": qdrant_status,
            "groq_api": groq_status,
            "embedding_model": {"status": "loaded", "model": settings.EMBEDDING_MODEL}
        }
    )


@router.get("/stats", response_model=StatsResponse)
@timing
async def get_stats(
    qdrant_client: QdrantClient = Depends(get_qdrant_client_dep)
):
    try:
        collection_info = qdrant_client.get_collection(settings.COLLECTION_NAME)
        total_vectors = collection_info.points_count or 0

        return StatsResponse(
            collection_name=settings.COLLECTION_NAME,
            total_vectors=total_vectors,
            total_files=total_vectors,
            vector_dimension=collection_info.config.params.vectors.size,
            last_updated=None
        )

    except Exception as e:
        logger.error(f"❌ Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=f"Could not retrieve stats: {str(e)}")


@router.delete("/reset", response_model=ResetResponse)
@timing
async def reset_database(
    request: ResetRequest,
    qdrant_client: QdrantClient = Depends(get_qdrant_client_dep)
):
    logger.warning("🗑️ Database reset requested")

    try:
        if not request.confirm:
            raise ValueError("Explicit confirmation required")

        qdrant_client.delete_collection(settings.COLLECTION_NAME)
        logger.info(f"✅ Deleted collection: {settings.COLLECTION_NAME}")

        return ResetResponse(
            status="success",
            message=f"Collection '{settings.COLLECTION_NAME}' deleted successfully",
            vectors_deleted=None
        )

    except Exception as e:
        logger.error(f"❌ Reset failed: {e}")
        raise HTTPException(status_code=400, detail=f"Reset error: {str(e)}")


# ===========================================================================
# Advanced RAG Endpoints (Multi-Query + Reranking + Memory)
# ===========================================================================

@router.post("/advanced_query", response_model=AdvancedQueryResponse)
@timing
def advanced_query_endpoint(
    request: AdvancedQueryRequest,
    qdrant_client: QdrantClient = Depends(get_qdrant_client_dep),
    embedding_model: SentenceTransformer = Depends(get_embedding_model_dep),
    groq_client: Groq = Depends(get_groq_client_dep),
    reranker: Reranker = Depends(get_reranker_dep),
):
    """
    Advanced RAG endpoint with multi-query expansion, cross-encoder reranking,
    and optional conversation memory.

    Pipeline:
        History + Question → LLM generates N queries
        → Parallel Qdrant search for each query
        → Union + Deduplicate results
        → Cross-Encoder rerank → top-K chunks
        → Final LLM (History + all queries + reranked chunks)
        → Save turn to memory (if session_id provided)

    Pass a `session_id` UUID to enable multi-turn conversation memory.
    Omit it (or pass null) for stateless single-turn queries.
    """
    logger.info(
        "🚀 Advanced query | session='{}' | question='{}'...",
        (request.session_id or "stateless")[:8],
        request.question[:60],
    )

    try:
        multi_retriever = MultiQueryRetriever(qdrant_client, embedding_model)
        query_generator = QueryGenerator(groq_client)
        llm_client      = GroqLLMClient(groq_client)
        pipeline        = AdvancedQAPipeline(
            multi_retriever=multi_retriever,
            query_generator=query_generator,
            reranker=reranker,
            llm_client=llm_client,
        )

        result = pipeline.process(
            question=request.question,
            session_id=request.session_id,
        )

        return AdvancedQueryResponse(
            question=request.question,
            answer=result["answer"],
            generated_queries=result["generated_queries"],
            chunks_used=result["chunks_used"],
            processing_time_seconds=result["processing_time_seconds"],
            session_id=result["session_id"],
            turn_number=result["turn_number"],
        )

    except Exception as e:
        logger.error("❌ Advanced query failed: {}", str(e))
        raise HTTPException(status_code=500, detail=f"Advanced query error: {str(e)}")


@router.post("/advanced_query_debug", response_model=AdvancedQueryDebugResponse)
@timing
def advanced_query_debug_endpoint(
    request: AdvancedQueryRequest,
    qdrant_client: QdrantClient = Depends(get_qdrant_client_dep),
    embedding_model: SentenceTransformer = Depends(get_embedding_model_dep),
    groq_client: Groq = Depends(get_groq_client_dep),
    reranker: Reranker = Depends(get_reranker_dep),
):
    """
    Same as /advanced_query but includes the raw reranked chunks in the response
    (text, source, bi-encoder score, reranker_score) for inspection and debugging.
    Memory is NOT saved on debug calls to avoid polluting conversation history.
    """
    try:
        multi_retriever = MultiQueryRetriever(qdrant_client, embedding_model)
        query_generator = QueryGenerator(groq_client)
        llm_client      = GroqLLMClient(groq_client)
        pipeline        = AdvancedQAPipeline(
            multi_retriever=multi_retriever,
            query_generator=query_generator,
            reranker=reranker,
            llm_client=llm_client,
        )

        # Run stateless (no session_id) so debug calls don't pollute memory
        result = pipeline.process(
            question=request.question,
            session_id=None,
        )

        return AdvancedQueryDebugResponse(
            question=request.question,
            answer=result["answer"],
            generated_queries=result["generated_queries"],
            chunks_used=result["chunks_used"],
            processing_time_seconds=result["processing_time_seconds"],
            session_id=None,
            turn_number=1,
            retrieved_contexts=result["retrieved_contexts"],
        )

    except Exception as e:
        logger.error("❌ Advanced debug query failed: {}", str(e))
        raise HTTPException(status_code=500, detail=f"Debug query error: {str(e)}")


@router.delete("/session/{session_id}", response_model=ClearHistoryResponse)
async def clear_session_history(session_id: str):
    """
    Clear conversation history for a specific session.

    Use this when the user wants to start a fresh conversation
    without changing their session_id.
    """
    cleared = memory_store.clear(session_id)
    if cleared:
        return ClearHistoryResponse(
            status="cleared",
            session_id=session_id,
            message=f"Conversation history for session '{session_id}' has been cleared.",
        )
    else:
        return ClearHistoryResponse(
            status="not_found",
            session_id=session_id,
            message=f"No history found for session '{session_id}'.",
        )