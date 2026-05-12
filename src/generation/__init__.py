# src/generation/__init__.py
"""Generation module: Handles prompt engineering & LLM answer generation."""
from .llm_client import GroqLLMClient
from .prompt_templates import FALLBACK_RESPONSE
__all__ = ["GroqLLMClient", "FALLBACK_RESPONSE"]