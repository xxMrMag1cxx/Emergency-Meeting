"""
playit.gg: gör spelet nåbart från internet, utan att ändra något i routern.

Among Us ansluter i två steg:
  1. HTTPS (matchmaking) - går genom ngrok.py (eller tunnel.py, Cloudflare)
  2. UDP (själva spelet) - går hit, genom playit.gg

    Kompis --UDP--> playit.gg --tunnel--> playitd på Macen --UDP--> vår server (port 22023)

playit.gg ger servern en fast adress, t.ex. abc-def.gl.at.ply.gg:12345, som
är samma varje gång. Programmet playitd (playit.gg:s egen tunnel, byggd från
deras öppna källkod) håller kontakten med playit.gg och skickar trafiken hit.
Varje spelare får en egen port på Macen, så servern kan hålla isär dem.

Första gången:
  1. Servern visar en länk (https://playit.gg/claim/...). Värden öppnar den,
     loggar in eller skapar ett gratiskonto och godkänner servern.
  2. Servern får en hemlig nyckel som sparas i playit-nyckel.txt.
  3. Servern skapar en UDP-tunnel till port 22023 (eller ber värden göra det
     på playit.gg om det inte går).
Sedan sker allt av sig själv vid varje start.

Allt det här körs i en egen tråd, så servern fungerar på ert wifi under tiden.
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

log = logging.getLogger("playit")

API_BASE = os.environ.get("EM_PLAYIT_API", "https://api.playit.gg").rstrip("/")
SECRET_FILE = PROJECT_DIR / "playit-nyckel.txt"
PLAYIT_DIR = PROJECT_DIR / "playit"
LOCAL_IP = "127.0.0.1"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
PROBLEM = re.compile(r"\b(WARN|ERROR)\b")
# Varningar som playitd skriver vid varje start och som inte betyder något
# (t.ex. att Macen inte har IPv6). De visas bara med "debug": true.
HARMLESS = re.compile(
    r"No route to host|Network is unreachable|failed to ping tunnel server|"
    r"SessionNotSetup|failed to send initial ping"
)
PID_FILE = Path(tempfile.gettempdir()) / "em-playitd.pid"

CHECK_EVERY = 60  # sekunder mellan kollarna att tunneln finns kvar
RESOLVE_EVERY = 300  # sekunder mellan uppslagningarna av adressens IP


class PlayitError(Exception):
    """Något gick fel i kontakten med playit.gg."""


def find_playitd(setting: str) -> Optional[str]:
    """Letar efter playitd: först i mappen playit/, sedan på vanliga ställen."""
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
    """Among Us vill ha en IPv4-adress, inte ett namn."""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return None
    return infos[0][4][0] if infos else None


class PlayitApi:
    """Pratar med playit.gg:s API (JSON över HTTPS)."""

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
            raise PlayitError(f"konstigt svar från playit.gg: {text[:200]}") from None
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
            # playit.gg svarar ofta med JSON även vid fel.
            return error.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLError) and not self._unverified:
                # Python från python.org på Mac saknar ibland certifikaten
                # ("Install Certificates.command" har inte körts).
                log.debug("Certifikatkollen misslyckades, provar utan: %s", error)
                self._unverified = True
                return self._send(request)
            raise PlayitError(f"kunde inte nå playit.gg: {error.reason}") from None
        except OSError as error:
            raise PlayitError(f"kunde inte nå playit.gg: {error}") from None


class Playit:
    """
    Startar playitd och ser till att det finns en UDP-tunnel till spelet.
    `on_ready(adress, ip, port)` anropas när spelare utifrån kan ansluta,
    och igen om adressen ändras.
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
        self.show = show  # skriver en ruta i terminalen
        # Anropas när playit väntar på att värden gör något på playit.gg
        self.on_waiting = on_waiting or (lambda: None)
        self.process: Optional[subprocess.Popen] = None
        self.address = ""
        self.endpoint: Optional[Tuple[str, int]] = None
        self._stopping = threading.Event()
        self._shown: Dict[str, float] = {}

    # --- Start och stopp -------------------------------------------------

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
        except Exception:  # playit får aldrig krascha servern
            log.exception("Något gick fel med playit.gg. Servern fungerar fortfarande på ert wifi.")

    # --- Steg 1: koppla servern till ett playit-konto ---------------------

    @staticmethod
    def _load_secret() -> Optional[str]:
        try:
            secret = SECRET_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return secret or None

    def _claim(self) -> Optional[str]:
        """Visar en länk som värden öppnar en gång. Returnerar den hemliga nyckeln."""
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
                log.warning("playit.gg: %s (provar igen)", error)
                self._stopping.wait(10)
                continue

            if state == "UserAccepted":
                break
            if state == "UserRejected":
                log.warning("Servern godkändes inte på playit.gg. Starta om servern för en ny länk.")
                return None
            if state != last_state or time.monotonic() - last_box > 300:
                last_state, last_box = str(state), time.monotonic()
                self.on_waiting()
                self.show(
                    "KOPPLA SERVERN TILL PLAYIT.GG (bara första gången)",
                    [
                        "Då kan kompisar spela med er från sina egna hem.",
                        "",
                        "Öppna den här länken i en webbläsare:",
                        f"    {url}",
                        "",
                        "Logga in (eller skapa ett gratiskonto) och godkänn servern.",
                        "Under tiden fungerar servern som vanligt på ert wifi.",
                    ],
                )
            self._stopping.wait(2)
        else:
            return None

        for _ in range(30):
            try:
                reply = api.call("/claim/exchange", {"code": code})
            except PlayitError as error:
                log.debug("Väntar på nyckeln från playit.gg: %s", error)
                self._stopping.wait(2)
                continue
            secret = reply.get("secret_key") if isinstance(reply, dict) else None
            if secret:
                SECRET_FILE.write_text(secret + "\n", encoding="utf-8")
                try:
                    SECRET_FILE.chmod(0o600)
                except OSError:
                    pass
                log.info("Servern är kopplad till playit.gg. Nyckeln sparades i %s.", SECRET_FILE.name)
                return secret
        log.error("Fick ingen nyckel från playit.gg. Starta om servern och prova igen.")
        return None

    # --- Steg 2: programmet som håller tunneln öppen ---------------------

    @staticmethod
    def _stop_leftover() -> None:
        """Om servern stängdes abrupt förra gången kan playitd vara kvar. Stäng den."""
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
            log.info("Stänger en gammal playitd som var kvar (process %d).", pid)
            try:
                os.kill(pid, 15)
            except OSError:
                pass
            time.sleep(1)

    def _prepare_binary(self) -> None:
        """Se till att playitd får köras.

        En fil som kommit från en nedladdad ZIP har en "karantän"-märkning på
        Macen, och då vägrar macOS starta den. Vi tar bort märkningen, precis
        som när man högerklickar och väljer Öppna.
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
        log.info("Startar playit.gg-tunneln...")
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
            log.error("Kunde inte starta playitd: %s", error)
            if platform.system() == "Darwin":
                log.error("Om macOS säger att programmet inte går att öppna: högerklicka på "
                          "playit/playitd-macos i Finder, välj Öppna och sedan Öppna igen.")
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
        if not self._stopping.wait(2):  # Ctrl+C stänger playitd och servern samtidigt
            log.error("playit.gg-tunneln stängdes av (felkod %s). Startar om om en stund.", code)

    def _restart_if_dead(self, secret: str) -> None:
        if self.process is not None and self.process.poll() is not None and not self._stopping.is_set():
            self._stopping.wait(5)
            if not self._stopping.is_set():
                self._start_process(secret)

    # --- Steg 3: en UDP-tunnel till spelet ---------------------------------

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
                    self._show_once("auth", "PLAYIT.GG KÄNNER INTE IGEN SERVERN", [
                        "Nyckeln i playit-nyckel.txt fungerar inte längre",
                        "(servern kanske togs bort på playit.gg).",
                        "Ta bort filen playit-nyckel.txt och starta om servern,",
                        "så får du en ny länk att godkänna.",
                    ])
                else:
                    log.warning("playit.gg: %s (provar igen om en stund)", error)
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
                    "PLAYIT.GG-TUNNELN ÄR AVSTÄNGD",
                    [f"playit.gg säger: {tunnel['disabled_reason']}", "Kolla tunneln på https://playit.gg/account/tunnels"],
                )
            elif address != self.address or time.monotonic() - last_resolve > RESOLVE_EVERY:
                last_resolve = time.monotonic()
                if not self._use_address(address) and not self.address:
                    self._stopping.wait(10)  # adressen är ny, kolla snart igen
                    continue
            self._stopping.wait(CHECK_EVERY)

    def _find_tunnel(self, tunnels: List[dict]) -> Optional[dict]:
        """En UDP-tunnel (eller TCP+UDP) som går till vår port."""
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
                best = tunnel  # ingen lokal port angiven: samma port som den publika
        return best

    def _create_tunnel(self, api: PlayitApi, agent_id: Optional[str]) -> None:
        if not agent_id:
            return
        log.info("Skapar en UDP-tunnel till port %d på playit.gg...", self.port)
        requests = [
            # Så som playit.gg:s egna program gör (version 1 av anropet)
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
            # Det äldre anropet, om det nya inte finns
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
            log.info("Tunneln är skapad. Väntar på att playit.gg ger den en adress...")
            return
        log.info("Kunde inte skapa tunneln automatiskt (%s).", "; ".join(errors))
        self._ask_for_tunnel(agent_id, [])

    def _ask_for_tunnel(self, agent_id: Optional[str], pending: List[dict]) -> None:
        self.on_waiting()
        if pending:
            self._show_once("pending", "VÄNTAR PÅ PLAYIT.GG", [
                "Tunneln finns men har ingen adress än. Det brukar ta någon minut.",
                "Kolla gärna https://playit.gg/account/tunnels",
            ])
            return
        link = f"https://playit.gg/account/agents/{agent_id}" if agent_id else "https://playit.gg/account/agents"
        self._show_once("ask", "SKAPA EN TUNNEL PÅ PLAYIT.GG (bara första gången)", [
            "Servern kunde inte skapa tunneln själv. Gör så här:",
            f"  1. Öppna {link}",
            "  2. Lägg till en tunnel: välj UDP, 1 port.",
            f"  3. Lokal adress {LOCAL_IP}, lokal port {self.port}.",
            "Servern hittar tunneln själv när den är klar.",
        ])

    def _use_address(self, address: str) -> bool:
        """Slår upp adressens IP och berättar för servern. False om det inte gick."""
        parsed = parse_address(address)
        if parsed is None:
            log.warning("Förstod inte playit-adressen %r", address)
            return False
        host, port = parsed
        ip = resolve_ipv4(host)
        if ip is None:
            if not self.address and "dns" not in self._shown:
                self._shown["dns"] = time.monotonic()
                log.info("playit.gg gör i ordning adressen %s. Det kan ta några minuter första gången...", address)
            elif self.address:
                log.warning("Kunde inte slå upp %s (provar igen om en stund).", host)
            else:
                log.debug("Väntar fortfarande på att %s ska finnas", host)
            return False
        changed = (ip, port) != self.endpoint
        first = not self.address
        self.address, self.endpoint = address, (ip, port)
        if changed:
            if first:
                self.show("PLAYIT ÄR KLART!", [
                    "Kompisar kan nu spela med er från sina egna hem,",
                    "på wifi eller mobildata.",
                    "",
                    f"Spelets adress via playit.gg: {address}",
                    "Den adressen är samma varje gång servern startar.",
                ])
            else:
                log.info("playit-adressen är nu %s (%s:%d)", address, ip, port)
            self.on_ready(address, ip, port)
        return True

    # --- Meddelanden från playit.gg ----------------------------------------

    def _report_account(self, data: dict, api: PlayitApi) -> None:
        permissions = data.get("permissions") or {}
        status = permissions.get("account_status")
        messages = {
            "email-not-verified": "Bekräfta din e-post på playit.gg: https://playit.gg/account/settings/account/verify-email",
            "banned": "Kontot på playit.gg är avstängt: https://playit.gg/account",
            "agent-over-limit": "För många program på playit-kontot: https://playit.gg/account/agents",
            "agent-disabled": "Servern är avstängd på playit.gg: https://playit.gg/account/agents",
            "has-message": "playit.gg har ett meddelande till dig: https://playit.gg/account",
        }
        if status in messages:
            self._show_once(f"status-{status}", "MEDDELANDE FRÅN PLAYIT.GG", [messages[status]])
        elif status == "guest":
            self._show_guest_link(api)
        for notice in data.get("notices") or []:
            if not isinstance(notice, dict):
                continue
            text = str(notice.get("message", ""))
            if status == "email-not-verified" and "email" in text.lower():
                continue  # samma sak som rutan ovan
            link = notice.get("resolve_link")
            self._show_once(f"notice-{text}", "MEDDELANDE FRÅN PLAYIT.GG", [text] + ([str(link)] if link else []))

    def _show_guest_link(self, api: PlayitApi) -> None:
        if "guest" in self._shown:
            return
        try:
            session = api.call("/login/guest")
        except PlayitError:
            return
        key = session.get("session_key") if isinstance(session, dict) else None
        if key:
            self._show_once("guest", "PLAYIT.GG: GÄSTKONTO", [
                "Servern är kopplad till ett gästkonto på playit.gg.",
                "Logga in och spara kontot med en e-postadress, annars kan det försvinna:",
                f"    https://playit.gg/login/guest-account/{key}",
            ])

    def _show_once(self, key: str, title: str, lines: List[str]) -> None:
        """Visar en ruta, men inte samma ruta oftare än var tionde minut."""
        now = time.monotonic()
        if now - self._shown.get(key, -1e9) < 600:
            return
        self._shown[key] = now
        self.show(title, lines)
