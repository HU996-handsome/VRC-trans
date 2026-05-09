"""
Unified configuration for VRC-Translator.
"""
import os
import json
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────
APP_NAME = "VRC-Translator"
APP_VERSION = "1.0.0"

import sys

if getattr(sys, 'frozen', False):
    # PyInstaller: user files (config, data) next to exe
    PROJECT_ROOT = Path(sys.executable).parent
    # Bundled resources (templates, static) in temp extract dir
    _BUNDLE_DIR = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    _BUNDLE_DIR = PROJECT_ROOT

# User-editable directories (next to exe when frozen)
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DICTIONARIES_DIR = PROJECT_ROOT / "dictionaries"
HOT_WORDS_DIR = PROJECT_ROOT / "hot_words"
MODELS_DIR = DATA_DIR / "models"
LOGS_DIR = DATA_DIR / "logs"

# Bundled read-only resources
TEMPLATES_DIR = _BUNDLE_DIR / "src" / "ui" / "templates"
STATIC_DIR = _BUNDLE_DIR / "src" / "ui" / "static"

# Config files
CONFIG_FILE = CONFIG_DIR / "settings.json"
ENV_FILE = CONFIG_DIR / ".env"

# Dictionary files
DICT_BUNDLED = DICTIONARIES_DIR / "asr_terms.base.json"
DICT_OFFICIAL = DICTIONARIES_DIR / "asr_terms.official.json"
DICT_USER = DICTIONARIES_DIR / "asr_terms.user.json"
DICT_MANIFEST_URL = "https://78hejiu.top/dictionaries/asr_dictionary_manifest.json"

# ── Defaults ───────────────────────────────────────────────────

@dataclass
class ASRSettings:
    backend: str = "dashscope"          # dashscope | qwen | local_sensevoice | local_qwen3
    language_hint: str = "zh"           # zh | en | ja | ko | ru | auto
    # DashScope
    dashscope_api_key: str = ""
    dashscope_model: str = "paraformer-realtime-v2"
    # Qwen3 ASR (also uses dashscope_api_key)
    qwen_model: str = "qwen3-asr-flash-realtime-2026-02-10"
    # Local ASR
    local_engine: str = "sensevoice"    # sensevoice | qwen3
    local_vad_mode: str = "silero"      # silero | energy | disabled
    local_vad_threshold: float = 0.5
    local_vad_silence_duration: float = 0.8
    # Hot words
    hot_words_enabled: bool = True
    # Soniox (optional)
    soniox_api_key: str = ""

@dataclass
class TranslationSettings:
    # Primary translation (self-speech)
    primary_backend: str = "dashscope"  # dashscope | deepl | openrouter | google
    target_language: str = "en"
    secondary_target_language: str = ""
    fallback_language: str = "en"
    # DashScope / Qwen-MT
    dashscope_api_key: str = ""         # Shared with ASR
    qwen_mt_model: str = "qwen-mt-flash"
    # DeepL (optional)
    deepl_api_key: str = ""
    deepl_formality: str = "default"    # default | more | less | prefer_more | prefer_less
    # OpenRouter (optional)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_temperature: float = 0.3
    openrouter_timeout: float = 15.0
    # Style
    formality: str = "casual"           # casual | polite | very_polite
    sentence_style: str = "natural"     # natural | cute | cool | host
    # Streaming
    streaming_enabled: bool = True
    # Display
    dual_line: bool = True              # True = 原文+翻译两行显示
    # Smart target language
    smart_target_enabled: bool = False
    smart_target_strategy: str = "most_common"  # most_common | latest | weighted

@dataclass
class ReverseTranslationSettings:
    """Translation of others' speech."""
    enabled: bool = False
    backend: str = "same"               # same | dashscope | deepl | openrouter | google
    source_language: str = "auto"
    target_language: str = "zh"
    # Desktop audio
    loopback_device: str = ""
    segment_duration_s: float = 2.0
    tail_silence_s: float = 1.2
    # Self-suppression
    self_suppress: bool = True
    self_suppress_seconds: float = 0.65

@dataclass
class AudioSettings:
    sample_rate: int = 16000
    channels: int = 1
    block_size: int = 4096
    mic_device_index: Optional[int] = None
    denoise_strength: float = 0.5    # 0.0=off, 1.0=max

@dataclass
class OSCSettings:
    enabled: bool = True
    send_host: str = "127.0.0.1"
    send_port: int = 9000
    listen_port: int = 9001
    max_text_length: int = 144
    min_send_interval: float = 1.5
    mic_control_enabled: bool = True
    mute_delay_seconds: float = 0.2

@dataclass
class DisplaySettings:
    show_partial_results: bool = True
    dual_language: bool = False
    enable_ja_furigana: bool = False
    enable_zh_pinyin: bool = False
    text_fancy_style: str = "none"      # none | small_caps | curly | magic
    panel_width: int = 500
    panel_height: int = 200
    panel_opacity: float = 0.95
    overlay_port: int = 5002            # HTTP port for overlay data

@dataclass
class UISettings:
    language: str = "zh"                # zh | en | ja | ko | ru
    theme: str = "dark"                 # dark | light
    web_port: int = 5001
    auto_start_pipeline: bool = False   # True = 打开网页自动启动翻译

@dataclass
class Settings:
    asr: ASRSettings = field(default_factory=ASRSettings)
    translation: TranslationSettings = field(default_factory=TranslationSettings)
    reverse_translation: ReverseTranslationSettings = field(default_factory=ReverseTranslationSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    osc: OSCSettings = field(default_factory=OSCSettings)
    display: DisplaySettings = field(default_factory=DisplaySettings)
    ui: UISettings = field(default_factory=UISettings)

    # ── Serialization ──────────────────────────────────────────

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        s = cls()
        for section_name, section_cls in [
            ("asr", ASRSettings),
            ("translation", TranslationSettings),
            ("reverse_translation", ReverseTranslationSettings),
            ("audio", AudioSettings),
            ("osc", OSCSettings),
            ("display", DisplaySettings),
            ("ui", UISettings),
        ]:
            if section_name in data:
                section = getattr(s, section_name)
                for k, v in data[section_name].items():
                    if hasattr(section, k):
                        setattr(section, k, v)
        return s

    # ── File I/O ───────────────────────────────────────────────

    def save(self, path: Optional[Path] = None):
        path = path or CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        path = path or CONFIG_FILE
        if not path.exists():
            s = cls()
            s.save(path)
            return s
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (json.JSONDecodeError, KeyError):
            s = cls()
            s.save(path)
            return s

    # ── Env overrides ──────────────────────────────────────────

    def apply_env_overrides(self):
        """Load API keys and overrides from environment variables / .env file."""
        try:
            from dotenv import load_dotenv
            if ENV_FILE.exists():
                load_dotenv(ENV_FILE)
        except ImportError:
            pass

        env_map = {
            "DASHSCOPE_API_KEY": (self.asr, "dashscope_api_key"),
            "DEEPL_API_KEY": (self.translation, "deepl_api_key"),
            "OPENROUTER_API_KEY": (self.translation, "openrouter_api_key"),
            "SONIOX_API_KEY": (self.asr, "soniox_api_key"),
            "LLM_API_KEY": (self.translation, "openrouter_api_key"),
            "LLM_BASE_URL": (self.translation, "openrouter_base_url"),
            "LLM_MODEL": (self.translation, "openrouter_model"),
        }
        for env_key, (obj, attr) in env_map.items():
            val = os.environ.get(env_key)
            if val:
                setattr(obj, attr, val)

        # DashScope key is shared
        if self.asr.dashscope_api_key and not self.translation.dashscope_api_key:
            self.translation.dashscope_api_key = self.asr.dashscope_api_key

# ── Singleton ──────────────────────────────────────────────────

_settings: Optional[Settings] = None
_lock = threading.Lock()

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        with _lock:
            if _settings is None:
                _settings = Settings.load()
                _settings.apply_env_overrides()
    return _settings

def reload_settings() -> Settings:
    global _settings
    with _lock:
        _settings = Settings.load()
        _settings.apply_env_overrides()
    return _settings
