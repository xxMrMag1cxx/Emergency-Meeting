"""
A fixed HTTPS address with ngrok.

    Among Us --HTTPS--> ngrok --tunnel--> ngrok on the Mac --HTTP--> our server (TCP 22023)

Every free account on ngrok gets its own address, for example
    https://happy-penguin-1234.ngrok-free.dev
that is the same every time the server starts. Then friends only have to add
the server to Among Us once. (Cloudflare's address changes every start.)

The first time:
  1. The server asks the host to create a free account on ngrok and paste
     their "authtoken" into the terminal window. It's saved in ngrok-key.txt.
  2. The server downloads the program ngrok by itself and puts it in the ngrok/ folder.
After that everything happens by itself. If ngrok doesn't work, Cloudflare is
used like before, so the server works anyway.

All of this runs in its own thread, so the server works on your wifi meanwhile.
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
from .i18n import tr
from .platforms import IS_WINDOWS, arch, download, exe

log = logging.getLogger("ngrok")

KEY_FILE = PROJECT_DIR / "ngrok-key.txt"
ADDRESS_FILE = PROJECT_DIR / "ngrok-address.txt"
NGROK_DIR = PROJECT_DIR / "ngrok"
DOWNLOAD_BASE = os.environ.get("EM_NGROK_DOWNLOAD", "https://bin.equinox.io/c/bNyj1mQVY4c")

SIGNUP_URL = "https://dashboard.ngrok.com/signup"
TOKEN_URL = "https://dashboard.ngrok.com/get-started/your-authtoken"

URL_PATTERN = re.compile(r"https://[a-z0-9.-]+\.ngrok(?:-free)?\.(?:app|dev|io)\b")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,}$")

READY_TIMEOUT = 40  # seconds before we use Cloudflare instead
MAX_STARTS = 3  # tries before we give up for this time


def find_ngrok(setting: str) -> Optional[str]:
    """Looks for ngrok: first in the ngrok/ folder, then in the usual places."""
    if setting and setting != "auto":
        return setting if Path(setting).is_file() else None
    candidates: List[Path] = [NGROK_DIR / exe("ngrok")]
    found = shutil.which("ngrok")
    if found:
        candidates.append(Path(found))
    if not IS_WINDOWS:
        candidates += [Path("/opt/homebrew/bin/ngrok"), Path("/usr/local/bin/ngrok")]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def download_name() -> Optional[str]:
    """Which file ngrok has for this computer, for example ngrok-v3-stable-darwin-amd64.zip."""
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    machine = arch()
    if not system or not machine:
        return None
    ending = "tgz" if system == "linux" else "zip"
    return f"ngrok-v3-stable-{system}-{machine}.{ending}"


def download_ngrok() -> Optional[str]:
    """Downloads ngrok to the ngrok/ folder. Returns the path, or None if it didn't work."""
    name = download_name()
    if name is None:
        log.error("ngrok isn't available for this computer (%s %s).", platform.system(), platform.machine())
        return None
    url = f"{DOWNLOAD_BASE}/{name}"
    NGROK_DIR.mkdir(exist_ok=True)
    archive = NGROK_DIR / name
    log.info("Downloading ngrok (%s)...", url)
    if not download(url, archive, "ngrok"):
        return None

    target = NGROK_DIR / exe("ngrok")
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                member = next(m for m in z.namelist() if m.rstrip("/").endswith(exe("ngrok")))
                target.write_bytes(z.read(member))
        else:
            with tarfile.open(archive) as t:
                member = next(m for m in t.getmembers() if m.isfile() and m.name.endswith("ngrok"))
                source = t.extractfile(member)
                assert source is not None
                target.write_bytes(source.read())
    except (OSError, zipfile.BadZipFile, tarfile.TarError, StopIteration, AssertionError) as error:
        log.error("Could not unpack ngrok: %s", error)
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
        log.error("ngrok was downloaded but can't be started: %s", error)
        return None
    log.info("Downloaded %s", (version.stdout or version.stderr).strip() or "ngrok")
    return str(target)


_saved_terminal = None  # the terminal's settings while the key is read


def _read_hidden_line() -> str:
    """Reads a line without it showing in the terminal (like when you type a password)."""
    global _saved_terminal
    if IS_WINDOWS:
        import getpass
        try:
            return getpass.getpass("") + "\n"
        except EOFError:
            return ""
    try:
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSADRAIN, new)
    except Exception:  # no real terminal (for example Windows or a test)
        return sys.stdin.readline()
    _saved_terminal = (fd, old)
    try:
        return sys.stdin.readline()
    finally:
        restore_terminal()


def restore_terminal() -> None:
    """Puts the terminal back (so that you see what you type again)."""
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
    Gets the key out of what was pasted. On ngrok's page it's often written
    as a command: "ngrok config add-authtoken 2abc...". Then we take the last word.
    """
    words = text.strip().strip("'\"").split()
    return words[-1].strip("'\"") if words else ""


class Ngrok:
    """
    Starts ngrok and keeps an eye on it. Calls on_ready(url) when the address
    works, and on_failed() if ngrok can't be used (then the server uses
    Cloudflare instead).
    """

    def __init__(
        self,
        setting: str,
        port: int,
        on_ready: Callable[[str, bool], None],
        on_failed: Callable[[], None],
        show: Callable[[str, List[str]], None],
        ask: Optional[Callable[[bool], Optional[str]]] = None,
    ):
        self.setting = setting
        self.port = port
        self.on_ready = on_ready  # (url, the address has changed since last time)
        self.on_failed = on_failed
        self.show = show
        # Reads a line from the terminal (the server shares it with the commands).
        self.ask = ask
        self.url = ""
        self.process: Optional[subprocess.Popen] = None
        self._stopping = threading.Event()
        self._failed_reported = False
        self._config_file: Optional[Path] = None
        self._errors: List[str] = []
        self._announced = ""
        self.waiting_for_user = False  # True while the key is being asked for
        self.skipped = False  # the host pressed Enter instead of pasting a key

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

    # --- The main thread ----------------------------------------------------

    def _main(self) -> None:
        try:
            token = self._load_key() or self._ask_for_key()
            if not token:
                self._failed()
                return
            binary = find_ngrok(self.setting) or (download_ngrok() if self.setting in ("", "auto") else None)
            if not binary:
                self.show(tr("NGROK COULD NOT BE DOWNLOADED"), [
                    tr("The server could not download the program ngrok."),
                    tr("Check the internet connection and restart the server."),
                ])
                self._failed()
                return
            self._run(binary, token)
        except Exception:  # a bug here must not stop the server
            log.exception("Something went wrong with ngrok")
            self._failed()

    def _failed(self) -> None:
        if not self._failed_reported and not self._stopping.is_set():
            self._failed_reported = True
            self.on_failed()

    # --- Step 1: the key ------------------------------------------------

    @staticmethod
    def _load_key() -> Optional[str]:
        try:
            token = KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return token or None

    def _ask_for_key(self, wrong: bool = False) -> Optional[str]:
        """Asks for the key in the terminal window (only the first time)."""
        if sys.stdin is None:
            return None
        self.waiting_for_user = True
        try:
            return self._ask_for_key_now(wrong)
        finally:
            self.waiting_for_user = False

    def _ask_for_key_now(self, wrong: bool) -> Optional[str]:
        if wrong:
            title = tr("NGROK DOESN'T RECOGNIZE THE KEY")
            intro = [
                tr("The key in ngrok-key.txt doesn't work. Meanwhile Cloudflare is used."),
                tr("Get a new key like this:"),
            ]
        else:
            title = tr("FIXED HTTPS ADDRESS WITH NGROK (only the first time)")
            intro = [
                tr("With ngrok the server gets an HTTPS address that is the same every time,"),
                tr("so friends only have to add the server once."),
            ]
        self.show(title, intro + [
            "",
            tr("  1. Create a free account (or log in): {url}", url=SIGNUP_URL),
            tr("  2. Open {url}", url=TOKEN_URL),
            tr("  3. Copy your Authtoken."),
            tr("  4. Paste it here in the terminal window and press Enter."),
            tr("     (The key doesn't show when you paste it. That's on purpose,"),
            tr("     it's secret.)"),
            "",
            tr("Just press Enter to skip. Then Cloudflare is used like before."),
            tr("(To never be asked again, set \"ngrok\": false in config.json.)"),
        ])
        for _ in range(3):
            try:
                text = self.ask(True) if self.ask else _read_hidden_line()
            except (OSError, ValueError):
                return None
            if text is None:
                return None
            if self._stopping.is_set():
                return None
            token = clean_token(text)
            if not token:
                self.skipped = True
                log.info("Skipping ngrok this time. Cloudflare is used.")
                return None
            if not TOKEN_PATTERN.match(token):
                print(tr("  That didn't look like an authtoken. Try again (or press Enter):"), flush=True)
                continue
            KEY_FILE.write_text(token + "\n", encoding="utf-8")
            try:
                KEY_FILE.chmod(0o600)
            except OSError:
                pass
            log.info("Thanks! The key was saved in %s.", KEY_FILE.name)
            return token
        return None

    # --- Step 2: start ngrok ------------------------------------------

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
        previous = self._saved_url()  # the address last time
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
            log.debug("Starting ngrok (fixed HTTPS address)...")
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
                log.error("Could not start ngrok: %s", error)
                self._failed()
                return
            reader = threading.Thread(target=self._read_output, args=(self.process, ready), daemon=True)
            reader.start()

            started = time.monotonic()
            slow = False
            last_ask = 0.0
            while not ready.is_set() and self.process.poll() is None and not self._stopping.is_set():
                if time.monotonic() - started > 8 and time.monotonic() - last_ask > 3:
                    # If the log didn't say the address: ask ngrok's own little web page
                    last_ask = time.monotonic()
                    url = self._url_from_local_api()
                    if url:
                        self.url = url
                        ready.set()
                        break
                if not slow and time.monotonic() - started > READY_TIMEOUT:
                    slow = True
                    log.warning("ngrok hasn't answered in %d seconds. Cloudflare is used for now.", READY_TIMEOUT)
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
                token = self._ask_for_key(wrong=True)
                if not token:
                    self._failed()  # Cloudflare instead
                    return
                config = self._write_config(token)
                starts = 0
                continue
            if problem == "busy":
                self.show(tr("NGROK IS ALREADY IN USE"), [
                    tr("The ngrok account is already used by another server or program."),
                    tr("Close the other one (or the other server) and restart this one."),
                    tr("Meanwhile Cloudflare is used."),
                ])
                self._failed()
                return
            if problem == "url" and saved:
                log.info("ngrok didn't want the saved address %s. Trying without it.", saved)
                use_saved = False
                continue
            if self.url:
                log.error("ngrok was turned off. Restarting in a while...")
                starts = 0  # it worked before, so keep trying
                self._stopping.wait(10)
            else:
                for text in self._errors[:3]:
                    log.warning("ngrok: %s", text.splitlines()[0] if text else "?")
                self._failed()
                self._stopping.wait(5)
        if not self.url:
            log.warning("ngrok didn't get going. Cloudflare is used this time.")
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
                # Some errors ngrok writes as plain text (for example "ERROR:  ...")
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
        """ngrok has a little web page on the Mac (port 4040) that shows the address."""
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

    # --- Step 3: check the address and tell ---------------------------

    def _check_and_announce(self, previous: str) -> None:
        url = self.url.rstrip("/")
        self.url = url
        if url == self._announced:
            log.info("ngrok is running again (%s).", url)
            return
        changed = bool(previous) and previous.rstrip("/") != url
        if not previous or changed:
            try:
                ADDRESS_FILE.write_text(url + "\n", encoding="utf-8")
            except OSError:
                pass
        log.info("ngrok got the address %s, checking that it works...", url)
        if not self._reachable(url):
            log.warning(
                "Could not confirm the ngrok address from this computer, but it may work anyway. "
                "Try opening %s on the phone.", url,
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
                request.add_header("ngrok-skip-browser-warning", "1")  # no warning page
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
