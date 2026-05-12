# src/api/app.py

from fastapi import FastAPI, Request
from fastapi import status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from src.utils.config import settings
from src.utils.logger import setup_logger, get_logger
from src.api.routes import router as api_router
from src.api.models import ErrorResponse

setup_logger(log_level=settings.LOG_LEVEL, log_file=settings.LOG_FILE)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting Laptop Troubleshooting RAG API...")

    try:
        from src.api.dependencies import get_embedding_model, get_qdrant_client, get_groq_client

        logger.info("Pre-loading embedding model...")
        get_embedding_model()

        logger.info("Connecting to Qdrant...")
        get_qdrant_client()

        logger.info("Initializing Groq client...")
        get_groq_client()

        logger.info("✓ All resources pre-loaded successfully")

    except Exception as e:
        logger.error("Failed to initialize resources: {}", str(e))

    yield

    logger.info("🛑 Shutting down API server...")
    logger.info("✓ Shutdown complete")


app = FastAPI(
    title="Laptop Troubleshooting RAG API",
    description="""
    AI-powered laptop troubleshooting assistant.

    ## Features
    - **Ingest**: Upload preprocessed .txt manuals to build knowledge base
    - **Query**: Ask natural language questions, get step-by-step answers
    - **Debug**: Inspect retrieved contexts for transparency
    - **Monitor**: Health checks and statistics endpoints
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Structured request logging middleware.
    """

    import time
    start_time = time.time()

    response = await call_next(request)

    process_time = round((time.time() - start_time) * 1000, 2)

    logger.bind(
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=process_time,
        client=request.client.host if request.client else None
    ).info("request_processed")

    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all error handler for unhandled exceptions.

    FIX: Do NOT use f-strings with loguru. Loguru applies its own .format()
    pass on the message string after Python's f-string substitution runs.
    If str(exc) contains curly braces (e.g. dict reprs like {'type': ...}),
    loguru's format pass interprets them as named placeholders and raises
    KeyError. Use loguru's own {} placeholder style instead.
    """
    exc_str = type(exc).__name__ + ": " + str(exc)
    logger.error("Unhandled exception: {}", exc_str)

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=type(exc).__name__,
            message="An internal server error occurred. Please try again or contact support.",
            details={"path": str(request.url)} if settings.LOG_LEVEL == "DEBUG" else None
        ).model_dump()
    )


app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "message": "Laptop Troubleshooting RAG API is running!",
        "docs": "/docs",
        "health": "/api/v1/health"
    }


# -----------------------------
# Liveness Probe
# -----------------------------
@app.get(
    "/health",
    tags=["Monitoring"],
    status_code=status.HTTP_200_OK
)
async def health_check():
    """
    Lightweight liveness probe.

    Used by:
    - Docker healthcheck
    - Kubernetes livenessProbe
    """
    return {
        "status": "healthy",
        "service": "rag-api"
    }


# -----------------------------
# Readiness Probe
# -----------------------------
@app.get(
    "/ready",
    tags=["Monitoring"],
    status_code=status.HTTP_200_OK
)
async def readiness_check():
    """
    Readiness probe.

    Verifies critical dependencies are available before
    receiving traffic from Kubernetes.
    """

    dependencies = {
        "embedding_model": False,
        "qdrant": False,
        "groq_client": False
    }

    try:
        from src.api.dependencies import (
            get_embedding_model,
            get_qdrant_client,
            get_groq_client
        )

        # Validate embedding model
        embedding_model = get_embedding_model()
        if embedding_model:
            dependencies["embedding_model"] = True

        # Validate Qdrant connection
        qdrant_client = get_qdrant_client()
        qdrant_client.get_collections()
        dependencies["qdrant"] = True

        # Validate Groq client
        groq_client = get_groq_client()
        if groq_client:
            dependencies["groq_client"] = True

        all_ready = all(dependencies.values())

        return {
            "status": "ready" if all_ready else "not_ready",
            "dependencies": dependencies
        }

    except Exception as e:
        logger.exception("Readiness check failed")

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "dependencies": dependencies,
                "error": str(e)
            }
        )

logger.info("✓ FastAPI app initialized | Docs: http://localhost:8000/docs")