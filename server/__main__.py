"""
The starting point of the server. Run it with:

    python3 -m server
"""

import sys

if sys.version_info < (3, 8):
    print("Emergency Meeting needs Python 3.8 or newer.")
    print("You have Python %d.%d. Download a newer one from https://www.python.org/downloads/macos/" % sys.version_info[:2])
    sys.exit(1)

import asyncio  # noqa: E402
import signal  # noqa: E402
from typing import Set  # noqa: E402

from . import __version__, i18n  # noqa: E402
from .config import config_exists, load_config, rename_old_files, save_config  # noqa: E402
from .i18n import tr  # noqa: E402
from .logfile import remove_old_logs  # noqa: E402
from .startup import Server  # noqa: E402
from .terminal import restore_terminal, setup_logging, start_log_file  # noqa: E402
from .wizard import first_start  # noqa: E402


async def run() -> None:
    rename_old_files()
    is_first_start = not config_exists()
    config = load_config()
    i18n.set_language(config.language)
    setup_logging(config.debug, config.colors, config.color_theme)
    if config.log_files:
        start_log_file(__version__)
        remove_old_logs(config.keep_logs_days)

    skipped: Set[str] = set()
    if is_first_start:
        # The first time: a guide for the language, the name, ngrok and playit.gg
        if sys.stdin is not None and sys.stdin.isatty():
            skipped = first_start(config)
        save_config(config)

    await Server(config, first_start=is_first_start, skipped=skipped).run()


def _stop_on_signal(signum, frame) -> None:
    raise KeyboardInterrupt  # stop nicely, so that playitd, ngrok and cloudflared stop too


def main() -> None:
    # For example when the Terminal window is closed (SIGBREAK on Windows: Ctrl+Break)
    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop_on_signal)
    if sys.platform == "win32":
        # The "selector" loop keeps receiving UDP after a player's computer has
        # gone away. Windows' default loop could stop receiving in older Python.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        restore_terminal()
        print("\n" + tr("The server is off. Bye!"))


if __name__ == "__main__":
    main()
