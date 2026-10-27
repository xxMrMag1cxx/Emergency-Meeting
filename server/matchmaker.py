"""
HTTP-matchmaking: spelets "telefonväxel".

Innan Among Us ansluter till själva spelservern (UDP) frågar spelet
via vanlig HTTP, samma sorts trafik som en webbsida använder:

  1. POST /api/user        "Får jag en inloggningsbiljett (token)?"
  2. PUT  /api/games       "Var ska jag skapa mitt spel?"  -> vår IP + port
  3. GET  /api/games/<kod> "Var finns spelet med den här koden?"
  4. GET  /api/games/filtered och /api/filters
                           "Vilka offentliga spel finns?"

Sedan ansluter spelet via UDP till adressen vi gav det.

Among Us kräver HTTPS om spelet körs på en annan enhet än servern.
Det löser vi med en tunnel (se tunnel.py): tunneln tar emot HTTPS från
internet och skickar vidare det som vanlig HTTP hit.
"""

from __future__ import annotations

import base64
import json
import logging
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import gamecode
from .config import Config
from .lobby import Lobby, LobbyManager
from .protocol import DisconnectReason
from .region import region_info_json
from .webpage import render

log = logging.getLogger("http")


def ip_to_number(ip: str) -> int:
    """Among Us vill ha IP-adressen som ett enda tal (bytes i omvänd ordning)."""
    return struct.unpack("<I", socket.inet_aton(ip))[0]


class ServerInfo:
    """Saker som HTTP-delen behöver veta och som kan ändras medan servern kör."""

    def __init__(self, config: Config, public_ip: str, lobbies: LobbyManager):
        self.config = config
        self.public_ip = public_ip
        self.lobbies = lobbies
        self.tunnel_url = ""  # fylls i när tunneln är igång


class MatchmakerHandler(BaseHTTPRequestHandler):
    # Sätts av start_matchmaker() nedan.
    info: ServerInfo

    server_version = "EmergencyMeeting"
    protocol_version = "HTTP/1.1"
    timeout = 30  # sekunder innan en tyst anslutning stängs

    @property
    def config(self) -> Config:
        return self.info.config

    # --- Felsökning ------------------------------------------------------

    def handle(self) -> None:
        # Kika på första byten innan vi läser något. HTTPS (TLS) börjar
        # alltid med byte 0x16, vanlig HTTP börjar med en bokstav (GET, PUT...).
        try:
            first = self.connection.recv(1, socket.MSG_PEEK)
        except OSError:
            return
        if first == b"\x16":
            log.warning(
                "%s försökte ansluta med HTTPS direkt till port %s. "
                "Det går inte, använd HTTPS-adressen från tunneln i stället.",
                self.client_address[0],
                self.config.port,
            )
            return
        super().handle()

    def log_message(self, format: str, *args: Any) -> None:
        # Stäng av den inbyggda loggningen, vi loggar själva nedan.
        pass

    def log_error(self, format: str, *args: Any) -> None:
        text = format % args
        if "timed out" in text:
            # cloudflared håller anslutningar öppna "ifall att". När de har
            # varit tysta en stund stänger vi dem. Det är helt normalt.
            log.debug("Stängde en tyst anslutning från %s", self.client_address[0])
            return
        log.warning("HTTP-fel från %s: %s", self.client_address[0], text)

    # --- Hjälpfunktioner -------------------------------------------------

    def _send(self, status: int, body: Any, content_type: str = "application/json") -> None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
        else:
            data = str(body).encode("utf-8")
            if content_type == "application/json":
                content_type = "text/plain; charset=utf-8"

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> Optional[dict]:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Fick ogiltig JSON: %r", raw[:200])
            return None

    def _path(self) -> Tuple[str, str]:
        parsed = urlparse(self.path)
        return parsed.path.rstrip("/") or "/", parsed.query

    def _via_https(self) -> bool:
        """Kom förfrågan via tunneln (HTTPS) eller direkt (HTTP)?"""
        if self.headers.get("X-Forwarded-Proto", "").lower() == "https":
            return True
        return '"https"' in self.headers.get("Cf-Visitor", "")

    def _public_address(self) -> Tuple[str, int, bool]:
        """Adressen som spelet ska använda, sett från den som frågar."""
        host = (self.headers.get("Host") or self.info.public_ip).split(":")[0]
        if self._via_https():
            return f"https://{host}", 443, True
        return f"http://{host}", self.config.port, False

    def _listing(self, lobby: Lobby) -> dict:
        """Beskrivningen av ett spel som visas i spelets lista."""
        host = lobby.host
        hs = host.connection.handshake if host else None
        return {
            "IP": ip_to_number(self.info.public_ip),
            "Port": self.config.port,
            "GameId": lobby.code_int,
            "PlayerCount": len(lobby.players),
            "HostName": lobby.host_name,
            "TrueHostName": lobby.host_name,
            "HostPlatformName": hs.platform_name if hs else "",
            "Platform": hs.platform if hs else 0,
            "QuickChat": hs.chat_mode if hs else 1,
            "Age": 0,
            "MaxPlayers": lobby.options.max_players,
            "NumImpostors": lobby.options.num_impostors,
            "MapId": lobby.options.map_id,
            "Language": lobby.options.keywords,
            "Options": base64.b64encode(lobby.options.raw).decode("ascii"),
        }

    def _host_server(self) -> dict:
        return {"Ip": ip_to_number(self.info.public_ip), "Port": self.config.port}

    def _who(self) -> str:
        via = "via HTTPS-tunneln" if self._via_https() else "direkt"
        ip = self.headers.get("Cf-Connecting-Ip") or self.client_address[0]
        return f"{ip}, {via}"

    # --- Förfrågningar ---------------------------------------------------

    def do_GET(self) -> None:
        path, _query = self._path()
        log.debug("GET %s (%s)", self.path, self._who())

        if path == "/":
            url, port, is_https = self._public_address()
            log.info("Någon öppnade startsidan (%s)", self._who())
            page = render(self.config.server_name, url, port, is_https, self.info.tunnel_url)
            self._send(200, page, "text/html; charset=utf-8")

        elif path == "/regionInfo.json":
            url, port, _ = self._public_address()
            log.info("Någon laddade ner regionInfo.json (%s)", self._who())
            self._send(200, region_info_json(self.config.server_name, url, port), "application/json")

        elif path == "/ping":
            self._send(200, "pong")

        elif path == "/api/filters":
            self._send(200, {"filters": ["Tags", "NumImposters"]})

        elif path in ("/api/games", "/api/games/filtered"):
            # Listan över offentliga spel ("Find Game" i spelet).
            listings = [self._listing(lobby) for lobby in self.info.lobbies.public_lobbies()]
            log.info("Spelet frågade efter offentliga spel (%d st)", len(listings))
            if path.endswith("filtered"):
                total = len(self.info.lobbies.all())
                self._send(
                    200,
                    {"games": listings, "metadata": {"allGamesCount": total, "matchingGamesCount": len(listings)}},
                )
            else:
                self._send(200, listings)

        elif path.startswith("/api/games/"):
            # "Var finns spelet med den här koden?" (när man skriver in en kod)
            try:
                code_int = int(path.rsplit("/", 1)[-1])
            except ValueError:
                code_int = -1
            lobby = self.info.lobbies.find(code_int)
            code = gamecode.int_to_code(code_int) if code_int != -1 else "?"
            if lobby is None:
                log.info("Någon letade efter spelkod %s, men det spelet finns inte", code)
                self._send(
                    404,
                    {"Errors": [{"Reason": DisconnectReason.GAME_NOT_FOUND}], "Game": None},
                )
            else:
                log.info("Någon letade efter spelkod %s och hittade det", code)
                self._send(200, {"Errors": None, "Game": self._listing(lobby)})

        elif path == "/favicon.ico":
            self._send(404, "")

        else:
            log.info("Okänd GET-förfrågan: %s", self.path)
            self._send(404, "Hittades inte")

    def do_POST(self) -> None:
        path, query = self._path()
        body = self._read_json()

        if path == "/api/user":
            # Spelet vill ha en "token". Vi kontrollerar ingenting, alla
            # får komma in. Token är JSON som är base64-kodad.
            body = body or {}
            username = body.get("Username", "?")
            log.info("Spelare '%s' hämtade en token (steg 1 av anslutningen, %s)", username, self._who())
            self.info.lobbies.waiting_for_udp[username] = (time.monotonic(), self._who())
            token = {
                "Content": {
                    "Puid": body.get("Puid", ""),
                    "ClientVersion": body.get("ClientVersion", 0),
                    "ExpiresAt": "2012-12-21T00:00:00",
                },
                "Hash": "emergency_meeting",
            }
            encoded = base64.b64encode(json.dumps(token).encode("utf-8")).decode("ascii")
            self._send(200, encoded, "text/plain; charset=utf-8")

        elif path == "/api/games":
            # Äldre sätt att leta efter ett spel med kod.
            try:
                code_int = int(parse_qs(query).get("gameId", ["-1"])[0])
            except ValueError:
                code_int = -1
            if self.info.lobbies.find(code_int) is None:
                self._send(404, {"Errors": [{"Reason": DisconnectReason.GAME_NOT_FOUND}]})
            else:
                self._send(200, self._host_server())

        else:
            log.info("Okänd POST-förfrågan: %s", self.path)
            self._send(404, "Hittades inte")

    def do_PUT(self) -> None:
        path, _query = self._path()
        # Spelet skickar med lite data här som inte är JSON. Vi behöver den
        # inte än, men måste läsa den så att anslutningen inte blir rörig.
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        log.debug("PUT %s med %d bytes: %s", self.path, len(body), body.hex(" "))

        if path == "/api/games":
            log.info(
                "Spelet vill skapa ett spel, vi skickar det till %s:%s (steg 2)",
                self.info.public_ip,
                self.config.port,
            )
            self._send(200, self._host_server())
        else:
            log.info("Okänd PUT-förfrågan: %s", self.path)
            self._send(404, "Hittades inte")


def start_matchmaker(info: ServerInfo) -> ThreadingHTTPServer:
    """Startar HTTP-servern i bakgrunden och returnerar den."""
    handler = type("ConfiguredHandler", (MatchmakerHandler,), {"info": info})
    httpd = ThreadingHTTPServer((info.config.listen_ip, info.config.port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    thread.start()
    return httpd
