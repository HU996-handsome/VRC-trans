"""
Text post-processing: furigana, pinyin, formatting.
"""
import logging

logger = logging.getLogger(__name__)


class TextProcessor:
    """Post-processes translated text for VRChat display."""

    def __init__(self, enable_furigana: bool = False, enable_pinyin: bool = False,
                 max_length: int = 144, fancy_style: str = "none"):
        self.enable_furigana = enable_furigana
        self.enable_pinyin = enable_pinyin
        self.max_length = max_length
        self.fancy_style = fancy_style

    def process(self, text: str, language: str = "") -> str:
        if not text:
            return text

        # Apply furigana for Japanese
        if self.enable_furigana and language in ("ja", "auto"):
            text = self._add_furigana(text)

        # Apply pinyin for Chinese
        if self.enable_pinyin and language in ("zh", "auto"):
            text = self._add_pinyin(text)

        # Apply fancy text style
        if self.fancy_style != "none":
            text = self._apply_fancy(text, self.fancy_style)

        # Truncate to VRChat limit
        if len(text) > self.max_length:
            text = text[:self.max_length - 3] + "..."

        return text

    @staticmethod
    def _add_furigana(text: str) -> str:
        """Add hiragana readings to kanji (Japanese)."""
        try:
            from pykakasi import kakasi
            kks = kakasi()
            result = kks.convert(text)
            parts = []
            for item in result:
                orig = item["orig"]
                hira = item["hira"]
                if orig != hira and hira:
                    parts.append(f"{orig}({hira})")
                else:
                    parts.append(orig)
            return "".join(parts)
        except ImportError:
            return text

    @staticmethod
    def _add_pinyin(text: str) -> str:
        """Add toned pinyin to Chinese text."""
        try:
            from pypinyin import pinyin, Style
            import jieba
            words = jieba.cut(text)
            parts = []
            for word in words:
                if any('一' <= c <= '鿿' for c in word):
                    py = pinyin(word, style=Style.TONE)
                    reading = "".join([p[0] for p in py])
                    parts.append(f"{word}({reading})")
                else:
                    parts.append(word)
            return "".join(parts)
        except ImportError:
            return text

    @staticmethod
    def _apply_fancy(text: str, style: str) -> str:
        """Apply Unicode text transformations."""
        try:
            import fancify_text
            if style == "small_caps":
                return fancify_text.small_caps(text)
            elif style == "curly":
                return fancify_text.curly(text)
            elif style == "magic":
                return fancify_text.magic(text)
        except ImportError:
            pass
        return text

    @staticmethod
    def format_dual_language(original: str, translated: str, format: str = "both") -> str:
        """Format text for dual-language display."""
        if format == "translated_only":
            return translated
        elif format == "original_only":
            return original
        else:  # both
            return f"{translated}\n{original}"
