"""
HTTPS tunnel with Cloudflare (the program "cloudflared").

Among Us requires HTTPS, and HTTPS requires a certificate that phones and
computers trust. Getting our own is complicated, so we borrow Cloudflare's:

    Among Us --HTTPS--> Cloudflare --tunnel--> cloudflared on the Mac --HTTP--> our server

cloudflared gives us a random address, for example
    https://kingston-inside-best-graphic.trycloudflare.com
The address changes every time the server restarts. That's why ngrok is
preferred (see ngrok.py), and Cloudflare is the backup if ngrok doesn't work.

Only the HTTP part goes through the tunnel. The game itself (UDP) goes through
playit.gg (see playit.py), or directly to the Mac on your wifi.

No account is needed. Download the program once with get-cloudflared.command.
"""

from __future__ import annotations

import logging
import re
import shutil
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

from .config import PROJECT_DIR
from .i18n import tr

log = logging.getLogger("tunnel")

URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared(setting: str) -> Optional[str]:
    """Looks for cloudflared: first in the project folder, then in the usual places."""
    if setting and setting != "auto":
        return setting if Path(setting).exists() else None

    candidates: List[Path] = [PROJECT_DIR / "cloudflared"]
    found = shutil.which("cloudflared")
    if found:
        candidates.append(Path(found))
    candidates += [Path("/opt/homebrew/bin/cloudflared"), Path("/usr/local/bin/cloudflared")]

    for path in candidates:
        if path.is_file():
            return str(path)
    return None


class Tunnel:
    def __init__(
        self,
        binary: str,
        port: int,
        on_ready: Callable[[str], None],
        on_failed: Optional[Callable[[str], None]] = None,
    ):
        self.binary = binary
        self.port = port
        self.on_ready = on_ready
        self.on_failed = on_failed  # (reason), if cloudflared stops before it gets an address
        self.url = ""
        self.process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        command = [
            self.binary,
            "tunnel",
            "--no-autoupdate",
            "--url",
            f"http://127.0.0.1:{self.port}",
        ]
        log.debug("Starting the HTTPS tunnel (usually takes 5-15 seconds)...")
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        threading.Thread(target=self._read_output, name="tunnel", daemon=True).start()

    def _read_output(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        errors_shown = 0
        for line in self.process.stderr:
            line = line.strip()
            if not self.url:
                match = URL_PATTERN.search(line)
                if match:
                    self.url = match.group(0)
                    threading.Thread(target=self._wait_until_reachable, daemon=True).start()
                    continue
            # cloudflared writes a lot. We only show the errors (ERR), and not too many.
            if " ERR " in line and errors_shown < 5:
                errors_shown += 1
                log.warning("cloudflared: %s", line)
            else:
                log.debug("cloudflared: %s", line)

        code = self.process.wait()
        if code not in (0, -15):  # -15 = we turned it off ourselves
            log.error("The HTTPS tunnel was turned off (error code %s).", code)
        if not self.url and code != -15 and self.on_failed:
            self.on_failed(tr("cloudflared stopped (error code {code})", code=code))

    def _wait_until_reachable(self) -> None:
        """
        A new address takes a little while before it works everywhere.
        We try ourselves until our own server answers through the tunnel.
        """
        log.info("The tunnel got the address %s, checking that it works...", self.url)
        context = ssl.create_default_context()
        unverified = ssl._create_unverified_context()  # only for this check
        deadline = time.monotonic() + 90
        time.sleep(8)
        while time.monotonic() < deadline:
            for ctx in (context, unverified):
                try:
                    with urllib.request.urlopen(f"{self.url}/ping", timeout=5, context=ctx) as r:
                        if r.read() == b"pong":
                            self.on_ready(self.url)
                            return
                except urllib.error.URLError as error:
                    if isinstance(error.reason, ssl.SSLError):
                        continue  # the Mac's Python sometimes lacks certificates, try without the check
                    break  # the address doesn't work yet, wait a bit
                except (OSError, ssl.SSLError):
                    break
            time.sleep(4)
        log.warning(
            "Could not confirm the tunnel from the Mac, but it may work anyway. "
            "Try opening %s on the phone.",
            self.url,
        )
        self.on_ready(self.url)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
