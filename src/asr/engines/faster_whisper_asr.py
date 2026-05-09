"""
faster-whisper local ASR engine (from VRCT).
Uses CTranslate2-based Whisper for fast local speech recognition.
No internet connection required after model download.
"""
import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from ..base import BaseASR, ASRResult, ASRFactory

logger = logging.getLogger(__name__)

WEIGHTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "weights" / "whisper"

WHISPER_MODELS = {
    "tiny": {"repo": "Systran/faster-whisper-tiny", "size": "~75MB", "speed": "fastest"},
    "base": {"repo": "Systran/faster-whisper-base", "size": "~142MB", "speed": "very fast"},
    "small": {"repo": "Systran/faster-whisper-small", "size": "~466MB", "speed": "fast"},
    "medium": {"repo": "Systran/faster-whisper-medium", "size": "~1.5GB", "speed": "moderate"},
    "large-v3-turbo-int8": {"repo": "Zoont/faster-whisper-large-v3-turbo-int8-ct2", "size": "~794MB", "speed": "fast"},
    "large-v3-turbo": {"repo": "deepdml/faster-whisper-large-v3-turbo-ct2", "size": "~1.58GB", "speed": "moderate"},
}


class FasterWhisperASR(BaseASR):
    """Local faster-whisper ASR engine."""

    def __init__(self, settings, hot_words: Optional[list[str]] = None):
        super().__init__()
        self.model_name = getattr(settings.asr, "whisper_model", "small")
        self.language = settings.asr.language_hint if settings.asr.language_hint != "auto" else None
        self.hot_words = hot_words or []

        self._model = None
        self._running = False
        self._lock = threading.Lock()

        # Speech buffer
        self._speech_buffer: list[np.ndarray] = []
        self._is_speaking = False
        self._silence_frames = 0
        self._silence_threshold = 4

        # VAD
        self._vad = None

    def start(self):
        if self._running:
            return
        if not self._load_model():
            return
        self._running = True
        self._init_vad()
        logger.info(f"FasterWhisper ASR started (model={self.model_name})")

    def stop(self):
        self._running = False

    def feed_audio(self, audio: np.ndarray):
        if not self._running:
            return

        # VAD processing
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
                    if self._silence_frames >= self._silence_threshold:
                        self._transcribe_buffer()
        else:
            self._speech_buffer.append(audio)
            total_len = sum(len(a) for a in self._speech_buffer)
            if total_len >= 16000 * 3:
                self._transcribe_buffer()

    def flush(self):
        if self._is_speaking and self._speech_buffer:
            self._transcribe_buffer()

    def _load_model(self) -> bool:
        if self._model:
            return True

        model_info = WHISPER_MODELS.get(self.model_name)
        if not model_info:
            logger.error(f"Unknown whisper model: {self.model_name}")
            return False

        model_dir = WEIGHTS_DIR / self.model_name
        repo = model_info["repo"]

        # Download if needed
        if not model_dir.exists() or not (model_dir / "model.bin").exists():
            logger.info(f"Downloading whisper model: {repo}")
            try:
                from huggingface_hub import snapshot_download
                model_dir.mkdir(parents=True, exist_ok=True)
                snapshot_download(repo, local_dir=str(model_dir))
            except Exception as e:
                logger.error(f"Model download failed: {e}")
                return False

        try:
            from faster_whisper import WhisperModel

            # Detect compute type
            compute_type = "int8"
            try:
                import torch
                if torch.cuda.is_available():
                    gpu_name = torch.cuda.get_device_name(0).lower()
                    if "rtx" in gpu_name or "tesla" in gpu_name or "a100" in gpu_name:
                        compute_type = "int8_float16"
                    else:
                        compute_type = "float32"
            except ImportError:
                pass

            self._model = WhisperModel(
                str(model_dir),
                device="auto",
                compute_type=compute_type,
            )
            logger.info(f"FasterWhisper model loaded: {self.model_name} (compute={compute_type})")
            return True
        except Exception as e:
            logger.error(f"Failed to load whisper model: {e}")
            return False

    def _init_vad(self):
        from pathlib import Path
        model_path = Path(__file__).parent.parent / "models" / "silero_vad.jit"
        if not model_path.exists():
            model_path = WEIGHTS_DIR.parent / "silero_vad.jit"
        if model_path.exists():
            try:
                import onnxruntime as ort
                self._vad = _WhisperSileroVAD(model_path)
                logger.info("Whisper VAD initialized")
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

        try:
            segments, info = self._model.transcribe(
                audio,
                beam_size=5,
                language=self.language,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=200,
                ),
            )

            text_parts = []
            for segment in segments:
                if segment.no_speech_prob < 0.6 and segment.avg_log_prob > -0.8:
                    text_parts.append(segment.text.strip())

            text = " ".join(text_parts).strip()
            if text:
                self._emit(ASRResult(
                    text=text,
                    is_final=True,
                    language=str(info.language) if info.language else "",
                    confidence=info.language_probability,
                ))
        except Exception as e:
            logger.error(f"FasterWhisper transcription error: {e}")

    @staticmethod
    def list_models() -> dict:
        return WHISPER_MODELS

    @staticmethod
    def check_model_status(model_name: str) -> dict:
        model_dir = WEIGHTS_DIR / model_name
        exists = model_dir.exists() and (model_dir / "model.bin").exists()
        return {
            "available": exists,
            "path": str(model_dir),
            "info": WHISPER_MODELS.get(model_name, {}),
        }

    @staticmethod
    def download_model(model_name: str) -> bool:
        model_info = WHISPER_MODELS.get(model_name)
        if not model_info:
            return False
        try:
            from huggingface_hub import snapshot_download
            model_dir = WEIGHTS_DIR / model_name
            model_dir.mkdir(parents=True, exist_ok=True)
            snapshot_download(model_info["repo"], local_dir=str(model_dir))
            return True
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False


class _WhisperSileroVAD:
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
ASRFactory.register("faster_whisper", lambda s, hw: FasterWhisperASR(s, hw))
