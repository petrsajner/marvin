"""English-first UI localization with optional external language catalogs.

Python surfaces and the React workspace share the same message catalog. Missing
or damaged translations fall back to English without preventing application startup.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_current = "en"


def _load_catalog(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


_CATALOG = _load_catalog(Path(__file__).parent / "locales" / "cs.json")
_CS = {key: value for key, value in _CATALOG.get("messages", {}).items()
       if isinstance(key, str) and isinstance(value, str)} if isinstance(_CATALOG.get("messages"), dict) else {}
_native_name = _CATALOG.get("native_name")
LANGUAGES = {"en": "English", "cs": _native_name if isinstance(_native_name, str) and _native_name else "Czech"}
_ALIASES = {"en": "en", "english": "en", "eng": "en",
            "cs": "cs", "cz": "cs", "cze": "cs", "czech": "cs"}
_aliases = _CATALOG.get("aliases")
if isinstance(_aliases, list):
    _ALIASES.update({alias: "cs" for alias in _aliases if isinstance(alias, str)})


def locale_data(key: str, default: Any = None) -> Any:
    """Return localized compatibility data, independent of the active UI language."""
    value = _CATALOG.get(key, default)
    return value if default is None or isinstance(value, type(default)) else default


def input_pattern(key: str) -> str:
    """Ignore damaged optional input patterns while retaining English behavior."""
    value = locale_data(key, "")
    try:
        re.compile(value, re.IGNORECASE)
        return value
    except re.error:
        return ""


def normalize(value) -> str:
    return _ALIASES.get(str(value or "").strip().lower(), "en")


def set_language(value) -> str:
    global _current
    with _lock:
        _current = normalize(value)
    return _current


def get_language() -> str:
    return _current


def language_choices() -> list[tuple[str, str]]:
    return [(label, code) for code, label in LANGUAGES.items()]


def translate(text: str, language: str = "en", **fmt) -> str:
    translated = _CS.get(text, text) if normalize(language) == "cs" else text
    if not fmt:
        return translated
    try:
        return translated.format(**fmt)
    except (KeyError, ValueError, IndexError):
        return text.format(**fmt)


def t(text: str, **fmt) -> str:
    return translate(text, _current, **fmt)


def detect_language(root: Path) -> str | None:
    """Prefer current workspace settings, then legacy settings and installer choice."""
    runtime = Path(root) / "runtime"
    for name in ("workspace-settings.json", "webui-state.json"):
        saved = _load_catalog(runtime / name)
        if saved.get("language"):
            return normalize(saved["language"])
    try:
        raw = (runtime / "ui-language.txt").read_text(encoding="utf-8").strip()
        if raw:
            return normalize(raw)
    except (OSError, ValueError):
        pass
    return None
