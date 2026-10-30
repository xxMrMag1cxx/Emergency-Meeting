"""
HTTPS tunnel with Cloudflare (the program "cloudflared").

Among Us requires HTTPS, and HTTPS requires a certificate that phones and
computers trust. Getting our own is complicated, so we borrow Cloudflare's:

    Among Us --HTTPS--> Cloudflare --tunnel--> cloudflared on the computer --HTTP--> our server

cloudflared gives us a random address, for example
    https://kingston-inside-best-graphic.trycloudflare.com
The address changes every time the server restarts. That's why ngrok is
preferred (see ngrok.py), and Cloudflare is the backup if ngrok doesn't work.

Only the HTTP part goes through the tunnel. The game itself (UDP) goes through
playit.gg (see playit.py), or directly to the Mac on your wifi.

No account is needed. On the Mac, download the program once with
get-cloudflared.command. On Windows and Linux the server downloads it by itself.
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
from .platforms import IS_MAC, IS_WINDOWS, arch, download, exe, make_runnable

log = logging.getLogger("tunnel")

# The tunnel's address (not api.trycloudflare.com, which shows up in error messages)
URL_PATTERN = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared(setting: str, download_if_missing: bool = False) -> Optional[str]:
    """
    Looks for cloudflared: first in the project folder, then in the usual places.
    On Windows and Linux it can be downloaded from Cloudflare's GitHub page (on the
    Mac, get-cloudflared.command picks a version that works on the Mac's macOS).
    """
    if setting and setting != "auto":
        return setting if Path(setting).exists() else None

    candidates: List[Path] = [PROJECT_DIR / exe("cloudflared")]
    found = shutil.which("cloudflared")
    if found:
        candidates.append(Path(found))
    if not IS_WINDOWS:
        candidates += [Path("/opt/homebrew/bin/cloudflared"), Path("/usr/local/bin/cloudflared")]

    for path in candidates:
        if path.is_file():
            return str(path)
    if download_if_missing and not IS_MAC:
        return download_cloudflared()
    return None


def download_cloudflared() -> Optional[str]:
    """Downloads cloudflared for Windows or Linux to the project folder."""
    machine = arch()
    if machine is None:
        return None
    name = f"cloudflared-windows-{machine}.exe" if IS_WINDOWS else f"cloudflared-linux-{machine}"
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{name}"
    target = PROJECT_DIR / exe("cloudflared")
    partial = target.with_name(target.name + ".part")
    log.info("Downloading cloudflared (%s)...", url)
    try:
        ok = download(url, partial, "cloudflared") and partial.stat().st_size > 1000000
    except OSError:
        ok = False
    if not ok:
        try:
            partial.unlink()
        except OSError:
            pass
        return None
    partial.replace(target)
    make_runnable(target)
    return str(target)


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
        self._stopping = threading.Event()
        self._confirmed = False  # on_ready() has been called

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
        if self._stopping.is_set():
            return  # we turned it off ourselves
        if code != 0:
            log.error("The HTTPS tunnel was turned off (error code %s).", code)
        if self.on_failed and (not self.url or not self._confirmed):
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
        if self._stopping.wait(8):
            return
        while time.monotonic() < deadline and not self._stopping.is_set():
            if self.process is not None and self.process.poll() is not None:
                return  # cloudflared stopped, _read_output() reports it
            for ctx in (context, unverified):
                try:
                    with urllib.request.urlopen(f"{self.url}/ping", timeout=5, context=ctx) as r:
                        if r.read() == b"pong":
                            self._confirmed = True
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
            "Could not confirm the tunnel from this computer, but it may work anyway. "
            "Try opening %s on the phone.",
            self.url,
        )
        if self._stopping.is_set() or (self.process is not None and self.process.poll() is not None):
            return
        self._confirmed = True
        self.on_ready(self.url)

    def stop(self) -> None:
        self._stopping.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
