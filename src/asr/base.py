"""
Abstract ASR backend and factory.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ASRResult:
    text: str
    is_final: bool
    language: str = ""
    confidence: float = 0.0


ASRCallback = Callable[[ASRResult], None]


class BaseASR(ABC):
    """Abstract base class for ASR backends."""

    def __init__(self):
        self._callback: Optional[ASRCallback] = None

    def set_callback(self, callback: ASRCallback):
        self._callback = callback

    @abstractmethod
    def start(self):
        """Start the ASR engine."""
        ...

    @abstractmethod
    def stop(self):
        """Stop the ASR engine."""
        ...

    @abstractmethod
    def feed_audio(self, audio: np.ndarray):
        """Feed audio data (float32, 16kHz mono)."""
        ...

    @abstractmethod
    def flush(self):
        """Force flush any buffered audio (e.g., on mute)."""
        ...

    def _emit(self, result: ASRResult):
        if self._callback:
            self._callback(result)


class ASRFactory:
    """Creates ASR backends by name."""

    _backends = {}

    @classmethod
    def register(cls, name: str, factory_fn):
        cls._backends[name] = factory_fn

    @classmethod
    def create(cls, name: str, settings, hot_words: Optional[list[str]] = None) -> BaseASR:
        if name not in cls._backends:
            raise ValueError(f"Unknown ASR backend: {name}. Available: {list(cls._backends.keys())}")
        return cls._backends[name](settings, hot_words)

    @classmethod
    def available_backends(cls) -> dict[str, str]:
        """Return {name: description} of available backends."""
        return {
            "dashscope": "阿里云 DashScope (云端, 需要API Key)",
            "qwen": "Qwen3 ASR (云端, DashScope API Key)",
            "local_sensevoice": "SenseVoice Small (本地, 无需网络)",
            "faster_whisper": "faster-whisper (本地, 多语言, 推荐)",
        }
