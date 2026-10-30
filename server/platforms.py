"""
The differences between macOS, Windows and Linux, in one place:

  - which computer this is, and the names of programs (ngrok.exe on Windows)
  - downloading a file (ngrok, playitd and cloudflared are downloaded when
    they are missing)
  - checking if a process runs, and stopping it
  - the Terminal window on Windows: colors and the keys

Everything else in the server is the same on all three.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger("server")

SYSTEM = platform.system()  # "Darwin", "Windows" or "Linux"
IS_MAC = SYSTEM == "Darwin"
IS_WINDOWS = SYSTEM == "Windows"
IS_LINUX = SYSTEM == "Linux"

# The exit code that tells start.bat to start the server again (/reboot on
# Windows, where a program can't replace itself like on macOS and Linux).
# 76 = start again after a failed start.
RESTART_EXIT_CODE = 75
RESTART_AFTER_FAILURE_EXIT_CODE = 76


def system_name() -> str:
    """"macOS", "Windows" or "Linux" (for messages)."""
    return {"Darwin": "macOS"}.get(SYSTEM, SYSTEM)


def arch() -> Optional[str]:
    """"amd64" or "arm64" (None for something else)."""
    machine = platform.machine().lower()
    return {"x86_64": "amd64", "amd64": "amd64", "x64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)


def exe(name: str) -> str:
    """The file name of a program: "ngrok" -> "ngrok.exe" on Windows."""
    return name + ".exe" if IS_WINDOWS else name


# --- Downloading ---------------------------------------------------------------

def download(url: str, target: Path, what: str) -> bool:
    """Downloads a file. curl first (comes with macOS and Windows 10/11), otherwise Python."""
    curl = shutil.which("curl")
    if curl:
        try:
            result = subprocess.run([curl, "-fsSL", "--retry", "2", "-o", str(target), url],
                                    capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                return True
            log.debug("curl failed: %s", result.stderr.strip())
        except (OSError, subprocess.SubprocessError) as error:
            log.debug("curl failed: %s", error)
    for context in (ssl.create_default_context(), ssl._create_unverified_context()):
        try:
            with urllib.request.urlopen(url, timeout=60, context=context) as response:
                target.write_bytes(response.read())
            return True
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLError):
                continue  # the Mac's Python sometimes lacks the certificates
            log.error("Could not download %s: %s", what, error.reason)
            return False
        except OSError as error:
            log.error("Could not download %s: %s", what, error)
            return False
    return False


def make_runnable(path: Path) -> None:
    """chmod +x, and on the Mac remove the "downloaded from the internet" mark."""
    try:
        if not os.access(path, os.X_OK):
            path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass
    if IS_MAC:
        try:
            subprocess.run(["xattr", "-d", "com.apple.quarantine", str(path)], capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


# --- Processes -------------------------------------------------------------------

def process_command(pid: int) -> str:
    """The command line (macOS/Linux) or program name (Windows) of a process. "" if it doesn't run."""
    try:
        if IS_WINDOWS:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout
            return out if f'"{pid}"' in out else ""
        return subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                              capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def end_process(pid: int) -> None:
    """Asks a process to close, waits until it has, and forces it after 5 seconds."""
    if IS_WINDOWS:
        # Careful: os.kill() on Windows always ends the process at once, even with signal 0.
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and process_command(pid):
            time.sleep(0.3)
        return
    for signal_number, seconds in ((15, 5.0), (9, 2.0)):
        try:
            os.kill(pid, signal_number)
        except OSError:
            return  # it's gone
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            time.sleep(0.2)
            try:
                os.kill(pid, 0)
            except OSError:
                return


# --- The Terminal window on Windows ---------------------------------------------

_vt_enabled: Optional[bool] = None


def enable_windows_terminal() -> bool:
    """
    Turns on "virtual terminal" mode in the Windows console, so that colors and
    cursor movements (the ESC codes) work like on macOS and Linux. Windows 10
    and 11 have it. Returns True if it works (always True on macOS and Linux).
    """
    global _vt_enabled
    if not IS_WINDOWS:
        return True
    if _vt_enabled is not None:
        return _vt_enabled
    _vt_enabled = False
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetConsoleMode.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.SetConsoleMode.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        handle = kernel32.GetStdHandle(-11)  # the screen (STD_OUTPUT_HANDLE)
        mode = wintypes.DWORD()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            _vt_enabled = bool(kernel32.SetConsoleMode(handle, mode.value | 0x0001 | 0x0004))
    except Exception:
        _vt_enabled = False
    return _vt_enabled


# Special keys from msvcrt.getwch() (they come as two characters: "\xe0" or
# "\x00" and then a letter) -> the same codes macOS and Linux send.
_WINDOWS_KEYS = {"H": "\x1b[A", "P": "\x1b[B", "M": "\x1b[C", "K": "\x1b[D"}


def read_windows_key() -> str:
    """Waits for a key in the Windows console. Arrows come back as "\x1b[A" etc., like on macOS."""
    import msvcrt
    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):
        return _WINDOWS_KEYS.get(msvcrt.getwch(), "")
    return key


def windows_key_waiting() -> bool:
    import msvcrt
    return bool(msvcrt.kbhit())


def stdin_is_terminal() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):
        return False
