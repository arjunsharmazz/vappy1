"""Single source of settings: config/settings.toml + optional config/.env + LIVING_* overrides.

Nothing here ever raises on a bad config: invalid values are logged and replaced by
defaults so the frame still boots (important on an unattended Raspberry Pi).
"""
from contextvars import ContextVar
from copy import deepcopy
from functools import lru_cache
import logging
import os
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("settings")

DEFAULTS = {
    "device": {"profile": "auto"},
    "logging": {"level": "INFO"},
    "persona": {"name": "Living Avatar", "speaking_style": "friendly, natural and concise",
                "reply_language": "english", "gender": "female"},
    "stt": {"model_path": "", "compute_type": "int8",
            "threads": 0, "language": "hi", "beam_size": 3, "hint_words": "", "log_transcripts": False,
            "min_confidence": -0.8, "min_confidence_online": -1.8, "provider": "auto", "online_model": ""},
    "llm": {"enabled": True, "executable": "", "model_path": ".tools/models/Qwen3-0.6B-Q8_0.gguf",
            "port": 8091, "threads": 0, "context": 0, "temperature": 0.3,
            "max_tokens_short": 100, "max_tokens_normal": 220, "idle_unload_seconds": 300,
            "local_fallback": False},
    "tts": {"provider": "auto", "rate_wpm": 175, "voice": "hi_IN-priyamvada-medium", "speed": 1.0,
            "edge_voice": "", "edge_rate": "+0%", "edge_pitch": "+0Hz", "edge_timeout_seconds": 8},
    "online_ai": {"provider": "gemini", "model": "", "fallback_models": "", "base_url": "", "thinking": "",
                  "temperature": 0.8, "first_word_seconds": 8, "max_tokens": 2048},
    "vision": {"enabled": True, "camera_index": 0, "width": 320, "height": 240, "fps": 15, "mirror": True,
               "preview": True, "analysis": True, "analysis_fps": 4.0, "react_to_feelings": True},
    "conversation": {"hands_free": False, "canned_replies": True, "replies_file": "config/replies.json",
                     "end_silence_ms": 800, "allow_interrupt": False, "greet_on_arrival": True,
                     "listen_only_when_present": False, "start_on_load": True, "ask_name_on_start": True,
                     "canned_replies_when_online": False},
    "neural": {"enabled": True},
    "news": {"enabled": True, "feed_url": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
             "feed_url_hi": "https://news.google.com/rss?hl=hi&gl=IN&ceid=IN:hi",
             "max_items": 3, "timeout_seconds": 4, "cache_minutes": 30},
}

CHOICES = {
    ("device", "profile"): {"auto", "pc", "pi4", "pi5"},
    ("logging", "level"): {"DEBUG", "INFO", "WARNING", "ERROR"},
    ("stt", "language"): {"auto", "en", "hi"},
    ("stt", "provider"): {"auto", "local"},
    ("tts", "provider"): {"auto", "edge", "sapi", "piper"},
    ("online_ai", "provider"): {"gemini", "groq", "openai", "none"},
    ("online_ai", "thinking"): {"", "none", "minimal", "low", "medium", "high"},
    ("persona", "gender"): {"female", "male"},
}

# Whisper confidence is a log-probability, so this threshold is naturally negative.
NEGATIVE_OK = {("stt", "min_confidence"), ("stt", "min_confidence_online")}

# Older deployments configured these through environment variables; keep them working.
ENV_OVERRIDES = {
    "LIVING_STT_MODEL": ("stt", "model_path"),
    "LIVING_LLM_MODEL": ("llm", "model_path"),
    "LIVING_LLM_EXECUTABLE": ("llm", "executable"),
    "LIVING_AVATAR_NAME": ("persona", "name"),
    "LIVING_SPEAKING_STYLE": ("persona", "speaking_style"),
}


def load_env_file(path: Path):
    """Minimal KEY=VALUE reader for secrets. Existing environment variables win."""
    if not path.is_file():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            log.warning("Ignoring malformed line %d in %s", number, path.name)
            continue
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def raspberry_pi_model() -> str:
    """'pi5', 'pi4' (any older Pi) or '' when not running on a Raspberry Pi."""
    try:
        model = Path("/proc/device-tree/model").read_text(errors="ignore").lower()
    except OSError:
        return ""
    if "raspberry pi" not in model:
        return ""
    return "pi5" if "raspberry pi 5" in model else "pi4"


def detect_raspberry_pi() -> bool:
    return bool(raspberry_pi_model())


def _validated(raw: dict) -> dict:
    result = deepcopy(DEFAULTS)
    for section, values in raw.items():
        if section not in DEFAULTS or not isinstance(values, dict):
            log.warning("Unknown config section [%s] ignored", section)
            continue
        for key, value in values.items():
            if key not in DEFAULTS[section]:
                log.warning("Unknown config key %s.%s ignored", section, key)
                continue
            default = DEFAULTS[section][key]
            if isinstance(default, float) and isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            if type(value) is not type(default):
                log.warning("Config %s.%s must be %s; using default %r", section, key, type(default).__name__, default)
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0 \
                    and (section, key) not in NEGATIVE_OK:
                log.warning("Config %s.%s cannot be negative; using default %r", section, key, default)
                continue
            allowed = CHOICES.get((section, key))
            if allowed and value not in allowed:
                log.warning("Config %s.%s must be one of %s; using default %r", section, key, sorted(allowed), default)
                continue
            result[section][key] = value
    return result


def resolve_profile(raw: dict) -> str:
    profile = (raw.get("device") or {}).get("profile", "auto")
    if profile not in CHOICES[("device", "profile")]:
        profile = "auto"
    return (raspberry_pi_model() or "pc") if profile == "auto" else profile


def _apply_pi_overrides(raw: dict) -> dict:
    """settings.toml [pi.<section>] values replace the normal ones on a Raspberry Pi, so one
    settings file serves both the laptop and the Pi (lower camera load, no neural engine…)."""
    overrides = raw.pop("pi", None)
    if not isinstance(overrides, dict) or resolve_profile(raw) not in ("pi4", "pi5"):
        return raw
    merged = {k: dict(v) if isinstance(v, dict) else v for k, v in raw.items()}
    for section, values in overrides.items():
        if isinstance(values, dict):
            merged.setdefault(section, {}).update(values)
    return merged


def _apply_profile(s: dict):
    profile = s["device"]["profile"]
    if profile == "auto":
        profile = raspberry_pi_model() or "pc"
    s["device"]["resolved_profile"] = profile
    cores = os.cpu_count() or 4
    on_pi = profile in ("pi4", "pi5")
    # On a Pi, leave one core for the browser/renderer so the face never freezes.
    threads = max(1, min(3, cores - 1)) if on_pi else max(1, min(4, cores))
    for section in ("stt", "llm"):
        if not s[section]["threads"]:
            s[section]["threads"] = threads
    if not s["llm"]["context"]:
        s["llm"]["context"] = 2048 if on_pi else 4096


def _resolve_paths(s: dict):
    def resolve(value):
        path = Path(value)
        return path if path.is_absolute() else ROOT / path
    if not s["stt"]["model_path"]:
        # Whisper base understands Hindi/Hinglish far better than tiny but is ~2x slower:
        # fine on a PC (~2-4 s per sentence), too slow on a Raspberry Pi 4, which keeps tiny.
        models = ROOT / ".tools" / "models"
        base = models / "faster-whisper-base"
        use_base = s["device"]["resolved_profile"] not in ("pi4", "pi5") and (base / "model.bin").is_file()
        s["stt"]["model_path"] = str(base if use_base else models / "faster-whisper-tiny")
    s["stt"]["model_path"] = resolve(s["stt"]["model_path"])
    s["llm"]["model_path"] = resolve(s["llm"]["model_path"])
    exe = s["llm"]["executable"]
    if exe:
        s["llm"]["executable"] = resolve(exe)
    else:
        name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
        s["llm"]["executable"] = ROOT / ".tools" / "llama-cpp" / name


def load_settings(path: Path | None = None) -> dict:
    path = Path(path or os.environ.get("LIVING_CONFIG") or ROOT / "config" / "settings.toml")
    load_env_file(ROOT / "config" / ".env")
    raw = {}
    if path.is_file():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            log.error("Could not read %s (%s); using built-in defaults", path, error)
    else:
        log.warning("Config file %s not found; using built-in defaults", path)
    s = _validated(_apply_pi_overrides(raw))
    for env, (section, key) in ENV_OVERRIDES.items():
        if os.environ.get(env):
            s[section][key] = os.environ[env]
    _apply_profile(s)
    _resolve_paths(s)
    s["source"] = str(path) if raw else "defaults"
    return s


@lru_cache(maxsize=1)
def get_settings() -> dict:
    return load_settings()


# The avatar being served right now may be a man or a woman (detected from its photo, or chosen
# by the person); voice and Hindi verb forms follow it. Set per request; settings are the default.
current_gender: ContextVar = ContextVar("current_gender", default=None)


def persona_gender() -> str:
    return current_gender.get() or get_settings()["persona"]["gender"]


ONLINE_KEYS = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}


def _online_key(s: dict) -> str:
    """API key for the online brain, from config/.env or the environment ('' = not configured)."""
    name = ONLINE_KEYS.get(s["online_ai"]["provider"])
    return os.environ.get(name, "").strip() if name else ""


def online_key() -> str:
    return _online_key(get_settings())


def public_settings() -> dict:
    """Safe subset for the browser: no filesystem paths, no secrets."""
    s = get_settings()
    return {
        "device_profile": s["device"]["resolved_profile"],
        "persona": {"name": s["persona"]["name"], "reply_language": s["persona"]["reply_language"]},
        "stt": {"language": s["stt"]["language"]},
        "llm": {"enabled": s["llm"]["enabled"]},
        "brain": "online" if _online_key(s) else "local",
        "tts": {"provider": s["tts"]["provider"]},
        "vision": dict(s["vision"]),
        "neural": {"enabled": s["neural"]["enabled"]},
        # The face is drawn at 30 fps on a Raspberry Pi (less heat), 60 fps on a PC.
        "render_fps": 30 if s["device"]["resolved_profile"] in ("pi4", "pi5") else 60,
        "conversation": {key: value for key, value in s["conversation"].items() if key != "replies_file"},
    }
