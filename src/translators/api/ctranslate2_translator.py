"""
CTranslate2 local translation backend (from VRCT).
Uses int8 quantized Transformer models for fast offline translation.
No internet connection required after model download.
"""
import logging
from pathlib import Path
from typing import Optional

from ..base import BaseTranslator, TranslationResult

logger = logging.getLogger(__name__)

WEIGHTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "weights" / "ctranslate2"

# Supported models: name -> huggingface repo
LOCAL_MODELS = {
    "m2m100_418M": {
        "repo": "jncraton/m2m100_418M-ct2-int8",
        "size": "~450MB",
        "speed": "fastest",
        "quality": "basic",
    },
    "m2m100_1.2B": {
        "repo": "jncraton/m2m100_1.2B-ct2-int8",
        "size": "~1.3GB",
        "speed": "fast",
        "quality": "good",
    },
    "nllb_1.3B": {
        "repo": "OpenNMT/nllb-200-distilled-1.3B-ct2-int8",
        "size": "~1.4GB",
        "speed": "fast",
        "quality": "very good",
    },
    "nllb_3.3B": {
        "repo": "OpenNMT/nllb-200-3.3B-ct2-int8",
        "size": "~3.5GB",
        "speed": "moderate",
        "quality": "excellent",
    },
}

# Language code mapping for NLLB models
NLLB_LANG_MAP = {
    "zh": "zho_Hans", "en": "eng_Latn", "ja": "jpn_Jpan",
    "ko": "kor_Hang", "ru": "rus_Cyrl", "fr": "fra_Latn",
    "de": "deu_Latn", "es": "spa_Latn", "pt": "por_Latn",
    "ar": "arb_Arab", "it": "ita_Latn", "th": "tha_Thai",
    "vi": "vie_Latn", "id": "ind_Latn",
}

# Language code mapping for M2M100 models
M2M100_LANG_MAP = {
    "zh": "zh", "en": "en", "ja": "ja", "ko": "ko",
    "ru": "ru", "fr": "fr", "de": "de", "es": "es",
    "pt": "pt", "ar": "ar", "it": "it", "th": "th",
    "vi": "vi", "id": "id",
}


class CTranslate2Translator(BaseTranslator):
    """Local CTranslate2 translation engine."""

    def __init__(self, settings):
        super().__init__()
        self.name = "ctranslate2"
        self.model_name = getattr(settings.translation, "ctranslate2_model", "nllb_1.3B")
        self._translator = None
        self._tokenizer = None
        self._model_type = None  # "nllb" or "m2m100"

    def is_available(self) -> bool:
        try:
            import ctranslate2
            import transformers
            return True
        except ImportError:
            return False

    def _load_model(self) -> bool:
        if self._translator:
            return True

        model_info = LOCAL_MODELS.get(self.model_name)
        if not model_info:
            logger.error(f"Unknown local model: {self.model_name}")
            return False

        repo = model_info["repo"]
        model_dir = WEIGHTS_DIR / self.model_name

        # Download if not exists
        if not model_dir.exists() or not (model_dir / "model.bin").exists():
            logger.info(f"Downloading local translation model: {repo}")
            try:
                from huggingface_hub import snapshot_download
                model_dir.mkdir(parents=True, exist_ok=True)
                snapshot_download(repo, local_dir=str(model_dir))
            except Exception as e:
                logger.error(f"Model download failed: {e}")
                return False

        try:
            import ctranslate2
            import transformers

            # Detect model type
            if "nllb" in self.model_name:
                self._model_type = "nllb"
                tokenizer_name = "facebook/nllb-200-distilled-1.3B"
            else:
                self._model_type = "m2m100"
                tokenizer_name = "facebook/m2m100_418M"

            self._translator = ctranslate2.Translator(
                str(model_dir),
                compute_type="int8",
            )
            self._tokenizer = transformers.AutoTokenizer.from_pretrained(
                tokenizer_name, cache_dir=str(WEIGHTS_DIR / ".cache")
            )

            logger.info(f"Local translation model loaded: {self.model_name} ({self._model_type})")
            return True
        except Exception as e:
            logger.error(f"Failed to load local model: {e}")
            return False

    def translate(self, text: str, source_lang: str = "auto",
                  target_lang: str = "en", context: Optional[list] = None) -> TranslationResult:
        if not self._load_model():
            return TranslationResult(original=text, translated=text, backend="ctranslate2")

        try:
            # Map language codes
            if self._model_type == "nllb":
                src = NLLB_LANG_MAP.get(source_lang, NLLB_LANG_MAP.get("en"))
                tgt = NLLB_LANG_MAP.get(target_lang, NLLB_LANG_MAP.get("en"))
                # Set source language in tokenizer
                self._tokenizer.src_lang = src
            else:
                src = M2M100_LANG_MAP.get(source_lang, "en")
                tgt = M2M100_LANG_MAP.get(target_lang, "en")
                self._tokenizer.src_lang = src

            # Tokenize
            inputs = self._tokenizer(text, return_tensors="np", padding=False)
            source_tokens = inputs["input_ids"][0].tolist()

            # Add target language prefix for NLLB
            if self._model_type == "nllb":
                target_prefix = [tgt]
            else:
                target_prefix = [self._tokenizer.convert_tokens_to_ids(tgt)]

            # Translate
            results = self._translator.translate_batch(
                [source_tokens],
                target_prefix=[target_prefix],
                beam_size=5,
                max_decoding_length=512,
            )

            # Decode
            target_tokens = results[0].hypotheses[0][len(target_prefix):]
            translated = self._tokenizer.decode(target_tokens, skip_special_tokens=True)

            return TranslationResult(
                original=text,
                translated=translated,
                source_language=source_lang,
                target_language=target_lang,
                backend="ctranslate2",
            )
        except Exception as e:
            logger.error(f"CTranslate2 translation error: {e}")
            return TranslationResult(original=text, translated=text, backend="ctranslate2")

    @staticmethod
    def list_models() -> dict:
        return {name: info for name, info in LOCAL_MODELS.items()}

    @staticmethod
    def check_model_status(model_name: str) -> dict:
        model_dir = WEIGHTS_DIR / model_name
        exists = model_dir.exists() and (model_dir / "model.bin").exists()
        return {
            "available": exists,
            "path": str(model_dir),
            "info": LOCAL_MODELS.get(model_name, {}),
        }

    @staticmethod
    def download_model(model_name: str, progress_callback=None) -> bool:
        model_info = LOCAL_MODELS.get(model_name)
        if not model_info:
            return False
        try:
            from huggingface_hub import snapshot_download
            model_dir = WEIGHTS_DIR / model_name
            model_dir.mkdir(parents=True, exist_ok=True)
            snapshot_download(model_info["repo"], local_dir=str(model_dir))
            logger.info(f"Model {model_name} downloaded")
            return True
        except Exception as e:
            logger.error(f"Model download failed: {e}")
            return False
