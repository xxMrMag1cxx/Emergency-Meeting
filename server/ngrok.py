"""
Fast HTTPS-adress med ngrok.

    Among Us --HTTPS--> ngrok --tunnel--> ngrok på Macen --HTTP--> vår server (TCP 22023)

Varje gratiskonto på ngrok får en egen adress, t.ex.
    https://glad-pingvin-1234.ngrok-free.dev
som är samma varje gång servern startar. Då behöver kompisar bara lägga till
servern i Among Us en gång. (Cloudflares adress byts vid varje start.)

Första gången:
  1. Servern ber värden skapa ett gratiskonto på ngrok och klistra in sin
     "authtoken" i terminalfönstret. Den sparas i ngrok-nyckel.txt.
  2. Servern hämtar programmet ngrok själv och lägger det i mappen ngrok/.
Sedan går allt av sig självt. Om ngrok inte fungerar används Cloudflare som
förut, så servern fungerar ändå.

Allt det här körs i en egen tråd, så servern fungerar på ert wifi under tiden.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

from .config import PROJECT_DIR

log = logging.getLogger("ngrok")

KEY_FILE = PROJECT_DIR / "ngrok-nyckel.txt"
ADDRESS_FILE = PROJECT_DIR / "ngrok-adress.txt"
NGROK_DIR = PROJECT_DIR / "ngrok"
DOWNLOAD_BASE = os.environ.get("EM_NGROK_DOWNLOAD", "https://bin.equinox.io/c/bNyj1mQVY4c")

SIGNUP_URL = "https://dashboard.ngrok.com/signup"
TOKEN_URL = "https://dashboard.ngrok.com/get-started/your-authtoken"

URL_PATTERN = re.compile(r"https://[a-z0-9.-]+\.ngrok(?:-free)?\.(?:app|dev|io)\b")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,}$")

READY_TIMEOUT = 40  # sekunder innan vi tar Cloudflare i stället
MAX_STARTS = 3  # försök innan vi ger upp för den här gången


def find_ngrok(setting: str) -> Optional[str]:
    """Letar efter ngrok: först i mappen ngrok/, sedan på vanliga ställen."""
    if setting and setting != "auto":
        return setting if Path(setting).is_file() else None
    candidates: List[Path] = [NGROK_DIR / "ngrok"]
    found = shutil.which("ngrok")
    if found:
        candidates.append(Path(found))
    candidates += [Path("/opt/homebrew/bin/ngrok"), Path("/usr/local/bin/ngrok")]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def download_name() -> Optional[str]:
    """Vilken fil ngrok har för den här datorn, t.ex. ngrok-v3-stable-darwin-amd64.zip."""
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if not system or not arch:
        return None
    ending = "zip" if system == "darwin" else "tgz"
    return f"ngrok-v3-stable-{system}-{arch}.{ending}"


def download_ngrok() -> Optional[str]:
    """Hämtar ngrok till mappen ngrok/. Returnerar sökvägen, eller None om det inte gick."""
    name = download_name()
    if name is None:
        log.error("ngrok finns inte för den här datorn (%s %s).", platform.system(), platform.machine())
        return None
    url = f"{DOWNLOAD_BASE}/{name}"
    NGROK_DIR.mkdir(exist_ok=True)
    archive = NGROK_DIR / name
    log.info("Hämtar ngrok (%s)...", url)
    if not _fetch(url, archive):
        return None

    target = NGROK_DIR / "ngrok"
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                member = next(m for m in z.namelist() if m.rstrip("/").endswith("ngrok"))
                target.write_bytes(z.read(member))
        else:
            with tarfile.open(archive) as t:
                member = next(m for m in t.getmembers() if m.isfile() and m.name.endswith("ngrok"))
                source = t.extractfile(member)
                assert source is not None
                target.write_bytes(source.read())
    except (OSError, zipfile.BadZipFile, tarfile.TarError, StopIteration, AssertionError) as error:
        log.error("Kunde inte packa upp ngrok: %s", error)
        return None
    finally:
        try:
            archive.unlink()
        except OSError:
            pass
    target.chmod(0o755)

    try:
        version = subprocess.run([str(target), "version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        log.error("ngrok hämtades men går inte att starta: %s", error)
        return None
    log.info("Hämtade %s", (version.stdout or version.stderr).strip() or "ngrok")
    return str(target)


def _fetch(url: str, target: Path) -> bool:
    """Laddar ner en fil. curl först (följer med macOS), annars Python."""
    curl = shutil.which("curl")
    if curl:
        result = subprocess.run(
            [curl, "-fsSL", "--retry", "2", "-o", str(target), url],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True
        log.debug("curl misslyckades: %s", result.stderr.strip())
    for context in (ssl.create_default_context(), ssl._create_unverified_context()):
        try:
            with urllib.request.urlopen(url, timeout=60, context=context) as response:
                target.write_bytes(response.read())
            return True
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLError):
                continue  # Macens Python saknar ibland certifikaten
            log.error("Kunde inte hämta ngrok: %s", error.reason)
            return False
        except OSError as error:
            log.error("Kunde inte hämta ngrok: %s", error)
            return False
    return False


_saved_terminal = None  # terminalens inställningar medan nyckeln läses


def _read_hidden_line() -> str:
    """Läser en rad utan att den syns i terminalen (som när man skriver ett lösenord)."""
    global _saved_terminal
    try:
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSADRAIN, new)
    except Exception:  # ingen riktig terminal (t.ex. Windows eller ett test)
        return sys.stdin.readline()
    _saved_terminal = (fd, old)
    try:
        return sys.stdin.readline()
    finally:
        restore_terminal()


def restore_terminal() -> None:
    """Sätter tillbaka terminalen (så att man ser vad man skriver igen)."""
    global _saved_terminal
    if _saved_terminal is None:
        return
    fd, old = _saved_terminal
    _saved_terminal = None
    try:
        import termios
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        pass


def clean_token(text: str) -> str:
    """
    Tar fram nyckeln ur det som klistrades in. På ngroks sida står den ofta
    som ett kommando: "ngrok config add-authtoken 2abc...". Då tar vi sista ordet.
    """
    words = text.strip().strip("'\"").split()
    return words[-1].strip("'\"") if words else ""


class Ngrok:
    """
    Startar ngrok och håller koll på det. Anropar on_ready(url) när adressen
    fungerar, och on_failed() om ngrok inte går att använda (då tar
    servern Cloudflare i stället).
    """

    def __init__(
        self,
        setting: str,
        port: int,
        on_ready: Callable[[str, bool], None],
        on_failed: Callable[[], None],
        show: Callable[[str, List[str]], None],
    ):
        self.setting = setting
        self.port = port
        self.on_ready = on_ready  # (url, adressen har ändrats sedan förra gången)
        self.on_failed = on_failed
        self.show = show
        self.url = ""
        self.process: Optional[subprocess.Popen] = None
        self._stopping = threading.Event()
        self._failed_reported = False
        self._config_file: Optional[Path] = None
        self._errors: List[str] = []
        self._announced = ""

    @staticmethod
    def has_key() -> bool:
        return bool(Ngrok._load_key())

    def start(self) -> None:
        threading.Thread(target=self._main, name="ngrok", daemon=True).start()

    def stop(self) -> None:
        self._stopping.set()
        restore_terminal()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self._config_file:
            try:
                self._config_file.unlink()
            except OSError:
                pass

    # --- Huvudtråden ----------------------------------------------------

    def _main(self) -> None:
        try:
            token = self._load_key() or self._ask_for_key()
            if not token:
                self._failed()
                return
            binary = find_ngrok(self.setting) or (download_ngrok() if self.setting in ("", "auto") else None)
            if not binary:
                self.show("NGROK GICK INTE ATT HÄMTA", [
                    "Servern kunde inte hämta programmet ngrok.",
                    "Kolla internetanslutningen och starta om servern.",
                    "Under tiden används Cloudflare (adressen byts vid varje start).",
                ])
                self._failed()
                return
            self._run(binary, token)
        except Exception:  # en bugg här får inte stoppa servern
            log.exception("Något gick fel med ngrok")
            self._failed()

    def _failed(self) -> None:
        if not self._failed_reported and not self._stopping.is_set():
            self._failed_reported = True
            self.on_failed()

    # --- Steg 1: nyckeln ------------------------------------------------

    @staticmethod
    def _load_key() -> Optional[str]:
        try:
            token = KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return token or None

    def _ask_for_key(self, wrong: bool = False) -> Optional[str]:
        """Frågar efter nyckeln i terminalfönstret (bara första gången)."""
        if sys.stdin is None:
            return None
        if wrong:
            title = "NGROK KÄNNER INTE IGEN NYCKELN"
            intro = [
                "Nyckeln i ngrok-nyckel.txt fungerar inte. Under tiden används Cloudflare.",
                "Hämta en ny nyckel så här:",
            ]
        else:
            title = "FAST HTTPS-ADRESS MED NGROK (bara första gången)"
            intro = [
                "Med ngrok får servern en HTTPS-adress som är samma varje gång,",
                "så kompisar behöver bara lägga till servern en gång.",
            ]
        self.show(title, intro + [
            "",
            f"  1. Skapa ett gratiskonto (eller logga in): {SIGNUP_URL}",
            f"  2. Öppna {TOKEN_URL}",
            "  3. Kopiera din Authtoken.",
            "  4. Klistra in den här i terminalfönstret och tryck Enter.",
            "     (Nyckeln syns inte när du klistrar in den. Det är meningen,",
            "     den är hemlig.)",
            "",
            "Tryck bara Enter för att hoppa över. Då används Cloudflare som förut.",
        ])
        for _ in range(3):
            try:
                text = _read_hidden_line()
            except (OSError, ValueError):
                return None
            if self._stopping.is_set():
                return None
            token = clean_token(text)
            if not token:
                log.info("Hoppar över ngrok den här gången. Cloudflare används.")
                return None
            if not TOKEN_PATTERN.match(token):
                print("  Det där såg inte ut som en authtoken. Prova igen (eller tryck Enter):", flush=True)
                continue
            KEY_FILE.write_text(token + "\n", encoding="utf-8")
            try:
                KEY_FILE.chmod(0o600)
            except OSError:
                pass
            log.info("Tack! Nyckeln sparades i %s.", KEY_FILE.name)
            return token
        return None

    # --- Steg 2: starta ngrok ------------------------------------------

    def _write_config(self, token: str) -> Path:
        path = Path(tempfile.gettempdir()) / f"em-ngrok-{os.getpid()}.yml"
        path.write_text(
            "version: \"3\"\n"
            "agent:\n"
            f"  authtoken: {json.dumps(token)}\n"
            "  log: stdout\n"
            "  log_format: json\n"
            "  log_level: info\n"
            "  console_ui: false\n"
            "  update_check: false\n",
            encoding="utf-8",
        )
        try:
            path.chmod(0o600)
        except OSError:
            pass
        self._config_file = path
        return path

    @staticmethod
    def _saved_url() -> str:
        try:
            return ADDRESS_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _run(self, binary: str, token: str) -> None:
        config = self._write_config(token)
        previous = self._saved_url()  # adressen förra gången
        use_saved = True
        starts = 0
        while not self._stopping.is_set() and starts < MAX_STARTS:
            starts += 1
            saved = self._saved_url() if use_saved else ""
            command = [binary, "http", f"http://127.0.0.1:{self.port}", "--config", str(config)]
            if saved:
                command += ["--url", saved]
            self._errors = []
            ready = threading.Event()
            log.info("Startar ngrok (fast HTTPS-adress)...")
            try:
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    errors="replace",
                    cwd=tempfile.gettempdir(),
                )
            except OSError as error:
                log.error("Kunde inte starta ngrok: %s", error)
                self._failed()
                return
            reader = threading.Thread(target=self._read_output, args=(self.process, ready), daemon=True)
            reader.start()

            started = time.monotonic()
            slow = False
            last_ask = 0.0
            while not ready.is_set() and self.process.poll() is None and not self._stopping.is_set():
                if time.monotonic() - started > 8 and time.monotonic() - last_ask > 3:
                    # Om loggen inte sa adressen: fråga ngroks egen lilla webbsida
                    last_ask = time.monotonic()
                    url = self._url_from_local_api()
                    if url:
                        self.url = url
                        ready.set()
                        break
                if not slow and time.monotonic() - started > READY_TIMEOUT:
                    slow = True
                    log.warning("ngrok har inte svarat på %d sekunder. Cloudflare används så länge.", READY_TIMEOUT)
                    self._failed()
                ready.wait(0.5)

            if ready.is_set():
                self._check_and_announce(previous)
            self.process.wait()
            reader.join(timeout=2)
            if self._stopping.wait(2):
                return

            problem = self._explain_errors()
            if problem == "auth":
                try:
                    KEY_FILE.unlink()
                except OSError:
                    pass
                self._failed()  # Cloudflare under tiden
                token = self._ask_for_key(wrong=True)
                if not token:
                    return
                config = self._write_config(token)
                starts = 0
                continue
            if problem == "busy":
                self.show("NGROK ANVÄNDS REDAN", [
                    "ngrok-kontot används redan av en annan server eller ett annat program.",
                    "Stäng det andra (eller den andra servern) och starta om den här.",
                    "Under tiden används Cloudflare.",
                ])
                self._failed()
                return
            if problem == "url" and saved:
                log.info("ngrok ville inte ha den sparade adressen %s. Provar utan den.", saved)
                use_saved = False
                continue
            if self.url:
                log.error("ngrok stängdes av. Startar om om en stund...")
                starts = 0  # det fungerade förut, så fortsätt försöka
                self._stopping.wait(10)
            else:
                for text in self._errors[:3]:
                    log.warning("ngrok: %s", text.splitlines()[0] if text else "?")
                self._failed()
                self._stopping.wait(5)
        if not self.url:
            log.warning("ngrok kom inte igång. Cloudflare används den här gången.")
            self._failed()

    def _read_output(self, process: subprocess.Popen, ready: threading.Event) -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                entry = None
            if not isinstance(entry, dict):
                # Vissa fel skriver ngrok som vanlig text (t.ex. "ERROR:  ...")
                log.debug("ngrok: %s", line)
                match = URL_PATTERN.search(line)
                if match and "started" in line and not ready.is_set():
                    self.url = match.group(0)
                    ready.set()
                elif "ERR_NGROK" in line or line.upper().startswith("ERROR"):
                    self._errors.append(line)
                continue

            log.debug("ngrok: %s", line)
            url = str(entry.get("url") or "")
            if url.startswith("https://") and "started" in str(entry.get("msg", "")) and not ready.is_set():
                self.url = url
                ready.set()
            level = str(entry.get("lvl", ""))
            error = str(entry.get("err", "") or "")
            if level in ("eror", "error", "crit") or (error and error != "<nil>"):
                text = (error or str(entry.get("msg", ""))).replace("\r", "").strip()
                self._errors.append(text)

    @staticmethod
    def _url_from_local_api() -> str:
        """ngrok har en liten webbsida på Macen (port 4040) som visar adressen."""
        for port in (4040, 4041, 4042):
            for path in ("/api/tunnels", "/api/endpoints"):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
                        data = json.loads(response.read().decode("utf-8", errors="replace"))
                except (OSError, ValueError):
                    continue
                if not isinstance(data, dict):
                    continue
                items = data.get("tunnels") or data.get("endpoints") or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("public_url") or item.get("url") or "")
                    if url.startswith("https://"):
                        return url
        return ""

    def _explain_errors(self) -> str:
        text = "\n".join(self._errors)
        if "ERR_NGROK_105" in text or "ERR_NGROK_107" in text or "authentication failed" in text.lower():
            return "auth"
        if "ERR_NGROK_108" in text or "ERR_NGROK_334" in text or "already online" in text.lower():
            return "busy"
        if re.search(r"ERR_NGROK_(3\d\d|15\d)", text) or "domain" in text.lower() or "url" in text.lower():
            return "url"
        return ""

    # --- Steg 3: kolla adressen och berätta ---------------------------

    def _check_and_announce(self, previous: str) -> None:
        url = self.url.rstrip("/")
        self.url = url
        if url == self._announced:
            log.info("ngrok är igång igen (%s).", url)
            return
        changed = bool(previous) and previous.rstrip("/") != url
        if not previous or changed:
            try:
                ADDRESS_FILE.write_text(url + "\n", encoding="utf-8")
            except OSError:
                pass
        log.info("ngrok fick adressen %s, kollar att den fungerar...", url)
        if not self._reachable(url):
            log.warning(
                "Kunde inte bekräfta ngrok-adressen från Macen, men den kan ändå fungera. "
                "Prova att öppna %s på telefonen.", url,
            )
        if not self._stopping.is_set():
            self._announced = url
            self.on_ready(url, changed)

    def _reachable(self, url: str) -> bool:
        deadline = time.monotonic() + 30
        contexts = (ssl.create_default_context(), ssl._create_unverified_context())
        while time.monotonic() < deadline and not self._stopping.is_set():
            for context in contexts:
                request = urllib.request.Request(f"{url}/ping")
                request.add_header("ngrok-skip-browser-warning", "1")  # ingen varningssida
                request.add_header("User-Agent", "EmergencyMeeting")
                try:
                    with urllib.request.urlopen(request, timeout=5, context=context) as response:
                        if response.read() == b"pong":
                            return True
                except urllib.error.URLError as error:
                    if isinstance(error.reason, ssl.SSLError):
                        continue
                    break
                except (OSError, ssl.SSLError):
                    break
            self._stopping.wait(3)
        return False
