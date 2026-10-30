"""
The server's settings.

The settings are read from the file config.json in the project folder. The
file is created the first time the server starts (the server then also asks
for a language and a name), with the default values below. Change it with a
text editor.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

log = logging.getLogger("config")

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_DIR / "config.json"


@dataclass
class Config:
    # The name shown in the log, on the join page and as the region in Among Us.
    server_name: str = "Emergency Meeting"

    # The language in the server's Terminal window: "English" or "Swedish".
    # Everything else (the join page, files, chat messages) is always English.
    language: str = "English"

    # Which network address the server listens on. "0.0.0.0" means
    # "all networks on this computer" and is usually right.
    listen_ip: str = "0.0.0.0"

    # The port the game connects to. Among Us uses 22023 for both
    # HTTP (TCP) and the game itself (UDP).
    port: int = 22023

    # The address other devices should use to reach the server.
    # "auto" means the server finds out the Mac's address on the
    # home network by itself (for example 192.168.1.23).
    public_ip: str = "auto"

    # Start an HTTPS tunnel (needed for Among Us to connect from another
    # device than the Mac). With ngrok if possible, otherwise cloudflared.
    https_tunnel: bool = True

    # Use ngrok for HTTPS, so that the address is the same every time.
    # false = only use Cloudflare (the address changes every start).
    ngrok: bool = True

    # Where ngrok is. "auto" = look by itself (the ngrok/ folder first) and
    # download the program if it's missing.
    ngrok_path: str = "auto"

    # Where cloudflared is. "auto" = look by itself (the project folder first).
    cloudflared_path: str = "auto"

    # Make the game reachable from the internet with playit.gg, so that
    # friends can play from their own homes without changing the router.
    playit: bool = True

    # Where the program playitd is. "auto" = look by itself (the playit/ folder first).
    playit_path: str = "auto"

    # The server is made for one version of Among Us (see the README).
    # Let newer versions of the game join anyway (they usually work).
    allow_future_game_versions: bool = True

    # Let older versions of the game join.
    allow_older_game_versions: bool = True

    # Let players join a game even if their version of Among Us doesn't fit
    # with the host's. false = they get a message and can't join that game.
    allow_version_mixing: bool = False

    # Only let in the names in allowed-names.txt (add them with /allow).
    only_allowed_names: bool = False

    # A password for the join page, so that only those who know it can add
    # the server. "" = no password.
    page_password: str = ""

    # Load plugins from the plugins/ folder.
    plugins: bool = True

    # Show the games on the server and their codes on the join page.
    page_shows_games: bool = True

    # Show the HTTPS address as a QR code in the Terminal window.
    terminal_qr: bool = True

    # Colors in the Terminal window.
    colors: bool = True

    # Which colors: "auto" (follows the Mac's dark/light mode), "dark" (for a
    # black background) or "light" (for a white background).
    color_theme: str = "auto"

    # Keep what you type on the last line of the Terminal window, with new
    # messages showing up above it. false = type among the messages like before.
    input_line: bool = True

    # Save everything the Terminal window shows in logs/<date>.log, and a
    # summary of every round in logs/games/.
    log_files: bool = True

    # Remove log files older than this many days when the server starts (0 = keep them all).
    keep_logs_days: int = 14

    # Set to true to see every single packet in the log (good for debugging).
    debug: bool = False

    def resolved_public_ip(self) -> str:
        if self.public_ip and self.public_ip != "auto":
            return self.public_ip
        return detect_local_ip()


def detect_local_ip() -> str:
    """
    Finds out the computer's address on the home network.

    The trick: we "pretend to connect" a UDP socket to an address on the
    internet. Nothing is sent, but the computer then picks which network
    card it would have used, and we can read its address.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def config_exists() -> bool:
    return CONFIG_FILE.exists()


# Files that had Swedish names in older versions -> their names now
OLD_FILE_NAMES = {
    "playit-nyckel.txt": "playit-key.txt",
    "ngrok-nyckel.txt": "ngrok-key.txt",
    "ngrok-adress.txt": "ngrok-address.txt",
    "loggar": "logs",
}


def rename_old_files() -> None:
    """Gives files from older versions their new names, so that nothing has to be done again."""
    for old, new in OLD_FILE_NAMES.items():
        old_path, new_path = PROJECT_DIR / old, PROJECT_DIR / new
        if old_path.exists() and not new_path.exists():
            try:
                old_path.rename(new_path)
            except OSError:
                pass


# Settings in the file that the server doesn't know (saved back untouched).
_unknown: Dict[str, object] = {}

# Settings changed with /setting while the server runs. They are saved in the
# file right away, but the server keeps using the old values until it restarts.
_pending: Dict[str, object] = {}


def setting_names() -> List[str]:
    return [field.name for field in dataclasses.fields(Config)]


def saved_value(config: Config, name: str) -> object:
    """The value in config.json (the one the server uses after a restart)."""
    return _pending.get(name, getattr(config, name))


def is_pending(name: str) -> bool:
    return name in _pending


def change_setting(config: Config, name: str, value: object) -> bool:
    """
    Saves a new value in config.json without changing the running server.
    Returns False if the file couldn't be saved.
    """
    old = _pending.get(name, _MISSING)
    if value == getattr(config, name):
        _pending.pop(name, None)
    else:
        _pending[name] = value
    if save_config(config):
        return True
    if old is _MISSING:
        _pending.pop(name, None)
    else:
        _pending[name] = old
    return False


def forget_pending(name: str) -> None:
    """When a command has changed the setting in the running server too (for example /language)."""
    _pending.pop(name, None)


_MISSING = object()


def load_config() -> Config:
    config = Config()
    _unknown.clear()
    _pending.clear()

    if not CONFIG_FILE.exists():
        return config

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        log.error("config.json can't be read: %s", error)
        log.error("Check that all quotes and commas are right. Using the default values.")
        config._broken = True  # type: ignore[attr-defined]  # don't overwrite the file
        return config

    for key, value in data.items():
        if hasattr(config, key) and not key.startswith("_"):
            setattr(config, key, value)
        else:
            _unknown[key] = value
            log.warning("Unknown setting in config.json: %s (ignored)", key)

    # New settings from a newer version are added to the file, so that they show up there.
    known = {f.name for f in dataclasses.fields(Config)}
    if not known.issubset(data):
        save_config(config)
    return config


def save_config(config: Config) -> bool:
    """Saves the settings in config.json. Returns False if it didn't work."""
    if getattr(config, "_broken", False):
        log.warning("config.json has an error, so the change was not saved in the file.")
        return False
    data = dataclasses.asdict(config)
    data.update(_pending)
    data.update(_unknown)
    try:
        CONFIG_FILE.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as error:
        log.error("Could not save config.json: %s", error)
        return False
    return True
