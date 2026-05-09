"""
DeepL translation backend.
"""
import logging
from typing import Optional

from ..base import BaseTranslator, TranslationResult

logger = logging.getLogger(__name__)


class DeepLTranslator(BaseTranslator):
    def __init__(self, settings):
        super().__init__()
        self.name = "deepl"
        self.api_key = settings.translation.deepl_api_key
        self.formality = settings.translation.deepl_formality

    def is_available(self) -> bool:
        return bool(self.api_key)

    def translate(self, text: str, source_lang: str = "auto",
                  target_lang: str = "EN", context: Optional[list] = None) -> TranslationResult:
        try:
            import deepl
            translator = deepl.Translator(self.api_key)

            target = target_lang.upper()
            if target == "ZH":
                target = "ZH-HANS"

            result = translator.translate_text(
                text,
                source_lang=source_lang if source_lang != "auto" else None,
                target_lang=target,
                formality=self.formality if self.formality != "default" else None,
            )

            return TranslationResult(
                original=text,
                translated=str(result),
                source_language=source_lang,
                target_language=target_lang,
                backend="deepl",
            )
        except Exception as e:
            logger.error(f"DeepL translation error: {e}")
            return TranslationResult(original=text, translated=text, backend="deepl")
