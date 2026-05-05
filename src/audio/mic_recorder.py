"""
Microphone audio capture with VAD.
Adapted from Yakutan's audio_capture.py and MioVRC's recorder.py.
"""
import queue
import threading
import time
import logging
from typing import Optional, Callable

import numpy as np

from .adaptive_denoiser import AdaptiveDenoiser

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 1600  # 100ms at 16kHz (matching Yakutan)


class MicRecorder:
    """Captures microphone audio and detects speech using VAD."""

    def __init__(self, device_index: Optional[int] = None,
                 sample_rate: int = SAMPLE_RATE,
                 on_speech_start: Optional[Callable] = None,
                 on_speech_end: Optional[Callable[[np.ndarray], None]] = None,
                 denoise_strength: float = 0.5):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end

        self._stream = None
        self._audio_queue: queue.Queue = queue.Queue(maxsize=100)
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._vad = None
        self._denoiser = AdaptiveDenoiser(strength=denoise_strength)

        # Buffer for collecting speech segments
        self._speech_buffer: list[np.ndarray] = []
        self._is_speaking = False
        self._silence_frames = 0
        self._pre_speech_buffer: list[np.ndarray] = []
        self._pre_speech_max_frames = 3  # ~0.2s at 16kHz/4096

    def _init_vad(self, mode: str = "silero", threshold: float = 0.5):
        """Initialize VAD engine."""
        if mode == "silero":
            try:
                import onnxruntime as ort
                model_path = self._get_silero_model_path()
                if model_path and model_path.exists():
                    self._vad = SileroVAD(model_path, threshold)
                    logger.info("Silero VAD initialized")
                    return
            except Exception as e:
                logger.warning(f"Failed to init Silero VAD: {e}")

        if mode in ("silero", "energy"):
            self._vad = EnergyVAD(threshold=threshold)
            logger.info("Energy VAD initialized (fallback)")
        else:
            self._vad = None
            logger.info("VAD disabled")

    def _get_silero_model_path(self):
        from pathlib import Path
        candidates = [
            Path(__file__).parent / "models" / "silero_vad.jit",
            Path(__file__).parent.parent / "asr" / "models" / "silero_vad.jit",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def start(self):
        """Start microphone recording."""
        if self._running:
            return
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("MicRecorder started")

    def stop(self):
        """Stop microphone recording."""
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
        logger.info("MicRecorder stopped")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _capture_loop(self):
        """Main capture loop running in a thread."""
        import pyaudio

        pa = pyaudio.PyAudio()
        try:
            # Find device
            device_index = self.device_index
            if device_index is None:
                device_index = pa.get_default_input_device_info()["index"]

            # Check sample rate support
            device_info = pa.get_device_info_by_index(device_index)
            supported_rate = int(device_info["defaultSampleRate"])
            capture_rate = self.sample_rate if self._supports_rate(pa, device_index, self.sample_rate) else supported_rate

            self._stream = pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=capture_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=BLOCK_SIZE,
            )

            resample_needed = (capture_rate != self.sample_rate)
            logger.info(f"Mic opened: device={device_info['name']}, rate={capture_rate}, resample={resample_needed}")

            while self._running:
                try:
                    data = self._stream.read(BLOCK_SIZE, exception_on_overflow=False)
                except Exception as e:
                    logger.error(f"Mic read error: {e}")
                    time.sleep(0.1)
                    continue

                if self._paused:
                    continue

                # Convert to numpy
                audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

                # Resample if needed
                if resample_needed:
                    audio = self._resample(audio, capture_rate, self.sample_rate)

                # Noise reduction
                audio = self._denoiser.process(audio, update_profile=True)

                # Process through VAD
                self._process_audio(audio)

        except Exception as e:
            logger.error(f"Mic capture error: {e}")
        finally:
            try:
                pa.terminate()
            except Exception:
                pass

    def _process_audio(self, audio: np.ndarray):
        """Process audio chunk through VAD."""
        if self._vad is None:
            # No VAD, just buffer everything and flush periodically
            self._speech_buffer.append(audio)
            total = np.concatenate(self._speech_buffer)
            if len(total) >= self.sample_rate * 2:  # 2 seconds
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
                # Include pre-speech buffer
                self._speech_buffer.extend(self._pre_speech_buffer)
                self._pre_speech_buffer.clear()
            self._speech_buffer.append(audio)
            self._silence_frames = 0
        else:
            if self._is_speaking:
                self._silence_frames += 1
                self._speech_buffer.append(audio)
                # Flush after enough silence (2 frames = 200ms, faster response)
                if self._silence_frames >= 2:
                    self._flush_speech()
            else:
                # Keep pre-speech buffer
                self._pre_speech_buffer.append(audio)
                if len(self._pre_speech_buffer) > self._pre_speech_max_frames:
                    self._pre_speech_buffer.pop(0)

    def _flush_speech(self):
        """Flush collected speech to callback."""
        if self._speech_buffer and self.on_speech_end:
            audio = np.concatenate(self._speech_buffer)
            if len(audio) > self.sample_rate * 0.3:  # Min 0.3s
                self.on_speech_end(audio)
        self._speech_buffer.clear()
        self._is_speaking = False
        self._silence_frames = 0

    def flush(self):
        """Manually flush current speech buffer (e.g., on mute)."""
        if self._is_speaking:
            self._flush_speech()

    @staticmethod
    def _supports_rate(pa, device_index, rate):
        try:
            return pa.is_format_supported(
                rate, input_device=device_index, input_channels=1, input_format=pyaudio.paInt16
            )
        except Exception:
            return False

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
    def list_devices() -> list[dict]:
        """List available input devices."""
        try:
            import pyaudio
        except ImportError:
            return [{"index": 0, "name": "(pyaudio 未安装, 使用默认设备)", "sample_rate": 16000, "channels": 1}]
        pa = pyaudio.PyAudio()
        devices = []
        try:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info["maxInputChannels"] > 0:
                    devices.append({
                        "index": i,
                        "name": info["name"],
                        "sample_rate": int(info["defaultSampleRate"]),
                        "channels": info["maxInputChannels"],
                    })
        finally:
            pa.terminate()
        return devices


# ── VAD Implementations ────────────────────────────────────────

class SileroVAD:
    """Silero VAD using ONNX Runtime."""
    def __init__(self, model_path, threshold: float = 0.5):
        import onnxruntime as ort
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.threshold = threshold
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = 16000

    def is_speech(self, audio: np.ndarray) -> bool:
        if len(audio) < 512:
            audio = np.pad(audio, (0, 512 - len(audio)))
        audio_input = audio[:512].astype(np.float32).reshape(1, -1)
        sr = np.array([self._sr], dtype=np.int64)
        try:
            out, self._state = self.session.run(None, {
                "input": audio_input, "state": self._state, "sr": sr
            })
            return float(out[0][0]) > self.threshold
        except Exception:
            return False

    def reset(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)


class EnergyVAD:
    """Simple energy-based VAD fallback."""
    def __init__(self, threshold: float = 0.01):
        self.threshold = threshold

    def is_speech(self, audio: np.ndarray) -> bool:
        energy = np.sqrt(np.mean(audio ** 2))
        return energy > self.threshold

    def reset(self):
        pass
