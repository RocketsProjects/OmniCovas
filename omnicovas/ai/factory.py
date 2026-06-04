"""
omnicovas.ai.factory

Provider factory — selects an AIProvider based on user config.

Law 4 (AI Provider Agnosticism):
    Single entry point for the rest of the system.
    Core code calls factory.get_provider(config) once at startup
    and then interacts only with the returned AIProvider interface.

See: Master Blueprint v4.0 Section 5 (AI Modes)
See: Phase 1 Development Guide Week 4, Part A
"""

from __future__ import annotations

import logging

from omnicovas.ai.gemini_provider import GeminiProvider
from omnicovas.ai.null_provider import NullProvider
from omnicovas.ai.provider import AIProvider

logger = logging.getLogger(__name__)


def get_provider(
    provider_type: str,
    api_key: str | None = None,
    model: str | None = None,
) -> AIProvider:
    """
    Return a configured AIProvider based on the requested type.

    Args:
        provider_type: One of 'null', 'gemini'.
                       Future: 'openai', 'ollama'.
        api_key: API key for providers that need one (Gemini, OpenAI).
        model: Model name override for providers that support multiple.

    Returns:
        An AIProvider implementation. Falls back to NullProvider
        if configuration is missing or invalid.
    """
    provider_type_normalized = provider_type.lower().strip()

    if provider_type_normalized == "null":
        logger.info("Using NullProvider (AI disabled).")
        return NullProvider()

    if provider_type_normalized == "gemini":
        if not api_key:
            logger.warning(
                "Gemini requested but no API key provided. "
                "Falling back to NullProvider."
            )
            return NullProvider()
        if model:
            return GeminiProvider(api_key=api_key, model=model)
        return GeminiProvider(api_key=api_key)

    logger.warning(
        "Unknown AI provider type '%s'. Falling back to NullProvider.",
        provider_type,
    )
    return NullProvider()
