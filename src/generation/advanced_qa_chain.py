# src/generation/advanced_qa_chain.py
"""
Advanced QA Pipeline Orchestrator.

Implements the full proposed architecture:

    History + User Query
           ↓
    LLM → N independent queries (QueryGenerator)
           ↓
    Retrieve top-K per query → Union → Rerank → top-K final chunks
    (MultiQueryRetriever)             (Reranker)
           ↓
    Final LLM (History + Original Query + Generated Queries + Final Chunks)
    (GroqLLMClient)
           ↓
    Save turn to memory, return structured result

This class is a drop-in replacement for QAPipeline in the advanced route.
The original QAPipeline in qa_chain.py is untouched for backward compatibility.
"""

import time
from typing import Dict, List, Optional

from src.retrieval.multi_retriever import MultiQueryRetriever
from src.retrieval.query_generator import QueryGenerator
from src.retrieval.reranker import Reranker
from src.generation.llm_client import GroqLLMClient
from src.generation.prompt_templates import (
    FINAL_ANSWER_SYSTEM_PROMPT,
    FALLBACK_RESPONSE,
    build_final_answer_prompt,
)
from src.memory.conversation_memory import memory_store
from src.utils.logger import get_logger
from src.utils.config import settings

logger = get_logger(__name__)


class AdvancedQAPipeline:
    """
    End-to-end advanced RAG pipeline with multi-query, reranking, and memory.

    Usage:
        pipeline = AdvancedQAPipeline(
            multi_retriever=mretriever,
            query_generator=gen,
            reranker=reranker,
            llm_client=llm,
        )
        result = pipeline.process(
            question="My laptop screen flickers randomly",
            session_id="abc-123",         # optional, omit for stateless
        )
        print(result["answer"])
    """

    def __init__(
        self,
        multi_retriever: MultiQueryRetriever,
        query_generator: QueryGenerator,
        reranker: Reranker,
        llm_client: GroqLLMClient,
    ):
        self.multi_retriever = multi_retriever
        self.query_generator  = query_generator
        self.reranker         = reranker
        self.llm_client       = llm_client

    def process(
        self,
        question: str,
        session_id: Optional[str] = None,
    ) -> Dict:
        start_time = time.time()
        logger.info(
            "🚀 Advanced pipeline | session='{}' | question='{}'",
            (session_id or "stateless")[:8],
            question[:60],
        )

        logger.bind(query=question).info("rag_query_received")

        try:
            # ── Step 0: Load conversation history ────────────────────────────────
            conversation_history = ""
            turn_number = 1
            if session_id:
                conversation_history = memory_store.format_history_for_prompt(session_id)
                turn_number = memory_store.get_turn_count(session_id) + 1
                if conversation_history:
                    logger.info(
                        "📜 Loaded {} prior turn(s) for session '{}'",
                        turn_number - 1,
                        session_id[:8],
                    )

            # ── Step 1: Generate alternative queries ─────────────────────────────
            generated_queries = self.query_generator.generate(
                original_question=question,
                conversation_history=conversation_history,
            )

            # Combine: original query is ALWAYS searched too
            all_queries = [question] + generated_queries

            # ── Step 2: Parallel retrieval → union → dedup ────────────────────────
            candidate_chunks = self.multi_retriever.search_all(
                queries=all_queries,
                top_k_per_query=settings.TOP_K,
            )

            # ── Step 3: Graceful fallback if nothing retrieved ───────────────────
            if not candidate_chunks:
                logger.info("ℹ️ No chunks retrieved — returning fallback response")
                result = {
                    "answer":                  FALLBACK_RESPONSE,
                    "generated_queries":       generated_queries,
                    "chunks_used":             0,
                    "retrieved_contexts":      [],
                    "processing_time_seconds": round(time.time() - start_time, 2),
                    "session_id":              session_id,
                    "turn_number":             turn_number,
                }
                # Save to memory even on fallback so history stays coherent
                if session_id:
                    memory_store.add_turn(session_id, question, FALLBACK_RESPONSE)
                
                logger.bind(
                    query=question,
                    response_length=len(FALLBACK_RESPONSE),
                    retrieved_docs=0
                ).info("rag_response_generated")
                
                return result

            # ── Step 4: Rerank → keep top-K final chunks ─────────────────────────
            reranked_chunks = self.reranker.rerank(
                original_query=question,
                generated_queries=generated_queries,
                chunks=candidate_chunks,
                top_k=settings.RERANKER_TOP_K,
            )

            # ── Step 5: Build final prompt ────────────────────────────────────────
            user_prompt = build_final_answer_prompt(
                original_question=question,
                generated_queries=generated_queries,
                reranked_chunks=reranked_chunks,
                conversation_history=conversation_history,
            )

            # ── Step 6: Generate final answer via Groq ───────────────────────────
            answer = self.llm_client.generate(
                system_prompt=FINAL_ANSWER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )

            elapsed = round(time.time() - start_time, 2)

            logger.info(
                "✅ Advanced pipeline complete in {}s | {} candidate → {} reranked chunks | turn {}",
                elapsed,
                len(candidate_chunks),
                len(reranked_chunks),
                turn_number,
            )

            # ── Step 7: Persist this turn to memory ──────────────────────────────
            if session_id:
                memory_store.add_turn(session_id, question, answer)

            logger.bind(
                query=question,
                response_length=len(answer),
                retrieved_docs=len(reranked_chunks)
            ).info("rag_response_generated")

            return {
                "answer":                  answer,
                "generated_queries":       generated_queries,
                "chunks_used":             len(reranked_chunks),
                "retrieved_contexts":      reranked_chunks,
                "processing_time_seconds": elapsed,
                "session_id":              session_id,
                "turn_number":             turn_number,
            }

        except Exception as e:
            logger.exception("rag_pipeline_failed")
            raise
