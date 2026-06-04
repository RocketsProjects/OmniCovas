"""
omnicovas.ai.provider

Abstract base class for AI providers.

Law 4 (AI Provider Agnosticism):
    Core brain NEVER calls AI providers directly.
    Every provider implements this interface.
    Swapping providers is a single config change, never a code change.

Law 5 (Zero Hallucination Doctrine):
    Every AI call goes through a provider that grounds responses in
    the Knowledge Base. Free-form knowledge is forbidden.

Return Contract:
    query() returns str | None.
    None is a valid, expected return value when:
        - NullProvider is active (no AI mode)
        - Provider failed to respond
        - Response was filtered as ungrounded

    Every call site MUST handle None. mypy strict enforces this.

See: Master Blueprint v4.0 Section 5 (AI Abstraction Layer)
See: Phase 1 Development Guide Week 4, Part A
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    """
    Abstract base class for all AI providers.

    Implementations: NullProvider, GeminiProvider, OpenAIProvider,
                     OllamaProvider (Phase 2+)

    Every provider must fulfill three methods:
        - query(prompt, context) -> str | None
        - is_available() -> bool
        - name() -> str
    """

    @abstractmethod
    async def query(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Send a prompt to the AI and return the response.

        Args:
            prompt: The user-facing prompt (already KB-grounded)
            context: Optional additional context (system state, etc.)

        Returns:
            The AI's response as a string, or None if:
                - Provider is NullProvider (AI disabled)
                - API call failed
                - Response was filtered as ungrounded

        Must never raise on typical failures. Log and return None instead.
        Law 6: dispatcher must never be blocked by provider failures.
        """
        raise NotImplementedError

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Check whether this provider is currently usable.

        Returns:
            True if the provider can accept queries right now,
            False if it's misconfigured, rate-limited, or unreachable.
        """
        raise NotImplementedError

    @abstractmethod
    def name(self) -> str:
        """
        Human-readable provider name for logging and UI display.

        Returns:
            Short name like 'Gemini', 'OpenAI', 'Ollama', 'NullProvider'.
        """
        raise NotImplementedError
