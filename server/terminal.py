"""
Allt som har med Terminal-fönstret att göra:

  - färger (loggens rubriker, rutornas titlar, bannern högst upp)
  - rutorna med ===== runt
  - frågan om serverns namn första gången
  - kommandon som man skriver i fönstret, t.ex. /help

Färgerna är ANSI-koder som Terminal på Macen förstår. De stängs av när
utskriften inte går till ett riktigt fönster (t.ex. till en fil), när
miljövariabeln NO_COLOR finns eller med "colors": false i config.json.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger("konsol")

LINE = "=" * 64

# --- Färger ------------------------------------------------------------------
#
# Två uppsättningar färger: ljusa för mörk bakgrund och mörkare för vit
# bakgrund (annars syns till exempel gult knappt). "auto" tittar på om
# Macen har mörkt läge, eftersom Terminal följer det.

# Namnen på färgerna som används i koden
LIGHT_BLUE = "em"  # "Emergency Meeting"
PURPLE = "name"  # serverns namn
RED = "title"  # rutornas titlar
ERROR = "error"
GREEN = "ok"
GRAY = "time"
DARK_GRAY = "line"
PLAYING = "spel"

PALETTES: Dict[str, Dict[str, int]] = {
    "dark": {
        "em": 117, "name": 141, "title": 203, "error": 203, "warn": 229, "ok": 120,
        "time": 244, "line": 240, "text": 252,
        "server": 208, "spel": 214, "playit": 226, "ngrok": 81, "tunnel": 75,
        "http": 120, "bot": 49, "plugin": 177, "konsol": 117,
        "config": 252, "udp": 250, "lobby": 250,
    },
    "light": {
        "em": 32, "name": 98, "title": 160, "error": 160, "warn": 130, "ok": 28,
        "time": 244, "line": 250, "text": 236,
        "server": 166, "spel": 130, "playit": 136, "ngrok": 31, "tunnel": 25,
        "http": 28, "bot": 29, "plugin": 127, "konsol": 32,
        "config": 238, "udp": 240, "lobby": 240,
    },
}

_enabled = False
_palette = PALETTES["dark"]
_print_lock = threading.RLock()  # så att rutor och loggrader inte blandas


def colors_enabled() -> bool:
    return _enabled


def _mac_dark_mode() -> bool:
    try:
        import subprocess
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, timeout=3
        )
        return "dark" in result.stdout.lower()
    except Exception:
        return True


def enable_colors(wanted: bool, theme: str = "auto") -> None:
    """Färger bara om de är påslagna och utskriften går till ett riktigt Terminal-fönster."""
    global _enabled, _palette
    _enabled = bool(wanted) and "NO_COLOR" not in os.environ and sys.stdout.isatty()
    if theme not in PALETTES:
        theme = "dark" if sys.platform != "darwin" or _mac_dark_mode() else "light"
    _palette = PALETTES[theme]


def paint(text: str, color, bold: bool = False) -> str:
    """Färgar texten. color är ett namn ur PALETTES (t.ex. "title") eller ett färgnummer."""
    if not _enabled:
        return text
    number = _palette.get(color, 252) if isinstance(color, str) else color
    return f"\x1b[{'1;' if bold else ''}38;5;{number}m{text}\x1b[0m"


def category_color(name: str) -> str:
    base = name.split(".", 1)[0]
    return name if name in _palette else (base if base in _palette else "text")


class ColorFormatter(logging.Formatter):
    """Loggrader som '15:01:12  spel    Blobi skapade spelet ...', med färger."""

    def __init__(self) -> None:
        super().__init__(datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        time_text = self.formatTime(record, self.datefmt)
        name = f"{record.name:<6}"
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        if not _enabled:
            return f"{time_text}  {name}  {message}"
        if record.levelno >= logging.ERROR:
            message = paint(message, ERROR)
        elif record.levelno >= logging.WARNING:
            message = paint(message, "warn")
        return f"{paint(time_text, GRAY)}  {paint(name, category_color(record.name), bold=True)}  {message}"


class _LockedHandler(logging.StreamHandler):
    """Skriver loggrader utan att de hamnar mitt i en ruta som skrivs samtidigt."""

    def emit(self, record: logging.LogRecord) -> None:
        with _print_lock:
            super().emit(record)


def setup_logging(debug: bool, colors: bool, theme: str = "auto") -> None:
    enable_colors(colors, theme)
    handler = _LockedHandler(sys.stdout)
    handler.setFormatter(ColorFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if debug else logging.INFO)


# --- Rutor och banner -------------------------------------------------------


def print_box(title: str, lines: List[str]) -> None:
    """En ruta med ===== ovanför och under, och titeln i rött."""
    with _print_lock:
        print()
        print(paint(LINE, DARK_GRAY))
        print(f"  {paint(title, RED, bold=True)}")
        print()
        for line in lines:
            print(f"  {line}" if line else "")
        print(paint(LINE, DARK_GRAY), flush=True)


def full_name(server_name: str, colored: bool = True) -> str:
    """'Emergency Meeting - Blobis server' (eller bara 'Emergency Meeting')."""
    em = paint("Emergency Meeting", LIGHT_BLUE, bold=True) if colored else "Emergency Meeting"
    if not server_name or server_name.strip().lower() == "emergency meeting":
        return em
    name = paint(server_name, PURPLE, bold=True) if colored else server_name
    return f"{em} - {name}"


def print_banner(server_name: str, version: str, lines: List[str]) -> None:
    with _print_lock:
        print(paint(LINE, DARK_GRAY))
        print(f"  {full_name(server_name)}  {paint(f'(version {version})', GRAY)}")
        print(paint(LINE, DARK_GRAY))
        for line in lines:
            print(f"  {line}")
        print(paint(LINE, DARK_GRAY), flush=True)


def output_lock() -> "threading.RLock":
    """Håll låset för att skriva flera saker i rad utan att loggrader kommer emellan."""
    return _print_lock


def success(text: str) -> None:
    with _print_lock:
        print(f"  {paint(text, GREEN, bold=True)}", flush=True)


def say(text: str = "") -> None:
    with _print_lock:
        print(f"  {text}" if text else "", flush=True)


# --- Serverns namn ------------------------------------------------------------

MAX_NAME_LENGTH = 32


def clean_name(text: str) -> Tuple[str, str]:
    """Returnerar (namn, felmeddelande). Felmeddelandet är tomt om namnet är okej."""
    name = " ".join(text.split())  # inga dubbla mellanslag eller tabbar
    if not name:
        return "", "The name can't be empty."
    if len(name) > MAX_NAME_LENGTH:
        return "", f"The name can be at most {MAX_NAME_LENGTH} characters."
    if any(ord(c) < 32 for c in name):
        return "", "The name can't contain special control characters."
    return name, ""


def ask_server_name(default: str) -> str:
    """Frågar efter serverns namn (första gången servern startar)."""
    print()
    print(paint(LINE, DARK_GRAY))
    print(f"  {paint('NAME YOUR SERVER', RED, bold=True)}")
    print()
    print(f"  The name shows up as the region in Among Us and on the join page.")
    print(f"  Press Enter to keep {paint(default, PURPLE, bold=True)}.")
    print(paint(LINE, DARK_GRAY), flush=True)
    while True:
        try:
            text = input("  Input server name (you can change the name later): ")
        except EOFError:
            return default
        if not text.strip():
            say(f"Keeping the name {paint(default, PURPLE, bold=True)}.")
            return default
        name, problem = clean_name(text)
        if problem:
            say(paint(problem, ERROR))
            continue
        success("Name updated!")
        return name


# --- Kommandon ----------------------------------------------------------------

Command = Tuple[str, str, Callable[[str], None]]  # (användning, förklaring, funktion)


class Console:
    """
    Läser det man skriver i Terminal-fönstret medan servern kör.

    Rader som börjar med / är kommandon. Om något i servern väntar på svar
    (t.ex. ngrok-nyckeln) får den nästa rad i stället.
    """

    def __init__(self) -> None:
        self.commands: Dict[str, Command] = {}
        self._waiting: Optional["_Request"] = None
        self._lock = threading.Lock()
        self.add("help", "/help", "Show this list", self._help)

    def add(self, name: str, usage: str, text: str, action: Callable[[str], None]) -> None:
        self.commands[name] = (usage, text, action)

    def start(self) -> None:
        threading.Thread(target=self._read_loop, name="konsol", daemon=True).start()

    # --- För andra delar av servern ------------------------------------

    def ask(self, hidden: bool = False) -> Optional[str]:
        """Väntar på nästa rad som skrivs (utan att den syns om hidden). None = ingen terminal."""
        request = _Request(hidden)
        with self._lock:
            self._waiting = request
        if hidden:
            _echo(False)
        try:
            request.done.wait()
        finally:
            if hidden:
                _echo(True)
            with self._lock:
                if self._waiting is request:
                    self._waiting = None
        return request.line

    # --- Läsningen --------------------------------------------------------

    def _read_loop(self) -> None:
        while True:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                return
            if line == "":  # fönstret stängt
                with self._lock:
                    waiting = self._waiting
                if waiting:
                    waiting.line = None
                    waiting.done.set()
                return
            text = line.strip()
            with self._lock:
                waiting = self._waiting
            if waiting is not None and not text.startswith("/"):
                waiting.line = text
                waiting.done.set()
                continue
            if text:
                self.run(text)

    def run(self, text: str) -> None:
        if not text.startswith("/"):
            say(f"Commands start with /. Use {paint('/help', LIGHT_BLUE, bold=True)} to get a list of useful commands.")
            return
        name, _, argument = text[1:].partition(" ")
        command = self.commands.get(name.lower())
        if command is None:
            say(paint(f"Unknown command /{name}.", ERROR) + f" Use {paint('/help', LIGHT_BLUE, bold=True)} to see them all.")
            return
        try:
            command[2](argument.strip())
        except Exception:
            log.exception("Kommandot /%s gick fel", name)

    def _help(self, _argument: str) -> None:
        width = max(len(usage) for usage, _, _ in self.commands.values())
        lines = []
        for usage, text, _ in self.commands.values():
            lines.append(f"{paint(usage.ljust(width), LIGHT_BLUE, bold=True)}   {text}")
        print_box("COMMANDS", lines)


class _Request:
    def __init__(self, hidden: bool):
        self.hidden = hidden
        self.line: Optional[str] = None
        self.done = threading.Event()


_saved_echo = None


def _echo(on: bool) -> None:
    """Slår av/på att det man skriver syns (som vid lösenord)."""
    global _saved_echo
    try:
        import termios
        fd = sys.stdin.fileno()
        if not on:
            _saved_echo = termios.tcgetattr(fd)
            settings = termios.tcgetattr(fd)
            settings[3] &= ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSADRAIN, settings)
        elif _saved_echo is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, _saved_echo)
            _saved_echo = None
    except Exception:
        pass


def restore_terminal() -> None:
    """Körs när servern stängs, så att man alltid ser vad man skriver efteråt."""
    _echo(True)
