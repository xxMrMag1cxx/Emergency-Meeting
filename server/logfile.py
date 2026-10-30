"""
Log files in the logs/ folder:

  logs/2026-10-30.log              everything the Terminal window showed that day
                                   (without colors and QR codes), so that nothing
                                   is lost when the window is closed
  logs/games/2026-10-30_13-20_GVTSQN.txt
                                   a summary of each round: who played, the roles,
                                   who was killed and who won
  logs/disconnect-....txt          the "black box" (see blackbox.py)

Files older than "keep_logs_days" in config.json are removed when the server
starts. Turn the day files off with "log_files": false.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TextIO

from .config import PROJECT_DIR

log = logging.getLogger("server")

LOG_DIR = PROJECT_DIR / "logs"
GAMES_DIR = LOG_DIR / "games"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[78]")
QR_LINE = re.compile(r"^[\s▀▄█]+$")  # a line of the QR code


class LogFile:
    """Gets everything that is written in the Terminal window and saves it in today's file."""

    def __init__(self, version: str) -> None:
        self.version = version
        self._partial = ""
        self._day = ""
        self._file: Optional[TextIO] = None
        self._lock = threading.Lock()
        self.broken = False

    def write(self, text: str) -> None:
        if self.broken:
            return
        with self._lock:
            self._partial += text
            if "\n" not in self._partial:
                return
            *lines, self._partial = self._partial.split("\n")
            for line in lines:
                self._write_line(line)

    def _write_line(self, line: str) -> None:
        line = ANSI.sub("", line).replace("\r", "").rstrip()
        if line and QR_LINE.match(line):
            return
        try:
            self._file_for_today().write(line + "\n")
            self._file_for_today().flush()
        except OSError:
            self.broken = True  # for example a full disk: the server must keep running

    def _file_for_today(self) -> TextIO:
        day = datetime.now().strftime("%Y-%m-%d")
        if self._file is None or day != self._day:
            if self._file is not None:
                self._file.close()
            LOG_DIR.mkdir(exist_ok=True)
            self._day = day
            self._file = open(LOG_DIR / f"{day}.log", "a", encoding="utf-8")
            self._file.write(f"\n===== Emergency Meeting {self.version}, "
                             f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        return self._file

    def close(self) -> None:
        with self._lock:
            if self._partial:
                self._write_line(self._partial)
                self._partial = ""
            if self._file is not None:
                self._file.close()
                self._file = None


def remove_old_logs(days: int) -> int:
    """Removes log files older than `days` days (0 = keep everything). Returns how many."""
    if days <= 0 or not LOG_DIR.is_dir():
        return 0
    limit = time.time() - days * 24 * 3600
    removed = 0
    patterns = ["*.log", "disconnect-*.txt", "games/*.txt"]
    for pattern in patterns:
        for path in LOG_DIR.glob(pattern):
            try:
                if path.stat().st_mtime < limit:
                    path.unlink()
                    removed += 1
            except OSError:
                pass
    return removed


def save_game_summary(code: str, lines: List[str]) -> Optional[Path]:
    """Saves the summary of a round in logs/games/. Returns the file, or None if it didn't work."""
    try:
        GAMES_DIR.mkdir(parents=True, exist_ok=True)
        path = GAMES_DIR / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{code}.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    except OSError as error:
        log.warning("Could not save the game summary: %s", error)
        return None
