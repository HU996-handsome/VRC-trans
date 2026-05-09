"""
Desktop audio loopback capture for reverse translation.
Captures system audio output (VRChat's audio) via WASAPI loopback.
"""
import queue
import threading
import time
import logging
from typing import Optional, Callable

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class DesktopRecorder:
    """Captures desktop audio via WASAPI loopback for reverse translation."""

    def __init__(self, loopback_device: Optional[str] = None,
                 sample_rate: int = SAMPLE_RATE,
                 on_speech_start: Optional[Callable] = None,
                 on_speech_end: Optional[Callable[[np.ndarray], None]] = None,
                 on_audio: Optional[Callable[[np.ndarray], None]] = None):
        self.loopback_device = loopback_device
        self.sample_rate = sample_rate
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self.on_audio = on_audio

        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._vad = None
        self._stream = None

        # Speech buffer
        self._speech_buffer: list[np.ndarray] = []
        self._is_speaking = False
        self._silence_frames = 0
        self._silence_threshold = 5  # frames of silence before flush

        # Self-suppression
        self._self_suppress_until = 0.0

    def _init_vad(self, threshold: float = 0.5):
        """Initialize Silero VAD for desktop audio."""
        try:
            import onnxruntime as ort
            from pathlib import Path
            model_path = Path(__file__).parent / "models" / "silero_vad.jit"
            if not model_path.exists():
                model_path = Path(__file__).parent.parent / "asr" / "models" / "silero_vad.jit"
            if model_path.exists():
                self._vad = _DesktopSileroVAD(model_path, threshold)
                logger.info("Desktop Silero VAD initialized")
                return
        except Exception as e:
            logger.warning(f"Desktop Silero VAD failed: {e}, using Energy VAD")

        self._vad = _DesktopEnergyVAD()
        logger.info("Desktop Energy VAD initialized (fallback)")

    def start(self):
        if self._running:
            return
        self._running = True
        self._paused = False
        self._init_vad()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("DesktopRecorder started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        logger.info("DesktopRecorder stopped")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def suppress_self(self, duration: float = 0.65):
        """Suppress audio processing after own message sent."""
        self._self_suppress_until = time.time() + duration

    def _capture_loop(self):
        """Main capture loop using PyAudioWPatch for WASAPI loopback."""
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            logger.error("pyaudiowpatch not installed. Desktop audio capture unavailable.")
            return

        pa = pyaudio.PyAudio()
        loopback_info = None
        try:
            # Find loopback device
            loopback_info = self._find_loopback_device(pa)
            if not loopback_info:
                logger.error("No WASAPI loopback device found")
                return

            device_name = loopback_info["name"]
            device_index = loopback_info["index"]
            native_rate = int(loopback_info["defaultSampleRate"])
            native_channels = int(loopback_info["maxInputChannels"])

            print(f"[Desktop] Loopback device: {device_name} (rate={native_rate}, ch={native_channels})", flush=True)

            try:
                self._stream = pa.open(
                    format=pyaudio.paFloat32,
                    channels=native_channels,
                    rate=native_rate,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=4096,
                )
                logger.info("Desktop stream opened")
            except Exception as e:
                logger.error(f"Desktop stream open failed: {e}")
                return

            resample_needed = (native_rate != self.sample_rate)

            while self._running:
                try:
                    data = self._stream.read(4096, exception_on_overflow=False)
                except Exception as e:
                    print(f"[Desktop] Read error: {e}", flush=True)
                    time.sleep(0.1)
                    continue

                if self._paused:
                    continue

                # Self-suppression check
                if time.time() < self._self_suppress_until:
                    continue

                # Convert to mono float32
                audio = np.frombuffer(data, dtype=np.float32)
                if native_channels > 1:
                    audio = audio.reshape(-1, native_channels).mean(axis=1)

                # Resample
                if resample_needed:
                    audio = self._resample(audio, native_rate, self.sample_rate)

                # Process through VAD
                self._process_audio(audio)

        except Exception as e:
            logger.error(f"Desktop capture error: {e}")
        finally:
            pass
            try:
                pa.terminate()
            except Exception:
                pass

    def _find_loopback_device(self, pa) -> Optional[dict]:
        """Find the WASAPI loopback device matching the configured output device."""
        target = self.loopback_device
        loopback_devices = []

        for i in range(pa.get_device_count()):
            try:
                info = pa.get_device_info_by_index(i)
                if "loopback" in info["name"].lower() and info["maxInputChannels"] > 0:
                    loopback_devices.append({"index": i, **info})
            except Exception:
                continue

        if not loopback_devices:
            return None

        if target:
            # Try exact match
            for dev in loopback_devices:
                if target.lower() in dev["name"].lower():
                    return dev

        # Return first available
        return loopback_devices[0]

    def _process_audio(self, audio: np.ndarray):
        """Process audio through VAD."""
        # Always send audio to ASR continuously (let ASR handle its own VAD)
        if self.on_audio:
            self.on_audio(audio)

        if self._vad is None:
            self._speech_buffer.append(audio)
            total = np.concatenate(self._speech_buffer)
            if len(total) >= self.sample_rate * 3:
                if self.on_speech_end:
                    self.on_speech_end(total)
                self._speech_buffer.clear()
            return

        is_speech = self._vad.is_speech(audio)

        if is_speech:
            if not self._is_speaking:
                self._is_speaking = True
                self._silence_frames = 0
                if self.on_speech_start:
                    self.on_speech_start()
            self._speech_buffer.append(audio)
            self._silence_frames = 0
        else:
            if self._is_speaking:
                self._silence_frames += 1
                self._speech_buffer.append(audio)
                if self._silence_frames >= self._silence_threshold:
                    self._flush_speech()

    def _flush_speech(self):
        if self._speech_buffer and self.on_speech_end:
            audio = np.concatenate(self._speech_buffer)
            duration = len(audio) / self.sample_rate
            if duration > 0.5:  # Min 0.5s
                print(f"[Desktop] Speech flushed: {duration:.1f}s", flush=True)
                self.on_speech_end(audio)
        self._speech_buffer.clear()
        self._is_speaking = False
        self._silence_frames = 0

    @staticmethod
    def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        if src_rate == dst_rate:
            return audio
        try:
            import soxr
            return soxr.resample(audio, src_rate, dst_rate)
        except ImportError:
            ratio = dst_rate / src_rate
            n = int(len(audio) * ratio)
            return np.interp(np.linspace(0, len(audio), n), np.arange(len(audio)), audio).astype(np.float32)

    @staticmethod
    def list_loopback_devices() -> list[dict]:
        """List available WASAPI loopback devices."""
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            return []

        pa = pyaudio.PyAudio()
        devices = []
        try:
            for i in range(pa.get_device_count()):
                try:
                    info = pa.get_device_info_by_index(i)
                    if "loopback" in info["name"].lower() and info["maxInputChannels"] > 0:
                        devices.append({
                            "index": i,
                            "name": info["name"],
                            "sample_rate": int(info["defaultSampleRate"]),
                            "channels": info["maxInputChannels"],
                        })
                except Exception:
                    continue
        finally:
            pa.terminate()
        return devices


class _DesktopSileroVAD:
    def __init__(self, model_path, threshold: float = 0.5):
        import onnxruntime as ort
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.threshold = threshold
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
            return float(out[0][0]) > self.threshold
        except Exception:
            return False


class _DesktopEnergyVAD:
    def __init__(self, threshold: float = 0.005):
        self.threshold = threshold

    def is_speech(self, audio: np.ndarray) -> bool:
        energy = np.sqrt(np.mean(audio ** 2))
        return energy > self.threshold
