"""
VRC-Translator: Main entry point.
Unified VRChat voice translation tool combining Yakutan + MioVRC features.
"""
import os
import sys
import logging
import signal
import threading
import time
from pathlib import Path

# Fix proxy issues for API calls
os.environ.setdefault('NO_PROXY', '*')
os.environ.setdefault('no_proxy', '*')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config.settings import get_settings, reload_settings
from src.app_state import get_state
from src.audio.mic_recorder import MicRecorder
from src.audio.desktop_recorder import DesktopRecorder
from src.asr.base import ASRFactory, ASRResult
from src.translators.factory import TranslatorFactory
from src.text.dictionary import DictionaryCorrector
from src.text.processor import TextProcessor
from src.osc.sender import OSCSender
from src.osc.listener import OSCListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("VRC-Translator")


class VRCTranslator:
    """Main application orchestrator."""

    def __init__(self):
        self.settings = get_settings()
        self.state = get_state()
        self._stop_event = threading.Event()
        self._web_thread = None

    def start(self):
        """Start all components."""
        logger.info("=" * 50)
        logger.info("VRC-Translator starting...")
        logger.info("=" * 50)

        try:
            self._init_dictionary()
            self._init_text_processor()
            self._init_translators()
            self._init_asr()
            self._init_audio()
            self._init_osc()
            self._start_web_ui()

            # Start components
            self.state.osc_sender.start()
            self.state.osc_listener.start()
            self.state.mic_recorder.start()
            if self.state.desktop_recorder:
                self.state.desktop_recorder.start()

            if self.settings.osc.mic_control_enabled:
                # Mic control ON: wait for VRChat unmute to start ASR
                self.state.is_muted = True
                self.state.subtitle.is_listening = False
                logger.info("Waiting for VRChat unmute to start ASR...")
            else:
                # Mic control OFF: start ASR immediately
                self.state.asr.start()
                self.state.subtitle.is_listening = True

            self.state.is_running = True
            logger.info("All components started successfully")
            logger.info(f"Web UI: http://127.0.0.1:{self.settings.ui.web_port}")
            logger.info(f"Overlay data: http://127.0.0.1:{self.settings.display.overlay_port}/api/overlay")

            # Register signal handlers
            signal.signal(signal.SIGINT, lambda *_: self.stop())
            signal.signal(signal.SIGTERM, lambda *_: self.stop())

            # Keep main thread alive
            while not self._stop_event.is_set():
                self._stop_event.wait(1.0)

        except Exception as e:
            logger.error(f"Startup error: {e}", exc_info=True)
            self.stop()

    def stop(self):
        """Stop all components."""
        logger.info("Stopping VRC-Translator...")
        self._stop_event.set()
        self.state.is_running = False

        for component_name in ["mic_recorder", "desktop_recorder", "asr", "reverse_asr",
                               "osc_sender", "osc_listener"]:
            component = getattr(self.state, component_name, None)
            if component:
                try:
                    component.stop()
                except Exception as e:
                    logger.error(f"Error stopping {component_name}: {e}")

        logger.info("VRC-Translator stopped")

    # ── Initialization ─────────────────────────────────────────

    def _init_dictionary(self):
        self.state.dictionary = DictionaryCorrector()
        self.state.dictionary.load()
        logger.info("Dictionary system initialized")

    def _init_text_processor(self):
        self.state.text_processor = TextProcessor(
            enable_furigana=self.settings.display.enable_ja_furigana,
            enable_pinyin=self.settings.display.enable_zh_pinyin,
            max_length=self.settings.osc.max_text_length,
            fancy_style=self.settings.display.text_fancy_style,
        )

    def _init_translators(self):
        # Import to register ctranslate2 backend
        from src.translators.api import ctranslate2_translator

        # Primary translator (self-speech)
        self.state.translator = TranslatorFactory.create(
            self.settings.translation.primary_backend, self.settings
        )
        logger.info(f"Primary translator: {self.settings.translation.primary_backend}")

        # Reverse translator (others' speech)
        if self.settings.reverse_translation.enabled:
            backend = self.settings.reverse_translation.backend
            if backend == "same":
                backend = self.settings.translation.primary_backend
            self.state.reverse_translator = TranslatorFactory.create(backend, self.settings)
            logger.info(f"Reverse translator: {backend}")

    def _init_asr(self):
        # Import engines to register them
        from src.asr.engines import dashscope_asr, sensevoice_asr, faster_whisper_asr

        # Primary ASR (mic - self-speech)
        hot_words = self._load_hot_words()
        self.state.asr = ASRFactory.create(self.settings.asr.backend, self.settings, hot_words)
        self.state.asr.set_callback(self._on_self_speech)
        self.state.subtitle.asr_backend = self.settings.asr.backend
        logger.info(f"Primary ASR: {self.settings.asr.backend}")

        # Reverse ASR (desktop - others' speech)
        if self.settings.reverse_translation.enabled:
            # Reverse uses same ASR engine type
            self.state.reverse_asr = ASRFactory.create(self.settings.asr.backend, self.settings, hot_words)
            self.state.reverse_asr.set_callback(self._on_others_speech)
            self.state.subtitle.is_reverse_active = True
            logger.info("Reverse ASR initialized")

    def _init_audio(self):
        # Microphone recorder
        self.state.mic_recorder = MicRecorder(
            device_index=self.settings.audio.mic_device_index,
            sample_rate=self.settings.audio.sample_rate,
            on_speech_start=self._on_mic_speech_start,
            on_speech_end=self._on_mic_speech_end,
        )

        # Desktop audio recorder (for reverse translation)
        if self.settings.reverse_translation.enabled:
            self.state.desktop_recorder = DesktopRecorder(
                loopback_device=self.settings.reverse_translation.loopback_device,
                sample_rate=self.settings.audio.sample_rate,
                on_speech_start=self._on_desktop_speech_start,
                on_speech_end=self._on_desktop_speech_end,
            )

        # Mute control
        def on_mute_change(muted):
            self.state.is_muted = muted
            if self.settings.osc.mic_control_enabled:
                if muted:
                    if self.state.asr and self.state.asr._running:
                        self.state.asr.flush()
                        self.state.asr.stop()
                    self.state.mic_recorder.pause()
                    if self.state.osc_sender:
                        self.state.osc_sender.set_typing(False)
                    self.state.subtitle.is_listening = False
                    logger.info("Mic muted - ASR stopped")
                else:
                    self.state.mic_recorder.resume()
                    if self.state.asr and not self.state.asr._running:
                        self.state.asr.start()
                    self.state.subtitle.is_listening = True
                    logger.info("Mic unmuted - ASR started")

        self._on_mute_change = on_mute_change

    def _init_osc(self):
        self.state.osc_sender = OSCSender(
            host=self.settings.osc.send_host,
            port=self.settings.osc.send_port,
            max_length=self.settings.osc.max_text_length,
            min_interval=self.settings.osc.min_send_interval,
        )

        self.state.osc_listener = OSCListener(
            port=self.settings.osc.listen_port,
            on_mute_change=self._on_mute_change,
        )

    def _start_web_ui(self):
        from src.ui.app import create_app
        app = create_app(self.settings, self.state)

        def run_web():
            app.run(
                host="127.0.0.1",
                port=self.settings.ui.web_port,
                debug=False,
                use_reloader=False,
            )

        self._web_thread = threading.Thread(target=run_web, daemon=True)
        self._web_thread.start()

    # ── Audio callbacks ────────────────────────────────────────

    def _on_mic_speech_start(self):
        self.state.subtitle.is_listening = True

    def _on_mic_speech_end(self, audio):
        """Called when mic detects end of speech segment."""
        if self.state.asr:
            self.state.asr.feed_audio(audio)

    def _on_desktop_speech_start(self):
        pass

    def _on_desktop_speech_end(self, audio):
        """Called when desktop audio detects end of speech segment."""
        if self.state.reverse_asr:
            # Apply self-suppression
            if self.settings.reverse_translation.self_suppress:
                self.state.desktop_recorder.suppress_self(
                    self.settings.reverse_translation.self_suppress_seconds
                )
            self.state.reverse_asr.feed_audio(audio)

    # ── ASR callbacks ──────────────────────────────────────────

    def _on_self_speech(self, result: ASRResult):
        """Called when self-speech ASR produces a result."""
        text = result.text
        if not text.strip():
            return

        # Dictionary correction
        if self.state.dictionary:
            text = self.state.dictionary.correct(text, result.language)

        if result.is_final:
            self.state.update_outgoing(text, "", is_partial=False)
            # Translate
            self._translate_outgoing(text, result.language)
            # Send to chatbox
            if self.state.osc_sender and self.settings.osc.enabled:
                translated = self.state.subtitle.outgoing_translated
                if translated:
                    self.state.osc_sender.send_chatbox(translated, priority="high")
        else:
            # Send partial text with typing indicator
            if self.state.osc_sender and self.settings.osc.enabled:
                self.state.osc_sender.send_partial(text)
            # Partial result
            self.state.update_outgoing(text, "", is_partial=True)
            if self.settings.display.show_partial_results:
                self._translate_outgoing_partial(text, result.language)

    def _on_others_speech(self, result: ASRResult):
        """Called when others' speech ASR produces a result."""
        text = result.text
        if not text.strip():
            return

        # Dictionary correction
        if self.state.dictionary:
            text = self.state.dictionary.correct(text, result.language)

        if result.is_final:
            self.state.update_incoming(text, "", is_partial=False)
            self._translate_incoming(text, result.language)
        else:
            self.state.update_incoming(text, "", is_partial=True)

    # ── Translation ────────────────────────────────────────────

    def _translate_outgoing(self, text: str, source_lang: str):
        """Translate self-speech to target language."""
        try:
            target = self.settings.translation.target_language
            result = self.state.translator.translate(text, source_lang, target)
            processed = self.state.text_processor.process(result.translated, target)
            self.state.update_outgoing(text, processed, is_partial=False)

            # Update chatbox with final translation
            if self.state.osc_sender and self.settings.osc.enabled:
                self.state.osc_sender.send_chatbox(processed, priority="high")
        except Exception as e:
            logger.error(f"Outgoing translation error: {e}")

    def _translate_outgoing_partial(self, text: str, source_lang: str):
        """Translate partial self-speech (for display only)."""
        try:
            target = self.settings.translation.target_language
            result = self.state.translator.translate(text, source_lang, target)
            self.state.update_outgoing(text, result.translated, is_partial=True)
        except Exception:
            pass

    def _translate_incoming(self, text: str, source_lang: str):
        """Translate others' speech."""
        try:
            target = self.settings.reverse_translation.target_language
            translator = self.state.reverse_translator or self.state.translator
            result = translator.translate(text, source_lang, target)
            processed = self.state.text_processor.process(result.translated, target)
            self.state.update_incoming(text, processed, is_partial=False)
        except Exception as e:
            logger.error(f"Incoming translation error: {e}")

    # ── Utilities ──────────────────────────────────────────────

    def _load_hot_words(self) -> list:
        hot_words = []
        hot_words_dir = Path(__file__).parent / "hot_words"
        if hot_words_dir.exists():
            for f in hot_words_dir.glob("*.txt"):
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        hot_words.extend(line.strip() for line in fh if line.strip())
                except Exception:
                    pass
        return hot_words


def main():
    app = VRCTranslator()
    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()
    sys.exit(0)


if __name__ == "__main__":
    main()
