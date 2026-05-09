"""
Centralized mutable runtime state.
"""
import threading
from dataclasses import dataclass, field
from typing import Optional

from .audio.mic_recorder import MicRecorder
from .audio.desktop_recorder import DesktopRecorder
from .asr.base import BaseASR
from .translators.base import ContextAwareTranslator
from .text.dictionary import DictionaryCorrector
from .text.processor import TextProcessor
from .osc.sender import OSCSender
from .osc.listener import OSCListener


@dataclass
class SubtitleState:
    """Current subtitle display state."""
    # Self-speech (outgoing)
    outgoing_original: str = ""
    outgoing_translated: str = ""
    outgoing_is_partial: bool = False
    # Others' speech (incoming)
    incoming_original: str = ""
    incoming_translated: str = ""
    incoming_is_partial: bool = False
    # Status
    is_listening: bool = False
    is_reverse_active: bool = False
    asr_backend: str = ""
    translation_backend: str = ""


class AppState:
    """Singleton holding all runtime components."""

    def __init__(self):
        # Components
        self.mic_recorder: Optional[MicRecorder] = None
        self.desktop_recorder: Optional[DesktopRecorder] = None
        self.asr: Optional[BaseASR] = None
        self.reverse_asr: Optional[BaseASR] = None
        self.translator: Optional[ContextAwareTranslator] = None
        self.reverse_translator: Optional[ContextAwareTranslator] = None
        self.dictionary: Optional[DictionaryCorrector] = None
        self.text_processor: Optional[TextProcessor] = None
        self.osc_sender: Optional[OSCSender] = None
        self.osc_listener: Optional[OSCListener] = None

        # State
        self.subtitle = SubtitleState()
        self.is_running = False
        self.is_muted = False

        # Lock for thread safety
        self._lock = threading.Lock()

    def update_outgoing(self, original: str, translated: str, is_partial: bool = False):
        with self._lock:
            self.subtitle.outgoing_original = original
            self.subtitle.outgoing_translated = translated
            self.subtitle.outgoing_is_partial = is_partial

    def update_incoming(self, original: str, translated: str, is_partial: bool = False):
        with self._lock:
            self.subtitle.incoming_original = original
            self.subtitle.incoming_translated = translated
            self.subtitle.incoming_is_partial = is_partial

    def get_subtitle_snapshot(self) -> dict:
        with self._lock:
            return {
                "outgoing": {
                    "original": self.subtitle.outgoing_original,
                    "translated": self.subtitle.outgoing_translated,
                    "is_partial": self.subtitle.outgoing_is_partial,
                },
                "incoming": {
                    "original": self.subtitle.incoming_original,
                    "translated": self.subtitle.incoming_translated,
                    "is_partial": self.subtitle.incoming_is_partial,
                },
                "status": {
                    "is_listening": self.subtitle.is_listening,
                    "is_reverse_active": self.subtitle.is_reverse_active,
                    "is_muted": self.is_muted,
                    "asr_backend": self.subtitle.asr_backend,
                    "translation_backend": self.subtitle.translation_backend,
                },
            }


# Global singleton
_state: Optional[AppState] = None
_lock = threading.Lock()


def get_state() -> AppState:
    global _state
    if _state is None:
        with _lock:
            if _state is None:
                _state = AppState()
    return _state
