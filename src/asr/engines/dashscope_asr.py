"""
DashScope ASR backend (cloud).
Uses Alibaba's DashScope SDK for streaming speech recognition.
"""
import logging
import threading
from typing import Optional

import numpy as np

from ..base import BaseASR, ASRResult, ASRFactory

logger = logging.getLogger(__name__)


class _Callback:
    """Adapter from DashScope RecognitionCallback to our ASR callback."""

    def __init__(self, asr_instance: "DashScopeASR"):
        self._asr = asr_instance

    def on_open(self) -> None:
        self._asr._connected = True

    def on_close(self) -> None:
        self._asr._connected = False

    def on_error(self, result) -> None:
        logger.error(f"DashScope ASR error: {result.code} {result.message}")

    def on_complete(self) -> None:
        pass

    def on_event(self, result) -> None:
        raw = result.get_sentence()
        if not raw:
            return
        # get_sentence() can return a single dict or a list of dicts
        sentences = [raw] if isinstance(raw, dict) else raw

        for sentence in sentences:
            if not isinstance(sentence, dict):
                continue
            text = sentence.get("text", "") or sentence.get("value", "")
            if not text.strip():
                continue
            is_final = result.is_sentence_end(sentence)
            lang = self._asr.language_hint or "auto"
            self._asr._emit(ASRResult(
                text=text.strip(),
                is_final=is_final,
                language=lang,
            ))


class DashScopeASR(BaseASR):
    """DashScope realtime ASR using the official SDK."""

    def __init__(self, settings, hot_words: Optional[list[str]] = None):
        super().__init__()
        self.api_key = settings.asr.dashscope_api_key
        self.model = settings.asr.dashscope_model
        self.language_hint = settings.asr.language_hint if settings.asr.language_hint != "auto" else ""
        self.hot_words = hot_words or []

        self._recognition = None
        self._running = False
        self._connected = False
        self._lock = threading.Lock()

    def _create_recognition(self):
        """Create a new DashScope Recognition instance."""
        import dashscope
        dashscope.api_key = self.api_key

        from dashscope.audio.asr import Recognition

        kwargs = {}
        if self.language_hint:
            kwargs["language_hints"] = [self.language_hint]

        # Faster sentence finalization
        kwargs["semantic_punctuation_enabled"] = False

        callback = _Callback(self)
        self._recognition = Recognition(
            model=self.model,
            callback=callback,
            format="pcm",
            sample_rate=16000,
            **kwargs,
        )

    def start(self):
        with self._lock:
            if self._running:
                return
            try:
                self._create_recognition()
                self._recognition.start()
                self._running = True
                print(f"[ASR] Started (model={self.model})", flush=True)
            except Exception as e:
                print(f"[ASR] Start error: {e}", flush=True)
                self._running = False
                self._recognition = None

    def stop(self):
        with self._lock:
            self._running = False
            self._connected = False
            if self._recognition:
                try:
                    self._recognition.stop()
                except Exception:
                    pass
                self._recognition = None

    def _ensure_running(self):
        """Restart ASR if it was stopped (e.g., due to silence timeout)."""
        if not self._running:
            return False
        # Recognition exists and is connecting/connected - OK to feed audio
        if self._recognition is not None:
            return True
        # Recognition was lost (e.g., after error) - reconnect
        try:
            self._create_recognition()
            self._recognition.start()
            logger.info("DashScope ASR reconnected")
        except Exception as e:
            logger.warning(f"DashScope ASR reconnect error: {e}")
            return False
        return True

    def feed_audio(self, audio: np.ndarray):
        if not self._running:
            return
        if not self._ensure_running():
            return
        pcm16 = (audio * 32768).astype(np.int16).tobytes()
        try:
            self._recognition.send_audio_frame(pcm16)
        except Exception as e:
            logger.warning(f"DashScope ASR feed error: {e}")
            self._connected = False
            self._recognition = None

    def flush(self):
        """No explicit flush needed for DashScope SDK - it handles silence detection."""
        pass


# Register
ASRFactory.register("dashscope", lambda s, hw: DashScopeASR(s, hw))
