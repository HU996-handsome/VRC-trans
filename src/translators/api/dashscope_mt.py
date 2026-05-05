"""
DashScope Qwen-MT translation backend.
Replicates Yakutan's QwenMTAPI exactly.
"""
import logging
from typing import Optional

from ..base import BaseTranslator, TranslationResult

logger = logging.getLogger(__name__)

# Exactly from Yakutan's QwenMTAPI.DOMAINS
VRCHAT_DOMAIN = (
    "The text is casual conversation from VRChat, "
    "a social virtual reality platform. "
    "Keep translations natural, friendly and colloquial."
)

# Exactly from Yakutan's QwenMTAPI.LANGUAGE_MAP
LANGUAGE_MAP = {
    "zh-cn": "zh", "zh-hans": "zh", "zh-hant": "zh-tw",
    "en-us": "en", "en-gb": "en", "en-au": "en",
    "pt-br": "pt", "pt-pt": "pt",
}


def _get_language_code(lang_code: str) -> str:
    """Map language codes to Qwen-MT format (from Yakutan)."""
    code = (lang_code or "auto").lower().strip()
    if not code or code == "auto":
        return "auto"
    return LANGUAGE_MAP.get(code, code)


class DashScopeTranslator(BaseTranslator):
    def __init__(self, settings):
        super().__init__()
        self.name = "dashscope"
        self.api_key = settings.translation.dashscope_api_key or settings.asr.dashscope_api_key
        self.model = settings.translation.qwen_mt_model
        self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx
            from openai import OpenAI
            # Bypass system proxy for DashScope API
            http_client = httpx.Client(proxy=None, trust_env=False)
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                http_client=http_client,
            )
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key)

    def translate(self, text: str, source_lang: str = "auto",
                  target_lang: str = "en", context: Optional[list] = None) -> TranslationResult:
        import time as _time
        t0 = _time.monotonic()
        try:
            client = self._get_client()

            # Exactly from Yakutan's QwenMTAPI.translate()
            translation_options = {
                "source_lang": _get_language_code(source_lang),
                "target_lang": _get_language_code(target_lang),
            }

            # Domain hint (from Yakutan)
            if VRCHAT_DOMAIN:
                translation_options["domains"] = VRCHAT_DOMAIN

            # Context pairs as tm_list (from Yakutan) - only if provided
            if context:
                tm_list = [
                    {"source": p["source"], "target": p["target"]}
                    for p in context
                    if str(p.get("source") or "").strip()
                    and str(p.get("target") or "").strip()
                ]
                if tm_list:
                    translation_options["tm_list"] = tm_list

            # Single user message, no system role (from Yakutan)
            messages = [{"role": "user", "content": text}]

            # No temperature, no max_tokens (matching Yakutan exactly)
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                extra_body={"translation_options": translation_options},
            )

            translated = response.choices[0].message.content
            elapsed = _time.monotonic() - t0
            logger.info(f"DashScope API: {elapsed:.2f}s ({self.model})")
            return TranslationResult(
                original=text,
                translated=(translated.strip() if translated else ""),
                source_language=source_lang,
                target_language=target_lang,
                backend="dashscope",
            )
        except Exception as e:
            elapsed = _time.monotonic() - t0
            logger.error(f"DashScope translation error after {elapsed:.2f}s: {e}")
            return TranslationResult(original=text, translated=text, backend="dashscope")
