"""
Base translator interface and context-aware wrapper.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    original: str
    translated: str
    source_language: str = ""
    target_language: str = ""
    backend: str = ""

    def __str__(self):
        return self.translated


class BaseTranslator(ABC):
    """Abstract base class for translation backends."""

    def __init__(self):
        self.name = "base"

    @abstractmethod
    def translate(self, text: str, source_lang: str = "auto",
                  target_lang: str = "en", context: Optional[list] = None) -> TranslationResult:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...


class ContextAwareTranslator(BaseTranslator):
    """Wraps a translator with sliding-window conversation context."""

    def __init__(self, backend: BaseTranslator, history_size: int = 6):
        super().__init__()
        self.name = backend.name
        self._backend = backend
        self._history: deque = deque(maxlen=history_size)

    def translate(self, text: str, source_lang: str = "auto",
                  target_lang: str = "en", context: Optional[list] = None) -> TranslationResult:
        # Build context from history
        ctx = context or []
        for entry in self._history:
            ctx.append({
                "source": entry["source"],
                "target": entry["target"],
                "source_lang": entry.get("source_lang", ""),
                "target_lang": entry.get("target_lang", ""),
            })

        result = self._backend.translate(text, source_lang, target_lang, ctx)

        # Add to history
        self._history.append({
            "source": text,
            "target": result.translated,
            "source_lang": result.source_language,
            "target_lang": result.target_language,
        })

        return result

    def is_available(self) -> bool:
        return self._backend.is_available()

    def clear_history(self):
        self._history.clear()


# Keywords that indicate a transient/retryable error (quota, rate limit, network)
_TRANSIENT_ERROR_KEYWORDS = [
    "quota", "rate limit", "billing", "balance", "insufficient",
    "too many requests", "429", "503", "timeout", "connection",
    "network", "temporarily", "overloaded",
]


def _is_transient_error(error_msg: str) -> bool:
    """Check if an error is transient (worth retrying with fallback)."""
    lower = error_msg.lower()
    return any(kw in lower for kw in _TRANSIENT_ERROR_KEYWORDS)


class FallbackTranslator(BaseTranslator):
    """Wraps a primary translator with automatic fallback on failure.

    When the primary translator fails (returns original text or raises),
    automatically retries with the fallback translator. On transient errors
    (quota, rate limit, network), switches to fallback for subsequent calls
    until the primary recovers.
    """

    def __init__(self, primary: BaseTranslator, fallback: BaseTranslator,
                 recovery_interval: float = 300.0):
        super().__init__()
        self.name = primary.name
        self._primary = primary
        self._fallback = fallback
        self._recovery_interval = recovery_interval  # seconds before retrying primary

        self._using_fallback = False
        self._fallback_since = 0.0
        self._fail_count = 0

    def translate(self, text: str, source_lang: str = "auto",
                  target_lang: str = "en", context: Optional[list] = None) -> TranslationResult:
        import time

        # If currently on fallback, check if it's time to retry primary
        if self._using_fallback:
            if (time.time() - self._fallback_since) >= self._recovery_interval:
                logger.info("Attempting to recover primary translator...")
                self._using_fallback = False
                self._fail_count = 0
            else:
                # Still on fallback
                try:
                    return self._fallback.translate(text, source_lang, target_lang, context)
                except Exception as e:
                    logger.error(f"Fallback translator also failed: {e}")
                    return TranslationResult(original=text, translated=text, backend=self._fallback.name)

        # Try primary
        try:
            result = self._primary.translate(text, source_lang, target_lang, context)
            # Check if result looks like a failure (returned original text unchanged)
            if result.translated == text and result.backend != "google":
                # Could be same-language or actual failure
                pass
            self._fail_count = 0
            return result
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Primary translator error: {error_msg}")
            self._fail_count += 1

            # On transient errors or repeated failures, switch to fallback
            if _is_transient_error(error_msg) or self._fail_count >= 2:
                logger.warning(f"Switching to fallback translator ({self._fallback.name})")
                self._using_fallback = True
                self._fallback_since = time.time()
                try:
                    return self._fallback.translate(text, source_lang, target_lang, context)
                except Exception as e2:
                    logger.error(f"Fallback translator also failed: {e2}")
                    return TranslationResult(original=text, translated=text, backend=self._fallback.name)

            # Non-transient single failure: return original text
            return TranslationResult(original=text, translated=text, backend=self._primary.name)

    def is_available(self) -> bool:
        return self._primary.is_available() or self._fallback.is_available()

    @property
    def active_backend(self) -> str:
        return self._fallback.name if self._using_fallback else self._primary.name
