"""
The commands /settings and /setting (a bit like the console in CS2):

    /settings                          shows everything in config.json
    /setting debug                     Current value of debug = false
    /setting debug = true              changes it in config.json

A change is saved in config.json right away, but the server keeps running
with the old value until it restarts (/reboot). That way nothing changes
under the feet of a game that is going on.
"""

from __future__ import annotations

import dataclasses
import ipaddress
import json
from typing import Optional, Tuple

from . import i18n
from .config import Config, change_setting, is_pending, saved_value, setting_names
from .i18n import tr
from .terminal import ERROR, GRAY, GREEN, LIGHT_BLUE, Console, clean_name, paint, print_box, say, success

TRUE_WORDS = ("true", "yes", "on", "1")
FALSE_WORDS = ("false", "no", "off", "0")

# Settings that only take some words
CHOICES = {
    "color_theme": ("auto", "dark", "light"),
}


def show(value: object) -> str:
    """A value written like in config.json: true, 22023, "Emergency Meeting"."""
    return json.dumps(value, ensure_ascii=False)


def default_value(name: str) -> object:
    for field in dataclasses.fields(Config):
        if field.name == name:
            return field.default
    raise KeyError(name)


def parse_value(name: str, text: str) -> Tuple[object, Optional[str]]:
    """Turns what was typed into a value for the setting. Returns (value, problem)."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    kind = type(default_value(name))

    if kind is bool:
        word = text.lower()
        if word in TRUE_WORDS:
            return True, None
        if word in FALSE_WORDS:
            return False, None
        return None, tr("{name} must be true or false.", name=name)

    if kind is int:
        try:
            number = int(text)
        except ValueError:
            return None, tr("{name} must be a whole number.", name=name)
        if name == "port" and not 1 <= number <= 65535:
            return None, tr("The port must be between 1 and 65535.")
        if number < 0:
            return None, tr("{name} can't be negative.", name=name)
        return number, None

    # Text
    if name == "server_name":
        clean, problem = clean_name(text)
        return (clean, None) if not problem else (None, problem)
    if name == "language":
        if text.lower() not in ("en", "sv", "english", "swedish", "engelska", "svenska", "se"):
            return None, tr("Unknown language {language}.", language=text) + f" ({' / '.join(i18n.LANGUAGES)})"
        return i18n.language_name(i18n.normalize(text)), None
    if name in CHOICES:
        word = text.lower()
        if word not in CHOICES[name]:
            return None, tr("{name} must be one of: {choices}.", name=name, choices=", ".join(CHOICES[name]))
        return word, None
    if name in ("listen_ip", "public_ip"):
        if name == "public_ip" and text.lower() == "auto":
            return "auto", None
        try:
            ipaddress.ip_address(text)
        except ValueError:
            if name == "public_ip":
                return None, tr("{name} must be auto or an address like {example}.", name=name, example="192.168.1.23")
            return None, tr("{name} must be an address like {example}.", name=name, example="0.0.0.0")
        return text, None
    if not text:
        if name == "page_password":
            return "", None  # no password
        return None, tr("{name} can't be empty.", name=name)
    return text, None


def add_settings_commands(console: Console, config: Config) -> None:
    def settings(_argument: str) -> None:
        names = setting_names()
        width = max(len(name) for name in names)
        lines = []
        for name in names:
            line = f"{paint(name.ljust(width), LIGHT_BLUE, bold=True)}   {show(saved_value(config, name))}"
            if is_pending(name):
                line += "   " + paint(tr("(after a reboot)"), GRAY)
            lines.append(line)
        lines += ["", tr("Change a setting with {command}.",
                         command=paint(tr("/setting <name> = <value>"), LIGHT_BLUE, bold=True))]
        print_box(tr("SETTINGS"), lines)

    def setting(argument: str) -> None:
        if "=" in argument:
            name, _, value_text = argument.partition("=")
            has_value = True
        else:
            name, _, value_text = argument.strip().partition(" ")
            has_value = bool(value_text.strip())
        name = name.strip().lower()
        if not name:
            say(tr("Usage: {command}", command=paint(tr("/setting <name> = <value>"), LIGHT_BLUE, bold=True)))
            return
        if name not in setting_names():
            say(paint(tr("Unknown setting {name}.", name=name), ERROR) + " "
                + tr("Use {settings} to see them all.", settings=paint("/settings", LIGHT_BLUE, bold=True)))
            return
        if not has_value:
            say(tr("Current value of {name} = {value}", name=name, value=show(saved_value(config, name))))
            return
        value, problem = parse_value(name, value_text)
        if problem:
            say(paint(problem, ERROR))
            return
        if value == saved_value(config, name):
            say(tr("{name} is already {value}.", name=name, value=show(value)))
            return
        if not change_setting(config, name, value):
            say(paint(tr("Could not save config.json, nothing was changed."), ERROR))
            return
        success(tr("Settings updated! Reboot the server to play with updated settings."))
        say(f"{paint(name, LIGHT_BLUE, bold=True)} = {paint(show(value), GREEN)}")

    console.add("settings", "/settings", "Prints out all server settings", settings)
    console.add("setting", "/setting <name> = <value>", "Changes a setting's value", setting)
