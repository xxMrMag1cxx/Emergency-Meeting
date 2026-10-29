"""
Everything to do with the Terminal window:

  - colors (the log's labels, the boxes' titles, the banner at the top)
  - the boxes with ===== around them
  - the questions the first time the server starts (language and name)
  - the steps while the server starts (1/5 Plugins ... 5/5 HTTPS)
  - commands you type in the window, for example /help
  - the line at the bottom where you type them (new messages show up above it)

The colors are ANSI codes that Terminal on the Mac understands. They are
turned off when the output doesn't go to a real window (for example to a
file), when the environment variable NO_COLOR is set, or with
"colors": false in config.json.

Text in the terminal is shown in the language chosen in config.json, see
i18n.py.
"""

from __future__ import annotations

import atexit
import codecs
import collections
import logging
import os
import signal
import sys
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Tuple

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
    if not isinstance(sys.stdout, _Output):
        sys.stdout = _Output(sys.stdout)  # type: ignore[assignment]
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


def print_banner(server_name: str, version: str, lines: List[str], copyright_line: str = "") -> None:
    with _print_lock:
        print(paint(LINE, DARK_GRAY))
        print(f"  {full_name(server_name)}  {paint(f'(version {version})', GRAY)}")
        if copyright_line:
            print(f"  {paint(copyright_line, GRAY)}")
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


def print_setup_step(number: int, total: int, box_follows: bool = True) -> None:
    """'  Setup 3 of 4' above each part of the first-start guide (the box below starts the next line)."""
    with _print_lock:
        print()
        end = "" if box_follows else "\n"
        print(f"  {paint(tr('Setup {number} of {total}', number=number, total=total), GRAY)}", end=end, flush=True)


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
        pending = b""
        chosen = False
        while not chosen:
            data = os.read(fd, 64)
            if not data:
                break
            pending += data
            before = selected
            # Several keys can come at once (for example an arrow and Enter)
            while pending and not chosen:
                if pending[:1] == b"\x1b" and pending[1:2] in (b"[", b"O"):
                    if len(pending) < 3:
                        break  # the rest of the arrow key is on its way
                    key, pending = pending[:3], pending[3:]
                else:
                    key, pending = pending[:1], pending[1:]
                if key in (b"\r", b"\n"):
                    chosen = True
                elif key in (b"\x1b[A", b"\x1bOA", b"k", b"w") and selected > 0:
                    selected -= 1
                elif key in (b"\x1b[B", b"\x1bOB", b"j", b"s") and selected < len(options) - 1:
                    selected += 1
                elif key in (b"1", b"2"):
                    selected = min(int(key) - 1, len(options) - 1)
            if selected != before:
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

    def __init__(self, input_line: bool = True) -> None:
        self.commands: Dict[str, Command] = {}
        self._waiting: Optional["_Request"] = None
        self._confirm: Optional[Callable[[], None]] = None  # what to do if the answer is yes
        self._lock = threading.Lock()
        self._want_input_line = input_line
        self._input: Optional[InputLine] = None
        self.add("help", "/help", "Show this list", self._help)

    def add(self, name: str, usage: str, text: str, action: Callable[[str], None]) -> None:
        """text is the explanation in English; it is translated when /help shows it."""
        self.commands[name] = (usage, text, action)

    def start(self) -> None:
        if self._want_input_line:
            self._input = start_input_line()
        threading.Thread(target=self._read_loop, name="console", daemon=True).start()

    # --- For other parts of the server -----------------------------------

    def ask(self, hidden: bool = False) -> Optional[str]:
        """Waits for the next line typed (without showing it if hidden). None = no terminal."""
        request = _Request(hidden)
        with self._lock:
            self._waiting = request
        if hidden:
            if self._input is not None:
                self._input.set_hidden(True)
            else:
                _echo(False)
        try:
            request.done.wait()
        finally:
            if hidden:
                if self._input is not None:
                    self._input.set_hidden(False)
                else:
                    _echo(True)
            with self._lock:
                if self._waiting is request:
                    self._waiting = None
        return request.line

    def confirm(self, on_yes: Callable[[], None]) -> None:
        """
        For a command that asks "Type yes or no": the next line typed is the
        answer. yes runs on_yes, no cancels. (The question itself is printed
        by the command.)
        """
        with self._lock:
            self._confirm = on_yes

    def _answer(self, text: str) -> None:
        answer = text.strip().lower()
        if answer in ("yes", "y", "ja", "j"):
            with self._lock:
                on_yes, self._confirm = self._confirm, None
            if on_yes is not None:
                on_yes()
        elif answer in ("no", "n", "nej"):
            with self._lock:
                self._confirm = None
            say(tr("Cancelled, nothing was changed."))
        else:
            say(tr("Type {yes} or {no}.", yes=paint("yes", LIGHT_BLUE, bold=True), no=paint("no", LIGHT_BLUE, bold=True)))

    # --- Reading -------------------------------------------------------------

    def _next_line(self) -> Optional[str]:
        """The next line typed. None when there is no more (the window was closed)."""
        if self._input is not None:
            return self._input.read_line()
        try:
            line = sys.stdin.readline()
        except (OSError, ValueError):
            return None
        return line if line != "" else None

    def _read_loop(self) -> None:
        while True:
            line = self._next_line()
            if line is None:
                with self._lock:
                    waiting = self._waiting
                if waiting:
                    waiting.line = None
                    waiting.done.set()
                return
            text = line.strip()
            with self._lock:
                waiting = self._waiting
                confirming = self._confirm is not None
            if waiting is not None and not text.startswith("/"):
                waiting.line = text
                waiting.done.set()
                continue
            if confirming:
                if text.startswith("/"):
                    with self._lock:
                        self._confirm = None  # a new command instead of an answer: forget the question
                else:
                    self._answer(text)
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
    if _input_line is not None:
        _input_line.stop()
    _echo(True)


# --- The input line at the bottom of the window ------------------------------------
#
# While the server runs, what you type stays on the last line of the window and
# everything else is written above it, so that a log line never ends up in the
# middle of a command you are typing.
#
# How: the terminal is told to only scroll lines 1 to rows-1 (a "scroll region",
# ESC [ top ; bottom r). The last line is ours. The keys are read one at a time
# without the terminal showing them (cbreak mode), and we draw the line ourselves.
# The place where the next message goes is kept with "save cursor" (ESC 7) and
# "restore cursor" (ESC 8).
#
# It is turned off when the output doesn't go to a real Terminal window, or with
# "input_line": false in config.json.

PROMPT = "> "


class _Output:
    """Stands in for sys.stdout, so that everything printed goes above the input line."""

    def __init__(self, stream) -> None:
        self._stream = stream

    @property
    def stream(self):
        return self._stream

    def write(self, text: str) -> int:
        line = _input_line
        if line is not None and line.active:
            return line.write(text)
        return self._stream.write(text)

    def flush(self) -> None:
        line = _input_line
        if line is None or not line.active:
            self._stream.flush()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


class InputLine:
    def __init__(self, out, fd: int) -> None:
        self.out = out  # the real stdout
        self.fd = fd  # the keyboard (stdin)
        self.active = False
        self.text = ""
        self.hidden = False
        self._rows = 0
        self._columns = 0
        self._partial = ""  # printed text that doesn't end with a newline yet
        self._saved_tty = None
        self._saved_stderr = None
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._escape = ""  # an arrow key or similar being read
        self._last_was_return = False
        self._lines: Deque[str] = collections.deque()
        self._history: List[str] = []
        self._browsing: Optional[int] = None
        self._draft = ""

    # --- On and off ----------------------------------------------------------

    def start(self) -> bool:
        try:
            import termios
            import tty
            self._saved_tty = termios.tcgetattr(self.fd)
            size = os.get_terminal_size(self.out.fileno())
        except Exception:
            return False
        if size.lines < 6 or size.columns < 20:
            return False
        with _print_lock:
            try:
                tty.setcbreak(self.fd)
            except Exception:
                return False
            self._rows, self._columns = size.lines, size.columns
            # Make room, set the scroll region (that moves the cursor to the top)
            # and go back to where the text was, inside the region.
            self.out.write(f"\n\x1b7\x1b[1;{self._rows - 1}r\x1b8\x1b[1A\x1b7")
            self.active = True
            self._draw()
            self._saved_stderr = sys.stderr
            sys.stderr = _Output(sys.stderr)  # type: ignore[assignment]
        try:
            signal.signal(signal.SIGWINCH, self._window_changed)
        except (ValueError, AttributeError, OSError):
            pass  # not the main thread, or not a Mac/Linux
        return True

    def stop(self) -> None:
        with _print_lock:
            if not self.active:
                return
            if self._partial:
                self.write("\n")
            self.active = False
            # Clear our line, let the whole window scroll again, back to the text.
            self.out.write(f"\x1b[{self._rows};1H\x1b[2K\x1b[r\x1b8")
            self.out.flush()
            if self._saved_stderr is not None:
                sys.stderr = self._saved_stderr
            try:
                import termios
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved_tty)
            except Exception:
                pass

    def _window_changed(self, *_args) -> None:
        # A signal handler must not wait for the lock, so a thread does the work.
        threading.Thread(target=self._redraw_after_resize, daemon=True).start()

    def _redraw_after_resize(self) -> None:
        with _print_lock:
            if self.active and self._check_size():
                self._draw()

    def _check_size(self) -> bool:
        """Sets the scroll region again if the window has a new size. Returns True if it had."""
        try:
            size = os.get_terminal_size(self.out.fileno())
        except OSError:
            return False
        if (size.lines, size.columns) == (self._rows, self._columns) or size.lines < 3:
            return False
        self._rows, self._columns = size.lines, size.columns
        self.out.write(f"\x1b[1;{self._rows - 1}r\x1b[{self._rows - 1};1H\x1b7")
        return True

    # --- Output --------------------------------------------------------------

    def write(self, text: str) -> int:
        """Called instead of sys.stdout.write. Whole lines go above the input line."""
        with _print_lock:
            self._partial += text
            if "\n" not in self._partial:
                return len(text)
            *lines, self._partial = self._partial.split("\n")
            self._check_size()
            self.out.write("\x1b8" + "".join(line + "\n" for line in lines) + "\x1b7")
            self._draw()
        return len(text)

    def _draw(self) -> None:
        shown = "*" * len(self.text) if self.hidden else self.text
        room = max(1, self._columns - len(PROMPT) - 1)
        if len(shown) > room:
            shown = shown[-room:]
        self.out.write(f"\x1b[{self._rows};1H\x1b[2K{paint(PROMPT, GRAY)}{shown}")
        self.out.flush()

    def set_hidden(self, hidden: bool) -> None:
        """Hidden: show * instead of what is typed (for keys)."""
        with _print_lock:
            self.hidden = hidden
            if self.active:
                self._draw()

    # --- Keys ---------------------------------------------------------------

    def read_line(self) -> Optional[str]:
        """Waits for Enter and returns the line. None when the window is closed."""
        while not self._lines:
            try:
                data = os.read(self.fd, 1024)
            except InterruptedError:
                continue
            except OSError:
                return None
            if not data:
                return None
            for key in self._decoder.decode(data):
                self._key(key)
            with _print_lock:
                if self.active:
                    self._draw()
        return self._lines.popleft()

    def _key(self, key: str) -> None:
        if self._escape:
            self._escape += key
            if len(self._escape) == 2 and key not in "[O":
                self._escape = ""  # Alt + a key: ignore
            elif len(self._escape) > 2 and "@" <= key <= "~":  # the end of the sequence
                sequence, self._escape = self._escape, ""
                if sequence in ("\x1b[A", "\x1bOA"):
                    self._browse(-1)
                elif sequence in ("\x1b[B", "\x1bOB"):
                    self._browse(1)
            elif len(self._escape) > 16:
                self._escape = ""
            return
        was_return, self._last_was_return = self._last_was_return, key == "\r"
        if key == "\x1b":
            self._escape = key
        elif key == "\n" and was_return:
            pass  # \r\n (for example when pasting): one Enter, not two
        elif key in "\r\n":
            self._submit()
        elif key in "\x7f\x08":  # Backspace
            self.text = self.text[:-1]
        elif key == "\x15":  # Ctrl+U: clear the line
            self.text = ""
        elif key == "\x17":  # Ctrl+W: remove the last word
            self.text = self.text.rstrip()
            self.text = self.text[:self.text.rfind(" ") + 1]
        elif key == "\t":
            self.text += " "
        elif key >= " ":
            self.text += key

    def _submit(self) -> None:
        line, self.text = self.text, ""
        self._browsing = None
        if line.strip() and not self.hidden:
            if not self._history or self._history[-1] != line:
                self._history.append(line)
            self.write(f"{paint(PROMPT, GRAY)}{line}\n")  # what you typed stays in the window
        self._lines.append(line)

    def _browse(self, step: int) -> None:
        """Up and down arrows: earlier commands."""
        if self.hidden or not self._history:
            return
        if self._browsing is None:
            self._browsing, self._draft = len(self._history), self.text
        self._browsing = max(0, min(len(self._history), self._browsing + step))
        self.text = self._history[self._browsing] if self._browsing < len(self._history) else self._draft


_input_line: Optional[InputLine] = None


def start_input_line() -> Optional[InputLine]:
    """Turns on the input line at the bottom if this is a real Terminal window."""
    global _input_line
    out = sys.stdout.stream if isinstance(sys.stdout, _Output) else None
    if out is None or os.environ.get("TERM", "") in ("", "dumb") or sys.stdin is None:
        return None
    try:
        if not (out.isatty() and sys.stdin.isatty()):
            return None
        fd = sys.stdin.fileno()
    except (OSError, ValueError, AttributeError):
        return None
    line = InputLine(out, fd)
    _input_line = line
    if not line.start():
        _input_line = None
        return None
    atexit.register(line.stop)  # the window must always work again afterwards
    return line
