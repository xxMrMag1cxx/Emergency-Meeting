"""
Everything to do with the Terminal window:

  - colors (the log's labels, the boxes' titles, the banner at the top)
  - the boxes with ===== around them
  - the questions the first time the server starts (language and name)
  - the steps while the server starts (1/5 Plugins ... 5/5 HTTPS)
  - commands you type in the window, for example /help

The colors are ANSI codes that Terminal on the Mac understands. They are
turned off when the output doesn't go to a real window (for example to a
file), when the environment variable NO_COLOR is set, or with
"colors": false in config.json.

Text in the terminal is shown in the language chosen in config.json, see
i18n.py.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from . import i18n
from .i18n import tr

log = logging.getLogger("console")

LINE = "=" * 64

# --- Colors -------------------------------------------------------------------
#
# Two sets of colors: bright ones for a dark background and darker ones for
# a white background (otherwise yellow, for example, is hard to see). "auto"
# checks whether the Mac is in dark mode, because Terminal follows that.

# The names of the colors used in the code
LIGHT_BLUE = "em"  # "Emergency Meeting"
PURPLE = "name"  # the server's name
RED = "title"  # the boxes' titles
ERROR = "error"
GREEN = "ok"
GRAY = "time"
DARK_GRAY = "line"
PLAYING = "game"

PALETTES: Dict[str, Dict[str, int]] = {
    "dark": {
        "em": 117, "name": 141, "title": 203, "error": 203, "warn": 229, "ok": 120,
        "time": 244, "line": 240, "text": 252,
        "server": 208, "game": 214, "playit": 226, "ngrok": 81, "tunnel": 75,
        "http": 120, "bot": 49, "plugin": 177, "console": 117,
        "config": 252, "udp": 250, "lobby": 250,
    },
    "light": {
        "em": 32, "name": 98, "title": 160, "error": 160, "warn": 130, "ok": 28,
        "time": 244, "line": 250, "text": 236,
        "server": 166, "game": 130, "playit": 136, "ngrok": 31, "tunnel": 25,
        "http": 28, "bot": 29, "plugin": 127, "console": 32,
        "config": 238, "udp": 240, "lobby": 240,
    },
}

# The log's labels in Swedish (the others are the same in both languages)
SWEDISH_LABELS = {"game": "spel", "console": "konsol"}

_enabled = False
_palette = PALETTES["dark"]
_print_lock = threading.RLock()  # so that boxes and log lines don't get mixed up


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
    """Colors only if they are turned on and the output goes to a real Terminal window."""
    global _enabled, _palette
    _enabled = bool(wanted) and "NO_COLOR" not in os.environ and sys.stdout.isatty()
    if theme not in PALETTES:
        theme = "dark" if sys.platform != "darwin" or _mac_dark_mode() else "light"
    _palette = PALETTES[theme]


def paint(text: str, color, bold: bool = False) -> str:
    """Colors the text. color is a name from PALETTES (for example "title") or a color number."""
    if not _enabled:
        return text
    number = _palette.get(color, 252) if isinstance(color, str) else color
    return f"\x1b[{'1;' if bold else ''}38;5;{number}m{text}\x1b[0m"


def category_color(name: str) -> str:
    base = name.split(".", 1)[0]
    return name if name in _palette else (base if base in _palette else "text")


def _translated_message(record: logging.LogRecord) -> str:
    """The log message in the terminal's language (looked up by its format string)."""
    if not isinstance(record.msg, str):
        return record.getMessage()
    message = i18n.translate(record.msg)
    if record.args:
        try:
            message = message % record.args
        except (TypeError, ValueError):
            return record.getMessage()  # a broken translation: show the English text
    return message


class ColorFormatter(logging.Formatter):
    """Log lines like '15:01:12  game    Blobi created the game ...', with colors."""

    def __init__(self) -> None:
        super().__init__(datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        time_text = self.formatTime(record, self.datefmt)
        label = record.name
        if i18n.current() == "sv":
            label = SWEDISH_LABELS.get(label, label)
        name = f"{label:<6}"
        message = _translated_message(record)
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
    """Writes log lines without them ending up in the middle of a box being written."""

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


# --- Boxes and banner ---------------------------------------------------------


def print_box(title: str, lines: List[str]) -> None:
    """A box with ===== above and below, and the title in red."""
    with _print_lock:
        print()
        print(paint(LINE, DARK_GRAY))
        print(f"  {paint(title, RED, bold=True)}")
        print()
        for line in lines:
            print(f"  {line}" if line else "")
        print(paint(LINE, DARK_GRAY), flush=True)


def full_name(server_name: str, colored: bool = True) -> str:
    """'Emergency Meeting - Blobi's server' (or just 'Emergency Meeting')."""
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
    """Hold the lock to write several things in a row without log lines in between."""
    return _print_lock


def success(text: str) -> None:
    with _print_lock:
        print(f"  {paint(text, GREEN, bold=True)}", flush=True)


def say(text: str = "") -> None:
    with _print_lock:
        print(f"  {text}" if text else "", flush=True)


# --- The steps while the server starts ---------------------------------------

STEP_MARKS = {"ok": ("✓", "ok"), "warn": ("!", "warn"), "failed": ("✗", "error"), "off": ("–", "time")}


def print_step(number: int, total: int, title: str) -> None:
    """'  4/5  playit.gg' when a step starts."""
    with _print_lock:
        print(f"  {paint(f'{number}/{total}', GRAY)}  {paint(title, LIGHT_BLUE, bold=True)}", flush=True)


def print_step_result(kind: str, text: str) -> None:
    """'       ✓ malls-vel.tun.ply.gg:45218' when a step is done. kind: ok, warn, failed or off."""
    mark, color = STEP_MARKS.get(kind, STEP_MARKS["ok"])
    with _print_lock:
        print(f"       {paint(mark, color, bold=True)} {text}", flush=True)


def print_step_detail(text: str) -> None:
    with _print_lock:
        print(f"         {text}", flush=True)


def print_setup_step(number: int, total: int) -> None:
    """'  Setup 3 of 4' above each part of the first-start guide."""
    with _print_lock:
        print()
        print(f"  {paint(tr('Setup {number} of {total}', number=number, total=total), GRAY)}", end="", flush=True)


def wait_for_enter(seconds: float) -> bool:
    """
    Waits at most `seconds`. Returns True if Enter was pressed meanwhile (for
    "press Enter to skip" in the first-start guide). Without a terminal it just waits.
    """
    if sys.stdin is None:
        time.sleep(seconds)
        return False
    try:
        import select
        ready, _, _ = select.select([sys.stdin], [], [], seconds)
    except (OSError, ValueError, TypeError):
        time.sleep(seconds)
        return False
    if not ready:
        return False
    if sys.stdin.readline() == "":  # no terminal (the input has ended)
        time.sleep(seconds)
        return False
    return True


# --- The language (asked the first time) ------------------------------------------

def choose_language(default: str = "en") -> str:
    """
    Lets you pick the language with the arrow keys:

        Select server language:

            English
            Swedish     <-----

    Returns 'en' or 'sv'. Without a real terminal the default is used.
    """
    options = list(i18n.LANGUAGES.items())  # [("English", "en"), ("Swedish", "sv")]
    codes = [code for _, code in options]
    selected = codes.index(default) if default in codes else 0
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
    except Exception:
        return codes[selected]

    width = max(len(name) for name, _ in options) + 5

    def draw() -> None:
        for index, (name, _) in enumerate(options):
            sys.stdout.write("\x1b[2K")  # clear the line
            if index == selected:
                sys.stdout.write(f"    {paint(name.ljust(width), PURPLE, bold=True)}{paint('<-----', PURPLE, bold=True)}\n")
            else:
                sys.stdout.write(f"    {name}\n")
        sys.stdout.flush()

    print()
    print(paint(LINE, DARK_GRAY))
    print(f"  {paint('Select server language:', PURPLE, bold=True)}")
    print()
    draw()
    print()
    print(f"  {paint('Use the arrow keys and press Enter.', GRAY)}")
    print(paint(LINE, DARK_GRAY), flush=True)
    sys.stdout.write("\x1b[?25l")  # hide the cursor while choosing
    sys.stdout.flush()

    try:
        tty.setcbreak(fd)
        while True:
            key = os.read(fd, 8)
            if not key:
                break
            if key in (b"\r", b"\n"):
                break
            if key in (b"\x1b[A", b"\x1bOA", b"k", b"w") and selected > 0:
                selected -= 1
            elif key in (b"\x1b[B", b"\x1bOB", b"j", b"s") and selected < len(options) - 1:
                selected += 1
            elif key in (b"1", b"2"):
                selected = min(int(key) - 1, len(options) - 1)
            else:
                continue
            # Up past the three lines below the choices, draw them again, and back down
            sys.stdout.write(f"\x1b[{len(options) + 3}F")
            draw()
            sys.stdout.write("\x1b[3E")
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h")  # show the cursor again
        sys.stdout.flush()
    return codes[selected]


# --- The server's name ---------------------------------------------------------

MAX_NAME_LENGTH = 32


def clean_name(text: str) -> Tuple[str, str]:
    """Returns (name, error). The error is empty if the name is okay."""
    name = " ".join(text.split())  # no double spaces or tabs
    if not name:
        return "", tr("The name can't be empty.")
    if len(name) > MAX_NAME_LENGTH:
        return "", tr("The name can be at most {count} characters.", count=MAX_NAME_LENGTH)
    if any(ord(c) < 32 for c in name):
        return "", tr("The name can't contain special control characters.")
    return name, ""


def ask_server_name(default: str) -> str:
    """Asks for the server's name (the first time the server starts)."""
    print()
    print(paint(LINE, DARK_GRAY))
    print(f"  {paint(tr('NAME YOUR SERVER'), RED, bold=True)}")
    print()
    print(f"  {tr('The name shows up as the region in Among Us and on the join page.')}")
    print(f"  {tr('Press Enter to keep {name}.', name=paint(default, PURPLE, bold=True))}")
    print(paint(LINE, DARK_GRAY), flush=True)
    while True:
        try:
            text = input(f"  {tr('Input server name (you can change the name later):')} ")
        except EOFError:
            return default
        if not text.strip():
            say(tr("Keeping the name {name}.", name=paint(default, PURPLE, bold=True)))
            return default
        name, problem = clean_name(text)
        if problem:
            say(paint(problem, ERROR))
            continue
        success(tr("Name updated!"))
        return name


# --- Commands ---------------------------------------------------------------------

Command = Tuple[str, str, Callable[[str], None]]  # (usage, explanation, function)


class Console:
    """
    Reads what you type in the Terminal window while the server runs.

    Lines that start with / are commands. If something in the server is
    waiting for an answer (for example the ngrok key), it gets the next line
    instead.
    """

    def __init__(self) -> None:
        self.commands: Dict[str, Command] = {}
        self._waiting: Optional["_Request"] = None
        self._lock = threading.Lock()
        self.add("help", "/help", "Show this list", self._help)

    def add(self, name: str, usage: str, text: str, action: Callable[[str], None]) -> None:
        """text is the explanation in English; it is translated when /help shows it."""
        self.commands[name] = (usage, text, action)

    def start(self) -> None:
        threading.Thread(target=self._read_loop, name="console", daemon=True).start()

    # --- For other parts of the server -----------------------------------

    def ask(self, hidden: bool = False) -> Optional[str]:
        """Waits for the next line typed (without showing it if hidden). None = no terminal."""
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

    # --- Reading -------------------------------------------------------------

    def _read_loop(self) -> None:
        while True:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                return
            if line == "":  # the window was closed
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
        help_command = paint("/help", LIGHT_BLUE, bold=True)
        if not text.startswith("/"):
            say(tr("Commands start with /. Use {help} to get a list of useful commands.", help=help_command))
            return
        name, _, argument = text[1:].partition(" ")
        command = self.commands.get(name.lower())
        if command is None:
            say(paint(tr("Unknown command /{name}.", name=name), ERROR) + " "
                + tr("Use {help} to see them all.", help=help_command))
            return
        try:
            command[2](argument.strip())
        except Exception:
            log.exception("The command /%s failed", name)

    def _help(self, _argument: str) -> None:
        usages = [tr(usage) for usage, _, _ in self.commands.values()]
        width = max(len(usage) for usage in usages)
        lines = []
        for usage, (_, text, _) in zip(usages, self.commands.values()):
            lines.append(f"{paint(usage.ljust(width), LIGHT_BLUE, bold=True)}   {tr(text)}")
        print_box(tr("COMMANDS"), lines)


class _Request:
    def __init__(self, hidden: bool):
        self.hidden = hidden
        self.line: Optional[str] = None
        self.done = threading.Event()


_saved_echo = None


def _echo(on: bool) -> None:
    """Turns showing what you type off/on (like for a password)."""
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
    """Runs when the server stops, so that you always see what you type afterwards."""
    _echo(True)
