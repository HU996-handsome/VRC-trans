"""
Google Translate backend (free, no API key required).
Uses the unofficial Google Translate API via requests.
No dependency on broken googletrans library.
"""
import json
import logging
import re
from typing import Optional

from ..base import BaseTranslator, TranslationResult

logger = logging.getLogger(__name__)


class GoogleTranslator(BaseTranslator):
    def __init__(self, settings):
        super().__init__()
        self.name = "google"
        self._session = None

    def is_available(self) -> bool:
        try:
            import requests
            return True
        except ImportError:
            return False

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            # Bypass proxy for Google Translate (direct connection)
            self._session.trust_env = False
        return self._session

    @staticmethod
    def _map_lang(lang: str, is_source: bool = False) -> str:
        if is_source and lang == "auto":
            return "auto"
        mapping = {
            "zh": "zh-CN", "zh-cn": "zh-CN", "zh-tw": "zh-TW",
            "ja": "ja", "ko": "ko", "en": "en", "ru": "ru",
        }
        return mapping.get(lang.lower(), lang)

    def translate(self, text: str, source_lang: str = "auto",
                  target_lang: str = "en", context: Optional[list] = None) -> TranslationResult:
        try:
            session = self._get_session()
            src = self._map_lang(source_lang, is_source=True)
            dest = self._map_lang(target_lang)

            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                "client": "gtx",
                "sl": src,
                "tl": dest,
                "dt": "t",
                "q": text,
            }

            resp = session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            resp.encoding = 'utf-8'

            data = resp.json()
            # Response format: [[["translated","original",...], ...], ...]
            translated_parts = []
            if data and isinstance(data[0], list):
                for segment in data[0]:
                    if isinstance(segment, list) and segment[0]:
                        translated_parts.append(segment[0])

            translated = "".join(translated_parts).strip()
            if not translated:
                translated = text

            return TranslationResult(
                original=text,
                translated=translated,
                source_language=source_lang,
                target_language=target_lang,
                backend="google",
            )
        except Exception as e:
            logger.error(f"Google translation error: {e}")
            return TranslationResult(original=text, translated=text, backend="google")
