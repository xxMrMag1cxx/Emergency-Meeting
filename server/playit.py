"""
playit.gg: makes the game reachable from the internet, without changing anything in the router.

Among Us connects in two steps:
  1. HTTPS (matchmaking) - goes through ngrok.py (or tunnel.py, Cloudflare)
  2. UDP (the game itself) - comes here, through playit.gg

    Friend --UDP--> playit.gg --tunnel--> playitd on the Mac --UDP--> our server (port 22023)

playit.gg gives the server a fixed address, for example abc-def.gl.at.ply.gg:12345,
that is the same every time. The program playitd (playit.gg's own tunnel, built
from their open source code) keeps in touch with playit.gg and sends the traffic
here. Every player gets their own port on the Mac, so the server can tell them apart.

The first time:
  1. The server shows a link (https://playit.gg/claim/...). The host opens it,
     logs in or creates a free account and approves the server.
  2. The server gets a secret key that is saved in playit-key.txt.
  3. The server creates a UDP tunnel to port 22023 (or asks the host to do it
     on playit.gg if that doesn't work).
After that everything happens by itself every start.

All of this runs in its own thread, so the server works on your wifi meanwhile.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import __version__
from .config import PROJECT_DIR
from .i18n import tr

log = logging.getLogger("playit")

API_BASE = os.environ.get("EM_PLAYIT_API", "https://api.playit.gg").rstrip("/")
SECRET_FILE = PROJECT_DIR / "playit-key.txt"
PLAYIT_DIR = PROJECT_DIR / "playit"
LOCAL_IP = "127.0.0.1"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
PROBLEM = re.compile(r"\b(WARN|ERROR)\b")
# Warnings that playitd writes every start and that don't mean anything
# (for example that the Mac doesn't have IPv6). They are only shown with "debug": true.
HARMLESS = re.compile(
    r"No route to host|Network is unreachable|failed to ping tunnel server|"
    r"SessionNotSetup|failed to send initial ping"
)
PID_FILE = Path(tempfile.gettempdir()) / "em-playitd.pid"

CHECK_EVERY = 60  # seconds between the checks that the tunnel is still there
RESOLVE_EVERY = 300  # seconds between the lookups of the address's IP


class PlayitError(Exception):
    """Something went wrong in the contact with playit.gg."""


def find_playitd(setting: str) -> Optional[str]:
    """Looks for playitd: first in the playit/ folder, then in the usual places."""
    if setting and setting != "auto":
        return setting if Path(setting).is_file() else None

    candidates: List[Path] = []
    if platform.system() == "Darwin":
        candidates.append(PLAYIT_DIR / "playitd-macos")
    elif platform.system() == "Linux":
        machine = platform.machine().lower()
        name = "aarch64" if machine in ("aarch64", "arm64") else "amd64"
        candidates.append(PLAYIT_DIR / f"playitd-linux-{name}")
    candidates.append(PLAYIT_DIR / "playitd")
    found = shutil.which("playitd")
    if found:
        candidates.append(Path(found))
    candidates += [Path("/opt/homebrew/bin/playitd"), Path("/usr/local/bin/playitd")]

    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def parse_address(address: str) -> Optional[Tuple[str, int]]:
    """'abc.gl.at.ply.gg:12345' -> ('abc.gl.at.ply.gg', 12345)."""
    host, sep, port = address.strip().rpartition(":")
    if not sep or not port.isdigit() or not host:
        return None
    return host.strip("[]"), int(port)


def resolve_ipv4(host: str) -> Optional[str]:
    """Among Us wants an IPv4 address, not a name."""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return None
    return infos[0][4][0] if infos else None


class PlayitApi:
    """Talks to playit.gg's API (JSON over HTTPS)."""

    def __init__(self, secret: Optional[str] = None, base: str = API_BASE):
        self.secret = secret
        self.base = base
        self._unverified = False

    def call(self, path: str, body: Optional[dict] = None) -> object:
        data = json.dumps(body or {}).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", f"EmergencyMeeting/{__version__}")
        if self.secret:
            request.add_header("Authorization", f"Agent-Key {self.secret.strip()}")
        text = self._send(request)
        try:
            reply = json.loads(text)
        except json.JSONDecodeError:
            raise PlayitError(tr("strange answer from playit.gg: {text}", text=text[:200])) from None
        status = reply.get("status") if isinstance(reply, dict) else None
        if status == "success":
            return reply.get("data")
        raise PlayitError(f"{status}: {reply.get('data') if isinstance(reply, dict) else reply}")

    def _send(self, request: urllib.request.Request) -> str:
        context = ssl._create_unverified_context() if self._unverified else ssl.create_default_context()
        try:
            with urllib.request.urlopen(request, timeout=20, context=context) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            # playit.gg often answers with JSON even on errors.
            return error.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLError) and not self._unverified:
                # Python from python.org on a Mac sometimes lacks the certificates
                # ("Install Certificates.command" hasn't been run).
                log.debug("The certificate check failed, trying without: %s", error)
                self._unverified = True
                return self._send(request)
            raise PlayitError(tr("could not reach playit.gg: {error}", error=error.reason)) from None
        except OSError as error:
            raise PlayitError(tr("could not reach playit.gg: {error}", error=error)) from None


class Playit:
    """
    Starts playitd and makes sure there is a UDP tunnel to the game.
    `on_ready(address, ip, port)` is called when players from outside can connect,
    and again if the address changes.
    """

    def __init__(
        self,
        binary: str,
        port: int,
        on_ready: Callable[[str, str, int], None],
        show: Callable[[str, List[str]], None],
        on_waiting: Optional[Callable[[], None]] = None,
    ):
        self.binary = binary
        self.port = port
        self.on_ready = on_ready
        self.show = show  # writes a box in the terminal
        # Called when playit waits for the host to do something on playit.gg
        self.on_waiting = on_waiting or (lambda: None)
        self.process: Optional[subprocess.Popen] = None
        self.address = ""
        self.endpoint: Optional[Tuple[str, int]] = None
        self._stopping = threading.Event()
        self._shown: Dict[str, float] = {}

    # --- Start and stop -------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._main, name="playit", daemon=True).start()

    def stop(self) -> None:
        self._stopping.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _main(self) -> None:
        try:
            secret = self._load_secret() or self._claim()
            if secret is None:
                return
            self._start_process(secret)
            self._watch_tunnel(PlayitApi(secret))
        except Exception:  # playit must never crash the server
            log.exception("Something went wrong with playit.gg. The server still works on your wifi.")

    # --- Step 1: connect the server to a playit account ---------------------

    @staticmethod
    def _load_secret() -> Optional[str]:
        try:
            secret = SECRET_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return secret or None

    def _claim(self) -> Optional[str]:
        """Shows a link that the host opens once. Returns the secret key."""
        api = PlayitApi()
        code = secrets.token_hex(5)
        url = f"https://playit.gg/claim/{code}"
        last_state = ""
        last_box = 0.0
        while not self._stopping.is_set():
            try:
                state = api.call(
                    "/claim/setup",
                    {"code": code, "agent_type": "self-managed", "version": f"Emergency Meeting {__version__}"},
                )
            except PlayitError as error:
                log.warning("playit.gg: %s (trying again)", error)
                self._stopping.wait(10)
                continue

            if state == "UserAccepted":
                break
            if state == "UserRejected":
                log.warning("The server was not approved on playit.gg. Restart the server for a new link.")
                return None
            if state != last_state or time.monotonic() - last_box > 300:
                last_state, last_box = str(state), time.monotonic()
                self.on_waiting()
                self.show(
                    tr("CONNECT THE SERVER TO PLAYIT.GG (only the first time)"),
                    [
                        tr("Then friends can play with you from their own homes."),
                        "",
                        tr("Open this link in a browser:"),
                        f"    {url}",
                        "",
                        tr("Log in (or create a free account) and approve the server."),
                        tr("Meanwhile the server works as usual on your wifi."),
                    ],
                )
            self._stopping.wait(2)
        else:
            return None

        for _ in range(30):
            try:
                reply = api.call("/claim/exchange", {"code": code})
            except PlayitError as error:
                log.debug("Waiting for the key from playit.gg: %s", error)
                self._stopping.wait(2)
                continue
            secret = reply.get("secret_key") if isinstance(reply, dict) else None
            if secret:
                SECRET_FILE.write_text(secret + "\n", encoding="utf-8")
                try:
                    SECRET_FILE.chmod(0o600)
                except OSError:
                    pass
                log.info("The server is connected to playit.gg. The key was saved in %s.", SECRET_FILE.name)
                return secret
        log.error("Got no key from playit.gg. Restart the server and try again.")
        return None

    # --- Step 2: the program that keeps the tunnel open ---------------------

    @staticmethod
    def _stop_leftover() -> None:
        """If the server was closed abruptly last time, playitd may still be there. Close it."""
        try:
            pid = int(PID_FILE.read_text().strip())
        except (OSError, ValueError):
            return
        try:
            command = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return
        if "playitd" in command and "--secret" in command:
            log.info("Closing an old playitd that was left (process %d).", pid)
            try:
                os.kill(pid, 15)
            except OSError:
                pass
            time.sleep(1)

    def _prepare_binary(self) -> None:
        """Make sure playitd is allowed to run.

        A file that came from a downloaded ZIP has a "quarantine" mark on the
        Mac, and then macOS refuses to start it. We remove the mark, just like
        when you right-click and choose Open.
        """
        path = Path(self.binary)
        try:
            if not os.access(path, os.X_OK):
                path.chmod(path.stat().st_mode | 0o111)
        except OSError:
            pass
        if platform.system() == "Darwin":
            try:
                subprocess.run(["xattr", "-d", "com.apple.quarantine", str(path)],
                               capture_output=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass

    def _start_process(self, secret: str) -> None:
        self._stop_leftover()
        self._prepare_binary()
        socket_path = os.path.join(tempfile.gettempdir(), f"em-playitd-{os.getpid()}.sock")
        command = [self.binary, "--secret", secret, "--socket-path", socket_path]
        env = dict(os.environ, NO_COLOR="1", PLAYIT_LOG=os.environ.get("PLAYIT_LOG", "info"))
        log.info("Starting the playit.gg tunnel...")
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                errors="replace",
                env=env,
                cwd=tempfile.gettempdir(),
            )
        except OSError as error:
            log.error("Could not start playitd: %s", error)
            if platform.system() == "Darwin":
                log.error("If macOS says the program can't be opened: right-click "
                          "playit/playitd-macos in Finder, choose Open and then Open again.")
            raise
        try:
            PID_FILE.write_text(str(self.process.pid))
        except OSError:
            pass
        threading.Thread(target=self._read_output, args=(self.process,), name="playitd", daemon=True).start()

    def _read_output(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        shown = 0
        for line in process.stdout:
            line = ANSI.sub("", line).strip()
            if not line:
                continue
            if PROBLEM.search(line) and not HARMLESS.search(line) and shown < 10:
                shown += 1
                log.warning("playitd: %s", line)
            else:
                log.debug("playitd: %s", line)
        code = process.wait()
        if not self._stopping.wait(2):  # Ctrl+C closes playitd and the server at the same time
            log.error("The playit.gg tunnel was turned off (error code %s). Restarting in a while.", code)

    def _restart_if_dead(self, secret: str) -> None:
        if self.process is not None and self.process.poll() is not None and not self._stopping.is_set():
            self._stopping.wait(5)
            if not self._stopping.is_set():
                self._start_process(secret)

    # --- Step 3: a UDP tunnel to the game ---------------------------------

    def _watch_tunnel(self, api: PlayitApi) -> None:
        tried_create = False
        last_resolve = 0.0
        waiting_since = time.monotonic()
        while not self._stopping.is_set():
            self._restart_if_dead(api.secret or "")
            try:
                data = api.call("/v1/agents/rundata")
            except PlayitError as error:
                if "auth" in str(error).lower():
                    self._show_once("auth", tr("PLAYIT.GG DOESN'T RECOGNIZE THE SERVER"), [
                        tr("The key in playit-key.txt doesn't work anymore"),
                        tr("(maybe the server was removed on playit.gg)."),
                        tr("Delete the file playit-key.txt and restart the server,"),
                        tr("and you get a new link to approve."),
                    ])
                else:
                    log.warning("playit.gg: %s (trying again in a while)", error)
                self._stopping.wait(30)
                continue
            data = data if isinstance(data, dict) else {}
            self._report_account(data, api)

            tunnel = self._find_tunnel(data.get("tunnels") or [])
            if tunnel is None:
                if not tried_create and not data.get("pending"):
                    tried_create = True
                    self._create_tunnel(api, data.get("agent_id"))
                elif time.monotonic() - waiting_since > 20:
                    self._ask_for_tunnel(data.get("agent_id"), data.get("pending") or [])
                self._stopping.wait(3 if time.monotonic() - waiting_since < 60 else 10)
                continue

            address = str(tunnel.get("display_address") or "")
            if tunnel.get("disabled_reason"):
                self._show_once(
                    "disabled",
                    tr("THE PLAYIT.GG TUNNEL IS DISABLED"),
                    [tr("playit.gg says: {reason}", reason=tunnel["disabled_reason"]),
                     tr("Check the tunnel at {url}", url="https://playit.gg/account/tunnels")],
                )
            elif address != self.address or time.monotonic() - last_resolve > RESOLVE_EVERY:
                last_resolve = time.monotonic()
                if not self._use_address(address) and not self.address:
                    self._stopping.wait(10)  # the address is new, check again soon
                    continue
            self._stopping.wait(CHECK_EVERY)

    def _find_tunnel(self, tunnels: List[dict]) -> Optional[dict]:
        """A UDP tunnel (or TCP+UDP) that goes to our port."""
        best = None
        for tunnel in tunnels:
            if not isinstance(tunnel, dict) or tunnel.get("port_type") not in ("udp", "both"):
                continue
            fields = {
                f.get("name"): f.get("value")
                for f in (tunnel.get("agent_config") or {}).get("fields", [])
                if isinstance(f, dict)
            }
            if str(fields.get("local_port", "")) == str(self.port):
                return tunnel
            if best is None and not fields.get("local_port"):
                best = tunnel  # no local port given: the same port as the public one
        return best

    def _create_tunnel(self, api: PlayitApi, agent_id: Optional[str]) -> None:
        if not agent_id:
            return
        log.info("Creating a UDP tunnel to port %d on playit.gg...", self.port)
        requests = [
            # The way playit.gg's own program does it (version 1 of the call)
            ("/v1/tunnels/create", {
                "ports": {"type": "custom-udp", "details": 1},
                "origin": {"type": "agent", "data": {
                    "agent_id": agent_id,
                    "config": {"fields": [
                        {"name": "local_ip", "value": LOCAL_IP},
                        {"name": "local_port", "value": str(self.port)},
                    ]},
                }},
                "enabled": True,
                "alloc": None,
                "name": "Emergency Meeting",
                "firewall_id": None,
            }),
            # The older call, if the new one doesn't exist
            ("/tunnels/create", {
                "name": "Emergency Meeting",
                "tunnel_type": None,
                "port_type": "udp",
                "port_count": 1,
                "origin": {
                    "type": "agent",
                    "data": {"agent_id": agent_id, "local_ip": LOCAL_IP, "local_port": self.port},
                },
                "enabled": True,
                "alloc": None,
                "firewall_id": None,
                "proxy_protocol": None,
            }),
        ]
        errors = []
        for path, body in requests:
            try:
                api.call(path, body)
            except PlayitError as error:
                log.debug("%s: %s", path, error)
                errors.append(str(error))
                continue
            log.info("The tunnel is created. Waiting for playit.gg to give it an address...")
            return
        log.info("Could not create the tunnel automatically (%s).", "; ".join(errors))
        self._ask_for_tunnel(agent_id, [])

    def _ask_for_tunnel(self, agent_id: Optional[str], pending: List[dict]) -> None:
        self.on_waiting()
        if pending:
            self._show_once("pending", tr("WAITING FOR PLAYIT.GG"), [
                tr("The tunnel exists but has no address yet. It usually takes a minute or so."),
                tr("Feel free to check {url}", url="https://playit.gg/account/tunnels"),
            ])
            return
        link = f"https://playit.gg/account/agents/{agent_id}" if agent_id else "https://playit.gg/account/agents"
        self._show_once("ask", tr("CREATE A TUNNEL ON PLAYIT.GG (only the first time)"), [
            tr("The server could not create the tunnel by itself. Do this:"),
            tr("  1. Open {url}", url=link),
            tr("  2. Add a tunnel: choose UDP, 1 port."),
            tr("  3. Local address {ip}, local port {port}.", ip=LOCAL_IP, port=self.port),
            tr("The server finds the tunnel by itself when it's ready."),
        ])

    def _use_address(self, address: str) -> bool:
        """Looks up the address's IP and tells the server. False if it didn't work."""
        parsed = parse_address(address)
        if parsed is None:
            log.warning("Didn't understand the playit address %r", address)
            return False
        host, port = parsed
        ip = resolve_ipv4(host)
        if ip is None:
            if not self.address and "dns" not in self._shown:
                self._shown["dns"] = time.monotonic()
                log.info("playit.gg is preparing the address %s. It can take a few minutes the first time...", address)
            elif self.address:
                log.warning("Could not look up %s (trying again in a while).", host)
            else:
                log.debug("Still waiting for %s to exist", host)
            return False
        changed = (ip, port) != self.endpoint
        first = not self.address
        self.address, self.endpoint = address, (ip, port)
        if changed:
            if first:
                self.show(tr("PLAYIT IS READY!"), [
                    tr("Friends can now play with you from their own homes,"),
                    tr("on wifi or mobile data."),
                    "",
                    tr("The game's address through playit.gg: {address}", address=address),
                    tr("That address is the same every time the server starts."),
                ])
            else:
                log.info("The playit address is now %s (%s:%d)", address, ip, port)
            self.on_ready(address, ip, port)
        return True

    # --- Messages from playit.gg ----------------------------------------

    def _report_account(self, data: dict, api: PlayitApi) -> None:
        permissions = data.get("permissions") or {}
        status = permissions.get("account_status")
        messages = {
            "email-not-verified": "Confirm your email on playit.gg: {url}/settings/account/verify-email",
            "banned": "The account on playit.gg is banned: {url}",
            "agent-over-limit": "Too many programs on the playit account: {url}/agents",
            "agent-disabled": "The server is disabled on playit.gg: {url}/agents",
            "has-message": "playit.gg has a message for you: {url}",
        }
        if status in messages:
            text = tr(messages[status], url="https://playit.gg/account")
            self._show_once(f"status-{status}", tr("MESSAGE FROM PLAYIT.GG"), [text])
        elif status == "guest":
            self._show_guest_link(api)
        for notice in data.get("notices") or []:
            if not isinstance(notice, dict):
                continue
            text = str(notice.get("message", ""))
            if status == "email-not-verified" and "email" in text.lower():
                continue  # the same thing as the box above
            link = notice.get("resolve_link")
            self._show_once(f"notice-{text}", tr("MESSAGE FROM PLAYIT.GG"), [text] + ([str(link)] if link else []))

    def _show_guest_link(self, api: PlayitApi) -> None:
        if "guest" in self._shown:
            return
        try:
            session = api.call("/login/guest")
        except PlayitError:
            return
        key = session.get("session_key") if isinstance(session, dict) else None
        if key:
            self._show_once("guest", tr("PLAYIT.GG: GUEST ACCOUNT"), [
                tr("The server is connected to a guest account on playit.gg."),
                tr("Log in and save the account with an email address, otherwise it can disappear:"),
                f"    https://playit.gg/login/guest-account/{key}",
            ])

    def _show_once(self, key: str, title: str, lines: List[str]) -> None:
        """Shows a box, but not the same box more often than every ten minutes."""
        now = time.monotonic()
        if now - self._shown.get(key, -1e9) < 600:
            return
        self._shown[key] = now
        self.show(title, lines)
