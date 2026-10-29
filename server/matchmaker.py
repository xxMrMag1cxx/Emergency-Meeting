"""
HTTP matchmaking: the game's "switchboard".

Before Among Us connects to the game server itself (UDP), the game asks
over ordinary HTTP, the same kind of traffic a web page uses:

  1. POST /api/user         "Can I have a login ticket (token)?"
  2. PUT  /api/games        "Where should I create my game?"  -> our IP + port
  3. GET  /api/games/<code> "Where is the game with this code?"
  4. GET  /api/games/filtered and /api/filters
                            "Which public games are there?"

Then the game connects over UDP to the address we gave it.

Among Us requires HTTPS if the game runs on another device than the server.
We solve that with a tunnel (see ngrok.py and tunnel.py): the tunnel takes
HTTPS from the internet and passes it on as ordinary HTTP to here.
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
from .i18n import tr
from .lobby import Lobby, LobbyManager
from .protocol import DisconnectReason
from .region import region_info_json
from .webpage import games_json, render

log = logging.getLogger("http")


def ip_to_number(ip: str) -> int:
    """Among Us wants the IP address as a single number (bytes in reverse order)."""
    return struct.unpack("<I", socket.inet_aton(ip))[0]


class ServerInfo:
    """Things the HTTP part needs to know and that can change while the server runs."""

    def __init__(self, config: Config, public_ip: str, lobbies: LobbyManager):
        self.config = config
        self.public_ip = public_ip
        self.lobbies = lobbies
        self.tunnel_url = ""  # filled in when the tunnel is running
        self.fixed_url = ""  # the ngrok address (the same every time), when it is running
        # The game's address through playit.gg (ip, port), when it is ready.
        self.playit_endpoint: Optional[Tuple[str, int]] = None
        self.playit_address = ""

    def set_playit(self, address: str, ip: str, port: int) -> None:
        self.playit_address = address
        self.playit_endpoint = (ip, port)

    def game_endpoint(self, via_internet: bool) -> Tuple[str, int]:
        """
        The address (ip, port) the game should connect to with UDP. Those who
        come through the HTTPS tunnel get the playit address (works everywhere),
        those who ask directly on the home network get the Mac's address.
        """
        endpoint = self.playit_endpoint
        if via_internet and endpoint is not None:
            return endpoint
        return self.public_ip, self.config.port


class MatchmakerHandler(BaseHTTPRequestHandler):
    # Set by start_matchmaker() below.
    info: ServerInfo

    server_version = "EmergencyMeeting"
    protocol_version = "HTTP/1.1"
    timeout = 30  # seconds before a quiet connection is closed

    @property
    def config(self) -> Config:
        return self.info.config

    # --- Troubleshooting ------------------------------------------------------

    def handle(self) -> None:
        # Peek at the first byte before we read anything. HTTPS (TLS) always
        # starts with byte 0x16, ordinary HTTP starts with a letter (GET, PUT...).
        try:
            first = self.connection.recv(1, socket.MSG_PEEK)
        except OSError:
            return
        if first == b"\x16":
            log.warning(
                "%s tried to connect with HTTPS directly to port %s. "
                "That doesn't work, use the HTTPS address from the tunnel instead.",
                self.client_address[0],
                self.config.port,
            )
            return
        super().handle()

    def log_message(self, format: str, *args: Any) -> None:
        # Turn off the built-in logging, we log ourselves below.
        pass

    def log_error(self, format: str, *args: Any) -> None:
        text = format % args
        if "timed out" in text:
            # cloudflared keeps connections open "just in case". When they have
            # been quiet for a while we close them. That's completely normal.
            log.debug("Closed a quiet connection from %s", self.client_address[0])
            return
        log.warning("HTTP error from %s: %s", self.client_address[0], text)

    # --- Helpers -------------------------------------------------

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
            log.warning("Got invalid JSON: %r", raw[:200])
            return None

    def _path(self) -> Tuple[str, str]:
        parsed = urlparse(self.path)
        return parsed.path.rstrip("/") or "/", parsed.query

    def _via_https(self) -> bool:
        """Did the request come through a tunnel (HTTPS) or directly (HTTP)?"""
        if self.headers.get("X-Forwarded-Proto", "").lower() == "https":
            return True  # ngrok and Cloudflare
        return '"https"' in self.headers.get("Cf-Visitor", "")

    def _public_address(self) -> Tuple[str, int, bool]:
        """The address the game should use, as seen from the one asking."""
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or self.info.public_ip)
        host = host.split(",")[0].strip().split(":")[0]
        if self._via_https():
            if host in ("localhost", "127.0.0.1") and self.info.tunnel_url:
                return self.info.tunnel_url, 443, True
            return f"https://{host}", 443, True
        return f"http://{host}", self.config.port, False

    def _listing(self, lobby: Lobby) -> dict:
        """The description of a game that is shown in the game's list."""
        host = lobby.host
        hs = host.connection.handshake if host else None
        ip, port = self.info.game_endpoint(self._via_https())
        return {
            "IP": ip_to_number(ip),
            "Port": port,
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
        ip, port = self.info.game_endpoint(self._via_https())
        return {"Ip": ip_to_number(ip), "Port": port}

    def _who(self) -> str:
        via = tr("through the HTTPS tunnel") if self._via_https() else tr("directly")
        forwarded = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        ip = self.headers.get("Cf-Connecting-Ip") or forwarded or self.client_address[0]
        return f"{ip}, {via}"

    # --- Requests ---------------------------------------------------

    def do_GET(self) -> None:
        path, _query = self._path()
        log.debug("GET %s (%s)", self.path, self._who())

        if path == "/":
            url, port, is_https = self._public_address()
            log.info("Someone opened the join page (%s)", self._who())
            page = render(
                self.config.server_name, url, port, is_https, self.info.tunnel_url,
                show_games=self.config.page_shows_games,
                playable_from_home=self.info.playit_endpoint is not None,
            )
            self._send(200, page, "text/html; charset=utf-8")

        elif path == "/games.json":
            # The list of games on the join page (fetched every five seconds)
            self._send(200, games_json(self.info.lobbies.all(), self.config.page_shows_games))

        elif path == "/regionInfo.json":
            url, port, _ = self._public_address()
            log.info("Someone downloaded regionInfo.json (%s)", self._who())
            self._send(200, region_info_json(self.config.server_name, url, port), "application/json")

        elif path == "/ping":
            self._send(200, "pong")

        elif path == "/api/filters":
            self._send(200, {"filters": ["Tags", "NumImposters"]})

        elif path in ("/api/games", "/api/games/filtered"):
            # The list of public games ("Find Game" in the game).
            listings = [self._listing(lobby) for lobby in self.info.lobbies.public_lobbies()]
            log.info("The game asked for public games (%d of them)", len(listings))
            if path.endswith("filtered"):
                total = len(self.info.lobbies.all())
                self._send(
                    200,
                    {"games": listings, "metadata": {"allGamesCount": total, "matchingGamesCount": len(listings)}},
                )
            else:
                self._send(200, listings)

        elif path.startswith("/api/games/"):
            # "Where is the game with this code?" (when you type in a code)
            try:
                code_int = int(path.rsplit("/", 1)[-1])
            except ValueError:
                code_int = -1
            lobby = self.info.lobbies.find(code_int)
            code = gamecode.int_to_code(code_int) if code_int != -1 else "?"
            if lobby is None:
                log.info("Someone looked for the game code %s, but that game doesn't exist", code)
                self._send(
                    404,
                    {"Errors": [{"Reason": DisconnectReason.GAME_NOT_FOUND}], "Game": None},
                )
            else:
                log.info("Someone looked for the game code %s and found it", code)
                self._send(200, {"Errors": None, "Game": self._listing(lobby)})

        elif path == "/favicon.ico" or path.startswith("/apple-touch-icon"):
            self._send(404, "")  # icons that browsers look for by themselves

        else:
            log.info("Unknown GET request: %s", self.path)
            self._send(404, "Not found")

    def do_POST(self) -> None:
        path, query = self._path()
        body = self._read_json()

        if path == "/api/user":
            # The game wants a "token". We don't check anything, everyone
            # gets in. The token is JSON that is base64 encoded.
            body = body or {}
            username = body.get("Username", "?")
            log.info("Player '%s' fetched a token (step 1 of connecting, %s)", username, self._who())
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
            # An older way of looking for a game by code.
            try:
                code_int = int(parse_qs(query).get("gameId", ["-1"])[0])
            except ValueError:
                code_int = -1
            if self.info.lobbies.find(code_int) is None:
                self._send(404, {"Errors": [{"Reason": DisconnectReason.GAME_NOT_FOUND}]})
            else:
                self._send(200, self._host_server())

        else:
            log.info("Unknown POST request: %s", self.path)
            self._send(404, "Not found")

    def do_PUT(self) -> None:
        path, _query = self._path()
        # The game sends some data here that isn't JSON. We don't need it
        # yet, but have to read it so that the connection doesn't get messed up.
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        log.debug("PUT %s with %d bytes: %s", self.path, len(body), body.hex(" "))

        if path == "/api/games":
            ip, port = self.info.game_endpoint(self._via_https())
            via = tr(" through playit.gg") if (ip, port) == self.info.playit_endpoint else ""
            log.info("The game wants to create a game, we send it to %s:%s%s (step 2)", ip, port, via)
            self._send(200, self._host_server())
        else:
            log.info("Unknown PUT request: %s", self.path)
            self._send(404, "Not found")


def start_matchmaker(info: ServerInfo) -> ThreadingHTTPServer:
    """Starts the HTTP server in the background and returns it."""
    handler = type("ConfiguredHandler", (MatchmakerHandler,), {"info": info})
    httpd = ThreadingHTTPServer((info.config.listen_ip, info.config.port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    thread.start()
    return httpd
