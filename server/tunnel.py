"""
HTTPS-tunnel med Cloudflare (programmet "cloudflared").

Among Us kräver HTTPS, och HTTPS kräver ett certifikat som telefoner och
datorer litar på. Att skaffa ett eget är krångligt, så vi lånar Cloudflares:

    Among Us --HTTPS--> Cloudflare --tunnel--> cloudflared på Macen --HTTP--> vår server

cloudflared ger oss en slumpad adress, t.ex.
    https://kingston-inside-best-graphic.trycloudflare.com
Adressen byts varje gång servern startas om. Därför används helst ngrok
(se ngrok.py), och Cloudflare är reserven om ngrok inte fungerar.

Bara HTTP-delen går genom tunneln. Själva spelet (UDP) går via playit.gg
(se playit.py), eller direkt till Macen på ert wifi.

Inget konto behövs. Hämta programmet en gång med hamta-cloudflared.command.
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

log = logging.getLogger("tunnel")

URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared(setting: str) -> Optional[str]:
    """Letar efter cloudflared: först i projektmappen, sedan på vanliga ställen."""
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
    def __init__(self, binary: str, port: int, on_ready: Callable[[str], None]):
        self.binary = binary
        self.port = port
        self.on_ready = on_ready
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
        log.info("Startar HTTPS-tunneln (tar oftast 5-15 sekunder)...")
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
            # cloudflared skriver mycket. Vi visar bara felen (ERR), och inte för många.
            if " ERR " in line and errors_shown < 5:
                errors_shown += 1
                log.warning("cloudflared: %s", line)
            else:
                log.debug("cloudflared: %s", line)

        code = self.process.wait()
        if code not in (0, -15):  # -15 = vi stängde av den själva
            log.error("HTTPS-tunneln stängdes av (felkod %s).", code)

    def _wait_until_reachable(self) -> None:
        """
        En ny adress tar en liten stund innan den fungerar överallt.
        Vi provar själva tills vår egen server svarar genom tunneln.
        """
        log.info("Tunneln fick adressen %s, kollar att den fungerar...", self.url)
        context = ssl.create_default_context()
        unverified = ssl._create_unverified_context()  # bara för den här kollen
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
                        continue  # Macens Python saknar ibland certifikat, prova utan kollen
                    break  # adressen fungerar inte än, vänta lite
                except (OSError, ssl.SSLError):
                    break
            time.sleep(4)
        log.warning(
            "Kunde inte bekräfta tunneln från Macen, men den kan ändå fungera. "
            "Prova att öppna %s på telefonen.",
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
