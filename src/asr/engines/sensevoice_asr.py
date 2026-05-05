"""
SenseVoice Small local ASR engine.
Uses Alibaba's SenseVoice Small model with ONNX Runtime for local inference.
No internet connection required after model download.
"""
import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from ..base import BaseASR, ASRResult, ASRFactory

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "models"
MODEL_REPO = "iic/SenseVoiceSmall"
ONNX_MODEL_NAME = "model_quant_int8.onnx"


class SenseVoiceASR(BaseASR):
    """Local SenseVoice Small ASR using ONNX Runtime."""

    def __init__(self, settings, hot_words: Optional[list[str]] = None):
        super().__init__()
        self.language = settings.asr.language_hint if settings.asr.language_hint != "auto" else ""
        self.hot_words = hot_words or []

        self._session = None
        self._running = False
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._audio_queue: list[np.ndarray] = []

        # VAD
        self._vad = None
        self._speech_buffer: list[np.ndarray] = []
        self._is_speaking = False
        self._silence_frames = 0

        # Model info
        self._model_dir = MODELS_DIR / "sensevoice"
        self._onnx_path = self._model_dir / ONNX_MODEL_NAME

    def start(self):
        if self._running:
            return
        if not self._load_model():
            return
        self._running = True
        self._init_vad()

    def stop(self):
        self._running = False

    def feed_audio(self, audio: np.ndarray):
        if not self._running:
            return

        # Process through VAD
        if self._vad:
            is_speech = self._vad.is_speech(audio)
            if is_speech:
                if not self._is_speaking:
                    self._is_speaking = True
                    self._silence_frames = 0
                self._speech_buffer.append(audio)
                self._silence_frames = 0
            else:
                if self._is_speaking:
                    self._silence_frames += 1
                    self._speech_buffer.append(audio)
                    if self._silence_frames >= 4:
                        self._transcribe_buffer()
                # Pre-speech buffer discarded for local (no streaming)
        else:
            # No VAD, accumulate and transcribe periodically
            self._speech_buffer.append(audio)
            total_len = sum(len(a) for a in self._speech_buffer)
            if total_len >= 16000 * 2:  # 2 seconds
                self._transcribe_buffer()

    def flush(self):
        if self._is_speaking and self._speech_buffer:
            self._transcribe_buffer()

    def _load_model(self) -> bool:
        if not self._onnx_path.exists():
            logger.warning(f"SenseVoice model not found at {self._onnx_path}")
            logger.info("Download the model from ModelScope: modelscope download --model iic/SenseVoiceSmall")
            return False

        try:
            import onnxruntime as ort
            providers = ["CPUExecutionProvider"]
            # Try CUDA/DirectML
            for p in ["CUDAExecutionProvider", "DmlExecutionProvider"]:
                if p in ort.get_available_providers():
                    providers.insert(0, p)

            self._session = ort.InferenceSession(str(self._onnx_path), providers=providers)
            logger.info(f"SenseVoice model loaded ({providers[0]})")
            return True
        except Exception as e:
            logger.error(f"Failed to load SenseVoice model: {e}")
            return False

    def _init_vad(self):
        from pathlib import Path
        model_path = Path(__file__).parent.parent / "models" / "silero_vad.jit"
        if not model_path.exists():
            model_path = MODELS_DIR / "silero_vad.jit"
        if model_path.exists():
            try:
                import onnxruntime as ort
                self._vad = _SenseVoiceSileroVAD(model_path)
                logger.info("SenseVoice VAD initialized")
            except Exception as e:
                logger.warning(f"VAD init failed: {e}")

    def _transcribe_buffer(self):
        if not self._speech_buffer:
            return

        audio = np.concatenate(self._speech_buffer)
        self._speech_buffer.clear()
        self._is_speaking = False
        self._silence_frames = 0

        if len(audio) < 1600:  # < 0.1s
            return

        # Run inference
        try:
            result = self._infer(audio)
            if result and result.strip():
                self._emit(ASRResult(
                    text=result.strip(),
                    is_final=True,
                    language=self.language or "auto",
                ))
        except Exception as e:
            logger.error(f"SenseVoice inference error: {e}")

    def _infer(self, audio: np.ndarray) -> str:
        """Run SenseVoice inference on audio segment."""
        if not self._session:
            return ""

        import onnxruntime as ort

        # Prepare input
        # SenseVoice expects: (1, audio_len) float32, and length
        audio_input = audio.astype(np.float32).reshape(1, -1)
        length = np.array([len(audio)], dtype=np.int64)
        language = np.array([self._get_lang_id()], dtype=np.int64)
        textnorm = np.array([2], dtype=np.int64)  # 2=auto normalization

        inputs = {
            "speech": audio_input,
            "speech_lengths": length,
            "language": language,
            "textnorm": textnorm,
        }

        outputs = self._session.run(None, inputs)

        # Decode output
        if outputs and len(outputs) > 0:
            token_ids = outputs[0]
            if isinstance(token_ids, np.ndarray):
                if token_ids.ndim > 1:
                    token_ids = token_ids[0]
                return self._decode_tokens(token_ids)
        return ""

    def _get_lang_id(self) -> int:
        """Map language hint to SenseVoice language ID."""
        lang_map = {"auto": 0, "zh": 0, "en": 1, "ja": 2, "ko": 3, "yue": 4}
        return lang_map.get(self.language, 0)

    def _decode_tokens(self, token_ids: np.ndarray) -> str:
        """Decode token IDs to text using the SenseVoice tokenizer."""
        # Try using the actual tokenizer
        tokenizer_path = self._model_dir / "tokenizer.json"
        if tokenizer_path.exists():
            try:
                import json
                with open(tokenizer_path, "r", encoding="utf-8") as f:
                    tokenizer_data = json.load(f)
                vocab = tokenizer_data.get("model", {}).get("vocab", {})
                id_to_token = {v: k for k, v in vocab.items()}
                text = ""
                for tid in token_ids:
                    token = id_to_token.get(int(tid), "")
                    if token and token not in ("<s>", "</s>", "<blank>", "<pad>"):
                        text += token
                return text.replace("▁", " ").strip()
            except Exception:
                pass

        # Fallback: try sentencepiece
        sp_path = self._model_dir / "tokenizer.model"
        if sp_path.exists():
            try:
                import sentencepiece as spm
                sp = spm.SentencePieceProcessor()
                sp.load(str(sp_path))
                return sp.decode_ids([int(t) for t in token_ids if int(t) < sp.get_piece_size()])
            except Exception:
                pass

        logger.warning("No tokenizer found for SenseVoice")
        return ""

    @staticmethod
    def check_model_status() -> dict:
        """Check if the SenseVoice model is available."""
        onnx_path = MODELS_DIR / "sensevoice" / ONNX_MODEL_NAME
        return {
            "available": onnx_path.exists(),
            "path": str(onnx_path),
            "size_mb": onnx_path.stat().st_size / (1024*1024) if onnx_path.exists() else 0,
        }

    @staticmethod
    def download_model(progress_callback=None):
        """Download SenseVoice model from ModelScope."""
        try:
            from modelscope import snapshot_download
            download_dir = MODELS_DIR / "sensevoice"
            download_dir.mkdir(parents=True, exist_ok=True)
            snapshot_download(MODEL_REPO, local_dir=str(download_dir))
            logger.info("SenseVoice model downloaded")
            return True
        except Exception as e:
            logger.error(f"Model download failed: {e}")
            return False


class _SenseVoiceSileroVAD:
    def __init__(self, model_path):
        import onnxruntime as ort
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def is_speech(self, audio: np.ndarray) -> bool:
        if len(audio) < 512:
            audio = np.pad(audio, (0, 512 - len(audio)))
        audio_input = audio[:512].astype(np.float32).reshape(1, -1)
        sr = np.array([16000], dtype=np.int64)
        try:
            out, self._state = self.session.run(None, {
                "input": audio_input, "state": self._state, "sr": sr
            })
            return float(out[0][0]) > 0.5
        except Exception:
            return False


# Register
ASRFactory.register("local_sensevoice", lambda s, hw: SenseVoiceASR(s, hw))
