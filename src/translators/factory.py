"""
Translation backend factory.
"""
import logging
from typing import Optional

from .base import BaseTranslator, ContextAwareTranslator, FallbackTranslator
from .api.dashscope_mt import DashScopeTranslator
from .api.deepl_translator import DeepLTranslator
from .api.openrouter_translator import OpenRouterTranslator
from .api.google_translator import GoogleTranslator
from .api.ctranslate2_translator import CTranslate2Translator

logger = logging.getLogger(__name__)


class TranslatorFactory:
    """Creates translation backends by name."""

    _backends = {
        "dashscope": DashScopeTranslator,
        "deepl": DeepLTranslator,
        "openrouter": OpenRouterTranslator,
        "google": GoogleTranslator,
        "ctranslate2": CTranslate2Translator,
    }

    @classmethod
    def create(cls, name: str, settings, use_context: bool = False) -> BaseTranslator:
        """Create a translator backend with automatic fallback.

        For paid backends (dashscope, deepl, openrouter), wraps with Google
        as fallback. When the primary fails (quota, rate limit, network),
        automatically switches to Google, then retries primary after 5 minutes.
        """
        if name not in cls._backends:
            logger.warning(f"Unknown translator '{name}', falling back to google")
            name = "google"

        backend = cls._backends[name](settings)
        if not backend.is_available():
            logger.warning(f"Translator '{name}' not available, trying fallbacks")
            for fallback_name in ["dashscope", "google"]:
                if fallback_name != name:
                    fb = cls._backends[fallback_name](settings)
                    if fb.is_available():
                        backend = fb
                        name = fallback_name
                        break

        # For paid backends, wrap with Google fallback
        if name != "google" and name != "ctranslate2":
            google_backend = cls._backends["google"](settings)
            if google_backend.is_available():
                logger.info(f"Wrapping {name} with Google fallback (auto-switch on failure)")
                backend = FallbackTranslator(
                    primary=backend,
                    fallback=google_backend,
                    recovery_interval=300.0,  # retry primary after 5 min
                )

        # DashScope has native context via translation_options,
        # skip ContextAwareTranslator wrapper for speed
        if use_context and name != "dashscope":
            return ContextAwareTranslator(backend)
        return backend

    @classmethod
    def available_backends(cls) -> dict[str, str]:
        return {
            "dashscope": "阿里云 DashScope Qwen-MT (推荐, 需要API Key)",
            "deepl": "DeepL (可选, 需要API Key)",
            "openrouter": "OpenRouter (可选, LLM翻译, 需要API Key)",
            "google": "Google Translate (免费, 无需Key)",
            "ctranslate2": "CTranslate2 (本地离线, 无需网络)",
        }
