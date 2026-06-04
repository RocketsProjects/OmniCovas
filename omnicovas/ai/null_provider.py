"""
omnicovas.ai.null_provider

The NullProvider — "no AI" mode.

Law 4 (AI Provider Agnosticism):
    This is a first-class provider, not a fallback.
    Commanders who choose "No AI" get full OmniCOVAS functionality:
    all telemetry, all intelligence, all alerts. Just no LLM-generated text.

Behavior:
    query() always returns None immediately.
    Every downstream caller must handle None gracefully (mypy enforces it).
    This forces the entire codebase to never assume AI is available.

See: Master Blueprint v4.0 Section 5 (Three AI Integration Tiers)
See: Phase 1 Development Guide Week 4, Part A
"""

from __future__ import annotations

import logging
from typing import Any

from omnicovas.ai.provider import AIProvider

logger = logging.getLogger(__name__)


class NullProvider(AIProvider):
    """
    Provider implementation for "No AI" mode.

    Returns None from every query. Always available. Zero cost.

    This is the default during development and a legitimate user choice
    in production. The system must work completely without AI.
    """

    async def query(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Return None — there is no AI to answer.

        Callers must branch on None and provide a deterministic,
        KB-grounded fallback (Tier 1 or Tier 2 from the Blueprint).
        """
        logger.debug("NullProvider.query called; returning None as designed.")
        return None

    async def is_available(self) -> bool:
        """
        NullProvider is always available. It is the zero-dependency mode.
        """
        return True

    def name(self) -> str:
        return "NullProvider"
