"""
Hazel: nätverkslagret som Among Us använder ovanpå UDP.

UDP är snabbt, men paket kan försvinna på vägen. Hazel löser det så här:

  - Viktiga paket ("reliable") får ett nummer. Mottagaren svarar med ett
    kvitto (ack) med samma nummer. Kommer inget kvitto skickas paketet igen.
  - Mindre viktiga paket ("unreliable") skickas bara en gång.
  - Spelet skickar "ping" då och då för att se att servern lever.

Den här filen tar hand om allt det, så att resten av servern bara
behöver bry sig om själva meddelandena.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional, Set, Tuple

from . import protocol
from .blackbox import FlightRecorder
from .handshake import Handshake, try_parse_handshake
from .messages import MessageReader, MessageWriter

log = logging.getLogger("udp")

Address = Tuple[str, int]

RESEND_AFTER_SECONDS = 0.3
MAX_RESENDS = 10
TIMEOUT_SECONDS = 15.0


class Connection:
    """En ansluten spelare."""

    def __init__(self, server: "HazelServer", address: Address, handshake: Optional[Handshake]):
        self.server = server
        self.address = address
        self.handshake = handshake
        self.last_seen = time.monotonic()
        self.connected = True

        # Fylls i av spellogiken: spelarens nummer och vilken lobby hen är i.
        self.client_id = 0
        self.player: Optional[object] = None

        # Kommer ihåg de senaste meddelandena, om något går fel.
        self.recorder = FlightRecorder()
        self._unknown_kinds_logged: Set[int] = set()

        self._next_id = 1
        # Paketnummer vi redan har tagit emot (för att upptäcka dubbletter).
        self._received_ids: Set[int] = set()
        self._received_order: Deque[int] = deque()
        # Paket vi har skickat men inte fått kvitto på: id -> [data, tid, försök]
        self._pending: Dict[int, list] = {}

    @property
    def name(self) -> str:
        return self.handshake.name if self.handshake else "?"

    def __str__(self) -> str:
        return f"{self.name} ({self.address[0]}:{self.address[1]})"

    # --- Ta emot ---------------------------------------------------------

    def remember_id(self, packet_id: int) -> bool:
        """Sparar ett paketnummer. Returnerar False om vi redan sett det."""
        if packet_id in self._received_ids:
            return False
        self._received_ids.add(packet_id)
        self._received_order.append(packet_id)
        if len(self._received_order) > 512:
            self._received_ids.discard(self._received_order.popleft())
        return True

    def send_ack(self, packet_id: int) -> None:
        # Sista byten berättar vilka av de 8 föregående paketen vi också har fått.
        recent = 0
        for i in range(1, 9):
            if ((packet_id - i) & 0xFFFF) in self._received_ids:
                recent |= 1 << (i - 1)
        self.server.send_raw(
            bytes([protocol.ACK, packet_id >> 8, packet_id & 0xFF, recent]), self.address
        )

    def handle_ack(self, packet_id: int, recent: Optional[int]) -> None:
        self._pending.pop(packet_id, None)
        if recent is not None:
            for i in range(1, 9):
                if recent & (1 << (i - 1)):
                    self._pending.pop((packet_id - i) & 0xFFFF, None)

    # --- Skicka ----------------------------------------------------------

    def send_reliable(self, payload: bytes) -> None:
        packet_id = self._next_id
        self._next_id = (self._next_id + 1) & 0xFFFF
        packet = bytes([protocol.RELIABLE, packet_id >> 8, packet_id & 0xFF]) + payload
        self._pending[packet_id] = [packet, time.monotonic(), 0]
        self.recorder.note("ut", payload)
        self.server.send_raw(packet, self.address)

    def send_unreliable(self, payload: bytes) -> None:
        self.server.send_raw(bytes([protocol.UNRELIABLE]) + payload, self.address)

    def disconnect(self, reason: int = protocol.DisconnectReason.EXIT_GAME, message: str = "") -> None:
        """
        Kopplar bort spelaren. Med reason=CUSTOM visas `message` i spelet.
        Paketet ser ut så här:
            [0x09] [1 = "det finns en anledning"] [delmeddelande: anledning (+ text)]
        """
        if not self.connected:
            return
        writer = MessageWriter()
        writer.write_byte(protocol.DISCONNECT)
        writer.write_bool(True)
        writer.start_message(0)
        writer.write_byte(reason)
        if reason == protocol.DisconnectReason.CUSTOM:
            writer.write_string(message)
        writer.end_message()
        self.server.send_raw(writer.to_bytes(), self.address)
        self.server.forget(self, "servern kopplade bort spelaren")

    def resend_lost_packets(self, now: float) -> None:
        for packet_id, entry in list(self._pending.items()):
            packet, sent_at, tries = entry
            if now - sent_at < RESEND_AFTER_SECONDS:
                continue
            if tries >= MAX_RESENDS:
                log.warning("%s svarar inte på paket %d, ger upp", self, packet_id)
                self.recorder.note_text("!!", f"spelet svarade aldrig på vårt paket {packet_id}")
                self._pending.pop(packet_id, None)
                continue
            entry[1] = now
            entry[2] = tries + 1
            self.server.send_raw(packet, self.address)


class HazelServer(asyncio.DatagramProtocol):
    """Lyssnar på UDP och håller koll på alla anslutna spelare."""

    def __init__(
        self,
        on_connect: Callable[[Connection], None],
        on_message: Callable[[Connection, MessageReader, bool], None],
        on_disconnect: Callable[[Connection, str], None],
        debug: bool = False,
    ):
        self.on_connect = on_connect
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self.debug = debug
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.connections: Dict[Address, Connection] = {}

    # --- asyncio anropar dessa automatiskt -------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, address: Address) -> None:
        try:
            self._handle_packet(data, address)
        except Exception:  # en trasig spelare ska inte krascha hela servern
            log.exception("Fel när ett paket från %s hanterades", address)

    # --- Paket in --------------------------------------------------------

    def _handle_packet(self, data: bytes, address: Address) -> None:
        if not data:
            return

        kind = data[0]
        if self.debug:
            log.debug(
                "<- %s %s: %s",
                address[0],
                protocol.PACKET_NAMES.get(kind, hex(kind)),
                data.hex(" "),
            )

        connection = self.connections.get(address)

        if kind == protocol.HELLO:
            self._handle_hello(data, address, connection)
            return

        if connection is None:
            # Vi känner inte den här avsändaren och det är inget Hello. Ignorera.
            return

        connection.last_seen = time.monotonic()

        if kind == protocol.RELIABLE and len(data) >= 3:
            packet_id = (data[1] << 8) | data[2]
            is_new = connection.remember_id(packet_id)
            connection.send_ack(packet_id)
            if is_new:
                connection.recorder.note("in", data[3:])
                self._dispatch(connection, data[3:], reliable=True)

        elif kind == protocol.UNRELIABLE:
            self._dispatch(connection, data[1:], reliable=False)

        elif kind == protocol.PING and len(data) >= 3:
            packet_id = (data[1] << 8) | data[2]
            connection.remember_id(packet_id)
            connection.send_ack(packet_id)

        elif kind == protocol.ACK and len(data) >= 3:
            packet_id = (data[1] << 8) | data[2]
            recent = data[3] if len(data) >= 4 else None
            connection.handle_ack(packet_id, recent)

        elif kind == protocol.DISCONNECT:
            why = self._disconnect_reason(data)
            connection.recorder.note_text("in", f"Disconnect: {why}")
            self.forget(connection, why)

        elif kind not in connection._unknown_kinds_logged:
            # Något vi inte förstår. Skriv ut det en gång, det kan förklara problem.
            connection._unknown_kinds_logged.add(kind)
            log.warning(
                "%s skickade en pakettyp som servern inte känner till (0x%02x, %d bytes)",
                connection,
                kind,
                len(data),
            )
            connection.recorder.note_text("in", f"okänd pakettyp 0x{kind:02x}: {data[:24].hex(' ')}")

    @staticmethod
    def _disconnect_reason(data: bytes) -> str:
        """Läser varför spelet kopplade från, om det skickade med en anledning."""
        if len(data) < 2:
            return "spelaren lämnade"
        try:
            reader = MessageReader(data[1:])
            if reader.read_byte() != 1:
                return "spelaren lämnade (tvingad, utan anledning)"
            inner = reader.read_message()
            reason = inner.read_byte()
            text = protocol.DISCONNECT_REASON_NAMES.get(reason, f"anledning {reason}")
            if inner.remaining:
                text += f": {inner.read_string()}"
            return f"spelet kopplade från: {text}"
        except ValueError:
            return f"spelaren lämnade ({data[1:20].hex(' ')})"

    def _handle_hello(self, data: bytes, address: Address, connection: Optional[Connection]) -> None:
        if len(data) < 4:
            return
        packet_id = (data[1] << 8) | data[2]

        if connection is not None:
            # Samma Hello igen (vårt kvitto försvann nog). Svara bara igen.
            connection.send_ack(packet_id)
            return

        hazel_version = data[3]
        handshake = try_parse_handshake(hazel_version, data[4:])
        connection = Connection(self, address, handshake)
        connection.remember_id(packet_id)
        self.connections[address] = connection
        connection.send_ack(packet_id)

        if handshake is None:
            log.warning("Kunde inte läsa Hello-paketet från %s: %s", address, data.hex(" "))
        self.on_connect(connection)

    def _dispatch(self, connection: Connection, payload: bytes, reliable: bool) -> None:
        reader = MessageReader(payload)
        for message in reader.messages():
            self.on_message(connection, message, reliable)

    # --- Paket ut och städning ------------------------------------------

    def send_raw(self, data: bytes, address: Address) -> None:
        if self.transport is not None:
            if self.debug:
                log.debug("-> %s: %s", address[0], data.hex(" "))
            self.transport.sendto(data, address)

    def forget(self, connection: Connection, why: str) -> None:
        if self.connections.pop(connection.address, None) is not None:
            connection.connected = False
            self.on_disconnect(connection, why)

    async def maintenance_loop(self) -> None:
        """Körs hela tiden: skickar om tappade paket och rensar bort tysta spelare."""
        while True:
            await asyncio.sleep(0.1)
            now = time.monotonic()
            for connection in list(self.connections.values()):
                if now - connection.last_seen > TIMEOUT_SECONDS:
                    self.forget(connection, "ingen kontakt på en stund (timeout)")
                else:
                    connection.resend_lost_packets(now)
