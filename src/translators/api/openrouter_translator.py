"""
OpenRouter / OpenAI-compatible LLM translation backend.
"""
import logging
from typing import Optional

from ..base import BaseTranslator, TranslationResult

logger = logging.getLogger(__name__)


class OpenRouterTranslator(BaseTranslator):
    def __init__(self, settings):
        super().__init__()
        self.name = "openrouter"
        self.api_key = settings.translation.openrouter_api_key
        self.base_url = settings.translation.openrouter_base_url
        self.model = settings.translation.openrouter_model
        self.temperature = settings.translation.openrouter_temperature
        self.timeout = settings.translation.openrouter_timeout

    def is_available(self) -> bool:
        return bool(self.api_key)

    def translate(self, text: str, source_lang: str = "auto",
                  target_lang: str = "en", context: Optional[list] = None) -> TranslationResult:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

            system = (
                f"You are a professional translator for VRChat. "
                f"Translate the following text to {target_lang}. "
                f"Keep the translation natural and conversational. "
                f"Only output the translation, nothing else."
            )

            if context:
                ctx_text = "\n".join([f"{c['source']} -> {c['target']}" for c in context[-4:]])
                system += f"\n\nRecent translations for consistency:\n{ctx_text}"

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ]

            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=1024,
            )

            translated = response.choices[0].message.content.strip()
            return TranslationResult(
                original=text,
                translated=translated,
                source_language=source_lang,
                target_language=target_lang,
                backend="openrouter",
            )
        except Exception as e:
            logger.error(f"OpenRouter translation error: {e}")
            return TranslationResult(original=text, translated=text, backend="openrouter")
