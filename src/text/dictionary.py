"""
Three-layer ASR dictionary correction system.

Layers (in priority order, later overrides earlier):
1. Bundled: Shipped with the app (VRChat-specific terms)
2. Official: Downloaded from 78hejiu.top
3. User: Custom corrections added by the user
"""
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)

DICTIONARIES_DIR = Path(__file__).resolve().parent.parent.parent / "dictionaries"
MANIFEST_URL = "https://78hejiu.top/dictionaries/asr_dictionary_manifest.json"


@dataclass
class CorrectionRule:
    replacement: str
    patterns: list[str]
    mode: str = "substring"     # substring | exact | word
    languages: list[str] = None
    case_sensitive: bool = False

    def __post_init__(self):
        if self.languages is None:
            self.languages = ["*"]


class DictionaryCorrector:
    """Layered ASR text correction system."""

    def __init__(self, dictionaries_dir: Optional[Path] = None):
        self._dir = dictionaries_dir or DICTIONARIES_DIR
        self._rules: list[CorrectionRule] = []
        self._cache_key: str = ""
        self._loaded = False

    def load(self):
        """Load and merge all dictionary layers."""
        layers = []

        # Layer 1: Bundled
        bundled = self._dir / "asr_terms.base.json"
        if bundled.exists():
            layers.append(("bundled", bundled))

        # Layer 2: Official
        official = self._dir / "asr_terms.official.json"
        if official.exists():
            layers.append(("official", official))

        # Layer 3: User
        user = self._dir / "asr_terms.user.json"
        if user.exists():
            layers.append(("user", user))

        # Check cache
        new_key = self._make_cache_key(layers)
        if new_key == self._cache_key and self._loaded:
            return

        # Load and merge
        merged = {}
        for name, path in layers:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entries = data.get("rules", data.get("terms", []))
                for entry in entries:
                    for pattern in entry.get("patterns", []):
                        key = pattern.lower() if not entry.get("case_sensitive", False) else pattern
                        merged[key] = CorrectionRule(
                            replacement=entry.get("replacement", ""),
                            patterns=entry.get("patterns", []),
                            mode=entry.get("mode", "substring"),
                            languages=entry.get("languages", ["*"]),
                            case_sensitive=entry.get("case_sensitive", False),
                        )
                logger.debug(f"Dictionary layer '{name}': {len(entries)} entries")
            except Exception as e:
                logger.warning(f"Failed to load dictionary layer '{name}': {e}")

        # Sort rules: exact > word > substring, then by pattern length (longer first)
        mode_order = {"exact": 0, "word": 1, "substring": 2}
        self._rules = sorted(
            merged.values(),
            key=lambda r: (mode_order.get(r.mode, 2), -max(len(p) for p in r.patterns))
        )
        self._cache_key = new_key
        self._loaded = True
        logger.info(f"Dictionary loaded: {len(self._rules)} rules from {len(layers)} layers")

    def correct(self, text: str, language: str = "*") -> str:
        """Apply dictionary corrections to ASR text."""
        if not self._loaded:
            self.load()
        if not self._rules:
            return text

        result = text
        for rule in self._rules:
            # Check language filter
            if rule.languages and "*" not in rule.languages and language not in rule.languages:
                continue

            for pattern in rule.patterns:
                if rule.mode == "exact":
                    if rule.case_sensitive:
                        if result == pattern:
                            result = rule.replacement
                    else:
                        if result.lower() == pattern.lower():
                            result = rule.replacement

                elif rule.mode == "word":
                    flags = 0 if rule.case_sensitive else re.IGNORECASE
                    escaped = re.escape(pattern)
                    result = re.sub(rf'\b{escaped}\b', rule.replacement, result, flags=flags)

                elif rule.mode == "substring":
                    if rule.case_sensitive:
                        result = result.replace(pattern, rule.replacement)
                    else:
                        result = re.sub(re.escape(pattern), rule.replacement, result, flags=re.IGNORECASE)

        return result

    def add_user_rule(self, replacement: str, patterns: list[str],
                      mode: str = "substring", languages: list[str] = None):
        """Add a user correction rule."""
        user_path = self._dir / "asr_terms.user.json"
        self._dir.mkdir(parents=True, exist_ok=True)

        # Load existing
        data = {"rules": []}
        if user_path.exists():
            try:
                with open(user_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        # Add new rule
        data["rules"].append({
            "replacement": replacement,
            "patterns": patterns,
            "mode": mode,
            "languages": languages or ["*"],
            "case_sensitive": False,
        })

        # Save
        with open(user_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Reload
        self._cache_key = ""
        self._loaded = False
        self.load()

    @staticmethod
    def _make_cache_key(layers: list) -> str:
        parts = []
        for name, path in layers:
            mtime = path.stat().st_mtime if path.exists() else 0
            parts.append(f"{name}:{mtime}")
        return hashlib.md5("|".join(parts).encode()).hexdigest()

    @staticmethod
    def download_official_dictionary() -> bool:
        """Download the official dictionary from 78hejiu.top."""
        try:
            import urllib.request
            DICTIONARIES_DIR.mkdir(parents=True, exist_ok=True)

            # Download manifest
            manifest_url = MANIFEST_URL
            with urllib.request.urlopen(manifest_url, timeout=10) as resp:
                manifest = json.loads(resp.read().decode("utf-8"))

            dict_url = manifest.get("url", manifest.get("dictionary_url", ""))
            if not dict_url:
                logger.error("Invalid dictionary manifest")
                return False

            # Download dictionary
            target = DICTIONARIES_DIR / "asr_terms.official.json"
            with urllib.request.urlopen(dict_url, timeout=30) as resp:
                data = resp.read()

            # Verify checksum if provided
            expected_hash = manifest.get("sha256", "")
            if expected_hash:
                actual_hash = hashlib.sha256(data).hexdigest()
                if actual_hash != expected_hash:
                    logger.error("Dictionary checksum mismatch")
                    return False

            with open(target, "wb") as f:
                f.write(data)

            logger.info(f"Official dictionary downloaded: {len(data)} bytes")
            return True
        except Exception as e:
            logger.error(f"Dictionary download failed: {e}")
            return False
