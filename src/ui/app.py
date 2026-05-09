"""
Flask Web UI for VRC-Translator.
Provides REST API for configuration, control, and subtitle data.
"""
import json
import logging
import os
import threading
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS

logger = logging.getLogger(__name__)

from src.config.settings import TEMPLATES_DIR, STATIC_DIR


def create_app(settings, state) -> Flask:
    app = Flask(__name__,
                template_folder=str(TEMPLATES_DIR),
                static_folder=str(STATIC_DIR))
    CORS(app)

    # ── Pages ──────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/panel")
    def panel():
        return render_template("panel.html")

    @app.route("/overlay")
    def overlay():
        """Minimal overlay page for VR wrist display."""
        return render_template("overlay.html")

    # ── API: Status ────────────────────────────────────────────

    @app.route("/api/status")
    def api_status():
        from src.utils.vrc_detector import get_vrchat_status
        vrc = get_vrchat_status()
        return jsonify({
            "running": state.is_running,
            "pipeline_active": state.pipeline_active if hasattr(state, 'pipeline_active') else False,
            "version": "1.0.0",
            "vrchat": vrc,
        })

    @app.route("/api/vrchat/status")
    def api_vrchat_status():
        from src.utils.vrc_detector import get_vrchat_status
        return jsonify(get_vrchat_status())

    @app.route("/api/pipeline/start", methods=["POST"])
    def api_pipeline_start():
        """Start the translation pipeline."""
        import sys
        from src.utils.vrc_detector import is_vrchat_running
        vrc_running = is_vrchat_running()

        if hasattr(state, 'pipeline_active') and state.pipeline_active:
            return jsonify({"ok": True, "message": "翻译管线已在运行"})

        try:
            _start_pipeline(settings, state)
            return jsonify({"ok": True, "message": "翻译管线已启动"})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/pipeline/stop", methods=["POST"])
    def api_pipeline_stop():
        """Stop the translation pipeline."""
        try:
            _stop_pipeline(state)
            return jsonify({"ok": True, "message": "翻译管线已停止"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    def _start_pipeline(settings, state):
        """Initialize and start all translation components."""
        import sys
        import threading
        import time
        from collections import deque
        from concurrent.futures import ThreadPoolExecutor
        from src.audio.mic_recorder import MicRecorder
        from src.audio.desktop_recorder import DesktopRecorder
        from src.asr.base import ASRFactory, ASRResult
        from src.translators.factory import TranslatorFactory
        from src.osc.sender import OSCSender
        from src.osc.listener import OSCListener

        from src.asr.engines import dashscope_asr, sensevoice_asr, faster_whisper_asr
        from src.translators.api import ctranslate2_translator

        mic_control = settings.osc.mic_control_enabled

        # Thread pool for non-blocking translation
        executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="translate")
        state._translate_executor = executor

        state._partial_lock = threading.Lock()

        # Load hot words
        hot_words = []
        from src.config.settings import HOT_WORDS_DIR
        hot_words_dir = HOT_WORDS_DIR
        if hot_words_dir.exists():
            for f in hot_words_dir.glob("*.txt"):
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        hot_words.extend(line.strip() for line in fh if line.strip())
                except Exception:
                    pass

        # ── Helpers ──

        def _build_display_text(original, translated):
            """Build display text: translation only, no dual-language."""
            if translated and translated != original:
                return translated
            return original

        # ── Self-speech callback: translate as you speak ──
        _last_self_text_printed = ""
        _partial_in_flight = [False]

        def on_self_speech(result: ASRResult):
            text = result.text
            if not text.strip():
                return
            if state.dictionary:
                text = state.dictionary.correct(text, result.language)

            if result.is_final:
                # ── Final result ──
                final_text = text.strip()
                if final_text == _last_self_text_printed:
                    return

                # Track self-speech for reverse self-suppression
                _last_self_text_for_suppress = final_text
                _last_self_time_for_suppress = time.time()
                _desktop_suppress_until[0] = time.time() + settings.reverse_translation.self_suppress_seconds

                state.update_outgoing(final_text, "", is_partial=False)

                def _do_translate():
                    import time as _t
                    t0 = _t.monotonic()
                    try:
                        target = settings.translation.target_language
                        tr = state.translator.translate(final_text, result.language, target)
                        translated = state.text_processor.process(tr.translated, target) if state.text_processor else tr.translated
                        elapsed = _t.monotonic() - t0

                        nonlocal _last_self_text_printed
                        if final_text == _last_self_text_printed:
                            return
                        _last_self_text_printed = final_text

                        state.update_outgoing(final_text, translated, is_partial=False)
                        if state.osc_sender and settings.osc.enabled:
                            osc_text = f"{final_text}\n{translated}" if settings.translation.dual_line else translated
                            state.osc_sender.send_chatbox(osc_text, priority="high")
                        print(f"  [我说] {final_text}", flush=True)
                        print(f"       {translated}  ({elapsed:.2f}s)", flush=True)
                    except Exception as e:
                        logger.error(f"Translation error: {e}")

                executor.submit(_do_translate)

            else:
                # ── Partial result: translate immediately while speaking ──
                if _partial_in_flight[0]:
                    return  # Skip if a partial translation is already running
                _partial_in_flight[0] = True

                def _do_partial():
                    try:
                        target = settings.translation.target_language
                        tr = state.translator.translate(text, result.language, target)
                        translated = state.text_processor.process(tr.translated, target) if state.text_processor else tr.translated
                        state.update_outgoing(text, translated, is_partial=True)
                        if state.osc_sender and settings.osc.enabled:
                            osc_text = f"{text}\n{translated}" if settings.translation.dual_line else translated
                            state.osc_sender.send_partial(osc_text)
                    except Exception:
                        pass
                    finally:
                        _partial_in_flight[0] = False

                executor.submit(_do_partial)

        # ── Others-speech callback (optimized: direct translation, no merger delay) ──
        _recent_listen_texts: deque = deque(maxlen=8)  # (timestamp, normalized_text)
        _listen_dedup_window = 1.6  # seconds
        _last_self_text_for_suppress = ""
        _last_self_time_for_suppress = 0.0

        def _normalize_for_compare(text: str) -> str:
            """Normalize text for duplicate comparison."""
            import re
            return re.sub(r"[^\w]", "", text or "").lower()

        def _is_self_suppressed(text: str) -> bool:
            """Check if desktop audio result should be suppressed."""
            if not settings.reverse_translation.self_suppress:
                return False
            now = time.time()
            # Suppress if mic recently produced the same text
            suppress_sec = settings.reverse_translation.self_suppress_seconds
            if (now - _last_self_time_for_suppress) <= suppress_sec:
                norm = _normalize_for_compare(text)
                last_norm = _normalize_for_compare(_last_self_text_for_suppress)
                if norm == last_norm:
                    return True
                if len(norm) >= 8 and len(last_norm) >= 8:
                    if norm in last_norm or last_norm in norm:
                        return True
            return False

        def _is_recent_duplicate(text: str) -> bool:
            """Check if this text was already seen recently."""
            now = time.time()
            norm = _normalize_for_compare(text)
            # Prune old entries
            while _recent_listen_texts and (now - _recent_listen_texts[0][0]) > _listen_dedup_window:
                _recent_listen_texts.popleft()
            for _, recent_norm in _recent_listen_texts:
                if norm == recent_norm:
                    return True
            return False

        def on_others_speech(result: ASRResult):
            text = result.text
            if not text.strip():
                return
            if state.dictionary:
                text = state.dictionary.correct(text, result.language)

            if result.is_final:
                final_text = text.strip()

                # Short-result filter
                if len(final_text) < 2:
                    return

                # Self-suppression check
                if _is_self_suppressed(final_text):
                    return

                # Duplicate dedup
                if _is_recent_duplicate(final_text):
                    return
                _recent_listen_texts.append((time.time(), _normalize_for_compare(final_text)))

                state.update_incoming(final_text, "", is_partial=False)

                def _translate_reverse():
                    try:
                        target = settings.reverse_translation.target_language
                        translator = state.reverse_translator or state.translator
                        tr = translator.translate(final_text, result.language, target)
                        translated = state.text_processor.process(tr.translated, target) if state.text_processor else tr.translated

                        state.update_incoming(final_text, translated, is_partial=False)
                        print(f"  [听] {final_text}", flush=True)
                        print(f"    >>> {translated}", flush=True)
                    except Exception as e:
                        logger.error(f"Reverse translation error: {e}")

                executor.submit(_translate_reverse)
            else:
                # Partial: just update display, no translation
                state.update_incoming(text, "", is_partial=True)

        # ── Create components ──
        state.asr = ASRFactory.create(settings.asr.backend, settings, hot_words)
        state.asr.set_callback(on_self_speech)
        state.subtitle.asr_backend = settings.asr.backend

        state.reverse_asr = ASRFactory.create(settings.asr.backend, settings, hot_words)
        state.reverse_asr.set_callback(on_others_speech)
        if hasattr(state.reverse_asr, 'language_hint'):
            state.reverse_asr.language_hint = ""
        state.reverse_asr.start()
        if not settings.reverse_translation.enabled:
            state.subtitle.is_reverse_active = False

        # Mic recorder - feed audio to ASR in real-time while speaking
        def on_mic_audio(audio):
            if state.asr and state.asr._running:
                state.asr.feed_audio(audio)

        state.mic_recorder = MicRecorder(
            device_index=settings.audio.mic_device_index,
            sample_rate=settings.audio.sample_rate,
            on_audio=on_mic_audio,
            denoise_strength=settings.audio.denoise_strength,
        )

        # Desktop recorder - feed ALL audio continuously to reverse ASR
        _desktop_suppress_until = [0.0]

        def on_desktop_audio(audio):
            # Self-suppression: skip audio when user just spoke
            if time.time() < _desktop_suppress_until[0]:
                return
            if state.reverse_asr and state.reverse_asr._running:
                state.reverse_asr.feed_audio(audio)

        state.desktop_recorder = DesktopRecorder(
            loopback_device=settings.reverse_translation.loopback_device,
            sample_rate=settings.audio.sample_rate,
            on_audio=on_desktop_audio,
        )

        # OSC sender
        state.osc_sender = OSCSender(
            host=settings.osc.send_host,
            port=settings.osc.send_port,
            max_length=settings.osc.max_text_length,
            min_interval=settings.osc.min_send_interval,
        )

        # ── ASR start/stop helpers ──
        def _start_asr():
            if state.asr and not state.asr._running:
                state.asr.start()
            state.subtitle.is_listening = True

        def _stop_asr():
            if state.asr and state.asr._running:
                state.asr.flush()
                state.asr.stop()
            if state.osc_sender:
                state.osc_sender.set_typing(False)
            state.subtitle.is_listening = False

        def on_mute_change(muted):
            state.is_muted = muted
            if mic_control:
                if muted:
                    _stop_asr()
                    if state.mic_recorder:
                        state.mic_recorder.pause()
                else:
                    if state.mic_recorder:
                        state.mic_recorder.resume()
                    _start_asr()

        state.osc_listener = OSCListener(
            port=settings.osc.listen_port,
            on_mute_change=on_mute_change,
        )

        # ── Start components ──
        state.osc_sender.start()
        state.osc_listener.start()
        state.mic_recorder.start()

        if state.desktop_recorder and settings.reverse_translation.enabled:
            state.desktop_recorder.start()

        # Start unmuted (OSC listener will handle mute/unmute from VRChat)
        state.is_muted = False
        _start_asr()

        state.pipeline_active = True
        state.is_running = True

    def _stop_pipeline(state):
        """Stop all translation components."""
        # Shutdown translation executor
        executor = getattr(state, "_translate_executor", None)
        if executor:
            executor.shutdown(wait=False, cancel_futures=True)
            state._translate_executor = None

        for name in ["mic_recorder", "desktop_recorder", "asr", "reverse_asr", "osc_sender", "osc_listener"]:
            comp = getattr(state, name, None)
            if comp:
                try:
                    comp.stop()
                except Exception:
                    pass
                setattr(state, name, None)
        state.pipeline_active = False
        state.subtitle.is_listening = False
        state.subtitle.is_reverse_active = False
        logger.info("Translation pipeline stopped")

    @app.route("/api/subtitles")
    def api_subtitles():
        return jsonify(state.get_subtitle_snapshot())

    @app.route("/api/overlay")
    def api_overlay_data():
        """Minimal data endpoint for overlay program."""
        snap = state.get_subtitle_snapshot()
        out = snap["outgoing"]
        inc = snap["incoming"]
        dual = settings.translation.dual_line
        out_text = f"{out['original']}\n{out['translated']}" if dual and out["translated"] else (out["translated"] or out["original"])
        in_text = f"{inc['original']}\n{inc['translated']}" if dual and inc["translated"] else (inc["translated"] or inc["original"])
        return jsonify({
            "out": out_text,
            "in": in_text,
            "out_partial": out["is_partial"],
            "in_partial": inc["is_partial"],
        })

    # ── API: Control ───────────────────────────────────────────

    @app.route("/api/start", methods=["POST"])
    def api_start():
        if not state.is_running:
            from main import VRCTranslator
            # TODO: proper start/stop lifecycle
        return jsonify({"ok": True, "running": state.is_running})

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        if state.is_running:
            state.is_running = False
        return jsonify({"ok": True, "running": state.is_running})

    @app.route("/api/toggle-mute", methods=["POST"])
    def api_toggle_mute():
        state.is_muted = not state.is_muted
        if state.is_muted:
            # Mute: stop ASR, pause mic
            if state.asr and state.asr._running:
                state.asr.flush()
                state.asr.stop()
            if state.mic_recorder:
                state.mic_recorder.pause()
            if state.osc_sender:
                state.osc_sender.set_typing(False)
            state.subtitle.is_listening = False
        else:
            # Unmute: resume mic, start ASR
            if state.mic_recorder:
                state.mic_recorder.resume()
            if state.asr and not state.asr._running:
                state.asr.start()
            state.subtitle.is_listening = True
        return jsonify({"muted": state.is_muted})

    @app.route("/api/toggle-reverse", methods=["POST"])
    def api_toggle_reverse():
        enabled = not state.subtitle.is_reverse_active
        state.subtitle.is_reverse_active = enabled
        settings.reverse_translation.enabled = enabled
        settings.save()
        if state.desktop_recorder:
            if enabled:
                state.desktop_recorder.start()
            else:
                state.desktop_recorder.stop()
        return jsonify({"reverse_active": enabled})

    # ── API: Text Input (closed-mic feature) ───────────────────

    @app.route("/api/send-text", methods=["POST"])
    def api_send_text():
        """Manual text input for closed-mic users."""
        data = request.get_json()
        text = data.get("text", "").strip()
        if not text:
            return jsonify({"error": "Empty text"}), 400

        # Translate and send
        if state.translator:
            target = settings.translation.target_language
            result = state.translator.translate(text, "auto", target)
            processed = state.text_processor.process(result.translated, target) if state.text_processor else result.translated
            state.update_outgoing(text, processed)

            if state.osc_sender and settings.osc.enabled:
                osc_text = f"{text}\n{processed}" if settings.translation.dual_line else processed
                state.osc_sender.send_chatbox(osc_text, priority="high")

            return jsonify({
                "original": text,
                "translated": processed,
            })
        return jsonify({"error": "Translator not ready"}), 503

    # ── API: Settings ──────────────────────────────────────────

    @app.route("/api/settings", methods=["GET"])
    def api_get_settings():
        return jsonify(settings.to_dict())

    @app.route("/api/keys", methods=["GET"])
    def api_get_keys():
        """Return masked API keys (show only last 4 chars)."""
        from src.config.settings import ENV_FILE
        env_path = ENV_FILE
        keys = {}
        key_names = ["DASHSCOPE_API_KEY", "DEEPL_API_KEY", "OPENROUTER_API_KEY", "SONIOX_API_KEY"]
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        if k in key_names and v:
                            keys[k] = "****" + v[-4:] if len(v) > 4 else "****"
        return jsonify(keys)

    @app.route("/api/keys", methods=["POST"])
    def api_save_keys():
        """Save API keys to config/.env file."""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data"}), 400

        from src.config.settings import ENV_FILE
        env_path = ENV_FILE
        env_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing .env
        existing = {}
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        existing[k.strip()] = v.strip()

        # Update with new values (skip masked values)
        key_map = {
            "dashscope": "DASHSCOPE_API_KEY",
            "deepl": "DEEPL_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "soniox": "SONIOX_API_KEY",
        }
        saved = []
        for field, env_key in key_map.items():
            val = data.get(field, "").strip()
            if val and not val.startswith("****"):
                existing[env_key] = val
                saved.append(field)

        # Write back
        lines = ["# VRC-Translator API Keys", "# Auto-saved from Web UI", ""]
        for env_key in ["DASHSCOPE_API_KEY", "DEEPL_API_KEY", "OPENROUTER_API_KEY", "SONIOX_API_KEY"]:
            lines.append(f"{env_key}={existing.get(env_key, '')}")

        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        # Reload env into current process
        for env_key, val in existing.items():
            if val:
                os.environ[env_key] = val

        # Reload settings
        from src.config.settings import reload_settings
        reload_settings()

        return jsonify({"ok": True, "saved": saved})

    @app.route("/api/settings", methods=["POST"])
    def api_update_settings():
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data"}), 400

        # Update settings
        for section_name, section_data in data.items():
            section = getattr(settings, section_name, None)
            if section and isinstance(section_data, dict):
                for k, v in section_data.items():
                    if hasattr(section, k):
                        setattr(section, k, v)

        settings.save()
        return jsonify({"ok": True})

    # ── API: ASR backends ──────────────────────────────────────

    @app.route("/api/asr/backends")
    def api_asr_backends():
        from src.asr.base import ASRFactory
        return jsonify(ASRFactory.available_backends())

    @app.route("/api/asr/devices")
    def api_asr_devices():
        from src.audio.mic_recorder import MicRecorder
        return jsonify(MicRecorder.list_devices())

    @app.route("/api/asr/loopback-devices")
    def api_loopback_devices():
        from src.audio.desktop_recorder import DesktopRecorder
        return jsonify(DesktopRecorder.list_loopback_devices())

    @app.route("/api/translator/backends")
    def api_translator_backends():
        from src.translators.factory import TranslatorFactory
        return jsonify(TranslatorFactory.available_backends())

    # ── API: Dictionary ────────────────────────────────────────

    @app.route("/api/dictionary/update", methods=["POST"])
    def api_dictionary_update():
        from src.text.dictionary import DictionaryCorrector
        ok = DictionaryCorrector.download_official_dictionary()
        if ok and state.dictionary:
            state.dictionary._loaded = False
            state.dictionary.load()
        return jsonify({"ok": ok})

    @app.route("/api/dictionary/rules", methods=["GET"])
    def api_dictionary_rules():
        if state.dictionary:
            state.dictionary.load()
            return jsonify({"rules": len(state.dictionary._rules)})
        return jsonify({"rules": 0})

    @app.route("/api/dictionary/add", methods=["POST"])
    def api_dictionary_add():
        data = request.get_json()
        if not data or "replacement" not in data or "patterns" not in data:
            return jsonify({"error": "Missing fields"}), 400
        if state.dictionary:
            state.dictionary.add_user_rule(
                replacement=data["replacement"],
                patterns=data["patterns"],
                mode=data.get("mode", "substring"),
                languages=data.get("languages"),
            )
            return jsonify({"ok": True})
        return jsonify({"error": "Dictionary not ready"}), 503

    # ── API: Model management ──────────────────────────────────

    @app.route("/api/models/sensevoice/status")
    def api_sensevoice_status():
        from src.asr.engines.sensevoice_asr import SenseVoiceASR
        return jsonify(SenseVoiceASR.check_model_status())

    @app.route("/api/models/sensevoice/download", methods=["POST"])
    def api_sensevoice_download():
        from src.asr.engines.sensevoice_asr import SenseVoiceASR
        def download():
            SenseVoiceASR.download_model()
        import threading
        threading.Thread(target=download, daemon=True).start()
        return jsonify({"ok": True, "message": "Download started"})

    @app.route("/api/models/faster-whisper/models")
    def api_faster_whisper_models():
        from src.asr.engines.faster_whisper_asr import FasterWhisperASR
        return jsonify(FasterWhisperASR.list_models())

    @app.route("/api/models/faster-whisper/status/<model_name>")
    def api_faster_whisper_status(model_name):
        from src.asr.engines.faster_whisper_asr import FasterWhisperASR
        return jsonify(FasterWhisperASR.check_model_status(model_name))

    @app.route("/api/models/faster-whisper/download/<model_name>", methods=["POST"])
    def api_faster_whisper_download(model_name):
        from src.asr.engines.faster_whisper_asr import FasterWhisperASR
        def download():
            FasterWhisperASR.download_model(model_name)
        import threading
        threading.Thread(target=download, daemon=True).start()
        return jsonify({"ok": True, "message": f"Downloading {model_name}"})

    @app.route("/api/models/ctranslate2/models")
    def api_ctranslate2_models():
        from src.translators.api.ctranslate2_translator import CTranslate2Translator
        return jsonify(CTranslate2Translator.list_models())

    @app.route("/api/models/ctranslate2/status/<model_name>")
    def api_ctranslate2_status(model_name):
        from src.translators.api.ctranslate2_translator import CTranslate2Translator
        return jsonify(CTranslate2Translator.check_model_status(model_name))

    @app.route("/api/models/ctranslate2/download/<model_name>", methods=["POST"])
    def api_ctranslate2_download(model_name):
        from src.translators.api.ctranslate2_translator import CTranslate2Translator
        def download():
            CTranslate2Translator.download_model(model_name)
        import threading
        threading.Thread(target=download, daemon=True).start()
        return jsonify({"ok": True, "message": f"Downloading {model_name}"})

    return app
