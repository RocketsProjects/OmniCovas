"""
omnicovas.ai.gemini_provider

Gemini AI provider — the default cloud AI for OmniCOVAS.

Uses Google's modern google-genai SDK (the legacy google-generativeai
package was deprecated April 2026).

Law 3 (API Respect Protocol):
    Rate limit enforcement is local, not reliant on the remote.
    Response caching reduces API load.

Law 5 (Zero Hallucination Doctrine):
    The prompt is ALREADY grounded in Knowledge Base entries before
    it reaches this provider. This class does not add knowledge —
    it only forwards the grounded prompt to the model.

Law 6 (Performance Priority):
    Failures return None; they never raise. The dispatcher never blocks.

See: Master Blueprint v4.0 Section 5 (AI Modes)
See: Phase 1 Development Guide Week 4, Part A
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any

from omnicovas.ai.provider import AIProvider

logger = logging.getLogger(__name__)

# Gemini Free Tier rate limits (verify at aistudio.google.com before release)
GEMINI_FREE_RPM = 15  # requests per minute
GEMINI_FREE_RPD = 1500  # requests per day
GEMINI_MODEL_DEFAULT = "gemini-2.0-flash"

# Response cache config
CACHE_MAX_ENTRIES = 256
CACHE_TTL_SECONDS = 3600  # 1 hour


class GeminiProvider(AIProvider):
    """
    AI provider that calls Google's Gemini API via the google-genai SDK.

    Args:
        api_key: Gemini API key (from config vault, never from code)
        model: Model name (default: gemini-2.0-flash, free tier friendly)

    Behavior:
        - Enforces rate limits locally (defensive, don't trust remote)
        - Caches responses for 1h (same prompt hash returns cached reply)
        - Returns None on any error — never raises
    """

    def __init__(
        self,
        api_key: str,
        model: str = GEMINI_MODEL_DEFAULT,
    ) -> None:
        self._api_key = api_key
        self._model_name = model
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._recent_request_times: list[float] = []
        self._client: Any | None = None
        self._initialization_failed = False

    def _lazy_init_client(self) -> bool:
        """
        Configure the Gemini client on first use.

        Returns:
            True if configuration succeeded, False otherwise.
        """
        if self._client is not None:
            return True
        if self._initialization_failed:
            return False

        try:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
            logger.info(
                "Gemini provider initialized with model '%s'.", self._model_name
            )
            return True
        except Exception as e:
            logger.error("Gemini initialization failed: %s", e)
            self._initialization_failed = True
            return False

    def _rate_limit_allows_request(self) -> bool:
        """
        Check whether we may make a request without exceeding the free-tier RPM.

        Returns:
            True if a request is allowed, False if we would exceed the limit.
        """
        now = time.monotonic()
        cutoff = now - 60.0
        self._recent_request_times = [
            t for t in self._recent_request_times if t > cutoff
        ]

        if len(self._recent_request_times) >= GEMINI_FREE_RPM:
            oldest = self._recent_request_times[0]
            wait = 60.0 - (now - oldest)
            logger.warning(
                "Gemini rate limit: %d/%d RPM reached, would need to wait %.1fs",
                len(self._recent_request_times),
                GEMINI_FREE_RPM,
                wait,
            )
            return False
        return True

    def _record_request(self) -> None:
        """Record that a request was issued, for rate limit bookkeeping."""
        self._recent_request_times.append(time.monotonic())

    def _cache_key(self, prompt: str) -> str:
        """Hash the prompt to produce a short, collision-resistant cache key."""
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> str | None:
        """Return cached response if present and not expired."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return value

    def _cache_put(self, key: str, value: str) -> None:
        """Store a response in the LRU cache."""
        self._cache[key] = (time.monotonic(), value)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)

    async def query(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Send the grounded prompt to Gemini and return the response.

        Args:
            prompt: Full KB-grounded prompt (Law 5)
            context: Optional additional context (unused by Gemini directly —
                     grounding happens at the KB layer before reaching here)

        Returns:
            Gemini's response text, or None on any failure.
        """
        # Check cache first
        cache_key = self._cache_key(prompt)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug("Gemini cache hit (key=%s...)", cache_key[:8])
            return cached

        # Rate limit check
        if not self._rate_limit_allows_request():
            return None

        # Lazy init
        if not self._lazy_init_client():
            return None

        # Actual API call
        try:
            self._record_request()
            assert self._client is not None
            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents=prompt,
            )
            text = getattr(response, "text", None)
            if not isinstance(text, str) or not text:
                logger.warning("Gemini returned empty response.")
                return None

            self._cache_put(cache_key, text)
            return text
        except Exception as e:
            logger.error("Gemini query failed: %s", e)
            return None

    async def is_available(self) -> bool:
        """
        Check that the provider is initialized and not rate-limited.
        """
        if self._initialization_failed:
            return False
        if not self._lazy_init_client():
            return False
        return self._rate_limit_allows_request()

    def name(self) -> str:
        return f"Gemini ({self._model_name})"
