"""
Translations for the server's terminal window (the one start.command opens).

Everything in Emergency Meeting is written in English. If "language" in
config.json is "Swedish", the terminal shows Swedish instead. Only the
terminal is translated: the join page, files, reports and chat messages in
the game are always in English.

Translations live in server/locales/<code>.json, for example sv.json:

    {"Server is online!": "Servern är igång!", ...}

How text gets translated:

  - Log messages are looked up by their format string, so
        log.info("%s joined %s", name, code)
    needs "%s joined %s" in the file. The %s placeholders must be the same
    (and in the same order) in both languages.
  - Other text uses tr():
        tr("The server is now called {name}.", name=name)
    Here the placeholders are {name} style.

Plugins can add their own translations, see plugins/README.md.
Run tools/check_translations.py to find text that has no translation yet.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

LOCALES_DIR = Path(__file__).resolve().parent / "locales"

# The languages you can choose in config.json: name -> code
LANGUAGES: Dict[str, str] = {"English": "en", "Swedish": "sv"}

# Other ways of writing the languages that are accepted in config.json
_ALIASES = {
    "en": "en", "english": "en", "engelska": "en",
    "sv": "sv", "swedish": "sv", "svenska": "sv", "se": "sv",
}

_current = "en"
_catalogs: Dict[str, Dict[str, str]] = {}


def normalize(value: object) -> str:
    """'Swedish', 'sv' or 'svenska' -> 'sv'. Anything unknown -> 'en'."""
    return _ALIASES.get(str(value or "").strip().lower(), "en")


def language_name(code: str) -> str:
    """'sv' -> 'Swedish'."""
    for name, value in LANGUAGES.items():
        if value == code:
            return name
    return "English"


def _catalog(code: str) -> Dict[str, str]:
    if code not in _catalogs:
        path = LOCALES_DIR / f"{code}.json"
        try:
            _catalogs[code] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            if code != "en":
                logging.getLogger("config").warning("Could not read the translations in %s: %s", path.name, error)
            _catalogs[code] = {}
    return _catalogs[code]


def set_language(value: object) -> str:
    """Chooses the terminal's language. Returns the code ('en' or 'sv')."""
    global _current
    _current = normalize(value)
    _catalog(_current)
    return _current


def current() -> str:
    return _current


def add_translations(code: str, texts: Dict[str, str]) -> None:
    """Adds translations, for example from a plugin: add_translations('sv', {...})."""
    _catalog(normalize(code)).update({str(k): str(v) for k, v in texts.items()})


def translate(text: str) -> str:
    """The text in the chosen language (or the text itself if there is no translation)."""
    if _current == "en":
        return text
    return _catalog(_current).get(text, text)


def tr(text: str, **values: object) -> str:
    """Translates text with {name} placeholders and fills them in."""
    translated = translate(text)
    if not values:
        return translated
    try:
        return translated.format(**values)
    except (KeyError, IndexError, ValueError):
        return text.format(**values)  # a broken translation: show the English text
