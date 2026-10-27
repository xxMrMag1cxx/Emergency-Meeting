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
"""

from __future__ import annotations

import base64
import json
import logging
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional, Tuple
from urllib.parse import urlparse

from .config import Config
from .protocol import DisconnectReason

log = logging.getLogger("http")


def ip_to_number(ip: str) -> int:
    """Among Us vill ha IP-adressen som ett enda tal (bytes i omvänd ordning)."""
    return struct.unpack("<I", socket.inet_aton(ip))[0]


class MatchmakerHandler(BaseHTTPRequestHandler):
    # Sätts av start_matchmaker() nedan.
    config: Config
    public_ip: str

    server_version = "EmergencyMeeting"
    protocol_version = "HTTP/1.1"

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

    def log_message(self, format: str, *args: Any) -> None:
        # Stäng av den inbyggda loggningen, vi loggar själva nedan.
        pass

    def _host_server(self) -> dict:
        return {"Ip": ip_to_number(self.public_ip), "Port": self.config.port}

    # --- Förfrågningar ---------------------------------------------------

    def do_GET(self) -> None:
        path, _query = self._path()
        log.debug("GET %s från %s", self.path, self.client_address[0])

        if path == "/":
            log.info("Någon öppnade startsidan från %s", self.client_address[0])
            self._send(
                200,
                f"{self.config.server_name} är igång!\n"
                "Lägg till servern i Among Us för att ansluta.\n",
                "text/plain; charset=utf-8",
            )

        elif path == "/api/filters":
            self._send(200, {"filters": ["Tags", "NumImposters"]})

        elif path in ("/api/games", "/api/games/filtered"):
            # Inga offentliga spel än: vi skickar en tom lista.
            log.info("Spelet frågade efter offentliga spel (inga finns än)")
            if path.endswith("filtered"):
                self._send(
                    200,
                    {"games": [], "metadata": {"allGamesCount": 0, "matchingGamesCount": 0}},
                )
            else:
                self._send(200, [])

        elif path.startswith("/api/games/"):
            code = path.rsplit("/", 1)[-1]
            log.info("Spelet letar efter spelkod %s (vi har inga spel än)", code)
            self._send(
                404,
                {"Errors": [{"Reason": DisconnectReason.GAME_NOT_FOUND}], "Game": None},
            )

        else:
            log.info("Okänd GET-förfrågan: %s", self.path)
            self._send(404, "Hittades inte")

    def do_POST(self) -> None:
        path, _query = self._path()
        body = self._read_json()

        if path == "/api/user":
            # Spelet vill ha en "token". Vi kontrollerar ingenting, alla
            # får komma in. Token är JSON som är base64-kodad.
            body = body or {}
            username = body.get("Username", "?")
            log.info("Spelare '%s' hämtade en token (steg 1 av anslutningen)", username)
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
            # Äldre sätt att leta efter ett spel. Inga spel finns än.
            self._send(404, {"Errors": [{"Reason": DisconnectReason.GAME_NOT_FOUND}]})

        else:
            log.info("Okänd POST-förfrågan: %s", self.path)
            self._send(404, "Hittades inte")

    def do_PUT(self) -> None:
        path, _query = self._path()
        self._read_json()

        if path == "/api/games":
            log.info(
                "Spelet vill skapa ett spel, vi skickar det till %s:%s (steg 2)",
                self.public_ip,
                self.config.port,
            )
            self._send(200, self._host_server())
        else:
            log.info("Okänd PUT-förfrågan: %s", self.path)
            self._send(404, "Hittades inte")


def start_matchmaker(config: Config, public_ip: str) -> ThreadingHTTPServer:
    """Startar HTTP-servern i bakgrunden och returnerar den."""
    handler = type(
        "ConfiguredHandler",
        (MatchmakerHandler,),
        {"config": config, "public_ip": public_ip},
    )
    httpd = ThreadingHTTPServer((config.listen_ip, config.port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    thread.start()
    return httpd
