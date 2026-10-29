"""
Hazel: the network layer Among Us uses on top of UDP.

UDP is fast, but packets can get lost on the way. Hazel solves it like this:

  - Important packets ("reliable") get a number. The receiver answers with a
    receipt (ack) with the same number. If no receipt comes, the packet is sent again.
  - Less important packets ("unreliable") are only sent once.
  - The game sends a "ping" now and then to check that the server is alive.

This file takes care of all of that, so that the rest of the server only
has to care about the messages themselves.
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
    """A connected player."""

    def __init__(self, server: "HazelServer", address: Address, handshake: Optional[Handshake]):
        self.server = server
        self.address = address
        self.handshake = handshake
        self.last_seen = time.monotonic()
        self.connected = True

        # Filled in by the game logic: the player's number and which lobby they are in.
        self.client_id = 0
        self.player: Optional[object] = None

        # Remembers the latest messages, in case something goes wrong.
        self.recorder = FlightRecorder()
        self._unknown_kinds_logged: Set[int] = set()

        self._next_id = 1
        # Packet numbers we have already received (to spot duplicates).
        self._received_ids: Set[int] = set()
        self._received_order: Deque[int] = deque()
        # Packets we have sent but not got a receipt for: id -> [data, time, tries]
        self._pending: Dict[int, list] = {}

    @property
    def name(self) -> str:
        return self.handshake.name if self.handshake else "?"

    def __str__(self) -> str:
        return f"{self.name} ({self.address[0]}:{self.address[1]})"

    # --- Ta emot ---------------------------------------------------------

    def remember_id(self, packet_id: int) -> bool:
        """Saves a packet number. Returns False if we have already seen it."""
        if packet_id in self._received_ids:
            return False
        self._received_ids.add(packet_id)
        self._received_order.append(packet_id)
        if len(self._received_order) > 512:
            self._received_ids.discard(self._received_order.popleft())
        return True

    def send_ack(self, packet_id: int) -> None:
        # The last byte tells which of the 8 previous packets we have also received.
        recent = 0
        for i in range(1, 9):
            if ((packet_id - i) & 0xFFFF) in self._received_ids:
                recent |= 1 << (i - 1)
        self.server.send_raw(
            bytes([protocol.ACK, packet_id >> 8, packet_id & 0xFF, recent]), self.address
        )
        self.recorder.last_ack_out = time.monotonic()

    def handle_ack(self, packet_id: int, recent: Optional[int]) -> None:
        if self._pending.pop(packet_id, None) is not None:
            self.recorder.note_text("in", f"receipt for our packet #{packet_id}")
        if recent is not None:
            for i in range(1, 9):
                if recent & (1 << (i - 1)):
                    self._pending.pop((packet_id - i) & 0xFFFF, None)

    # --- Send ------------------------------------------------------------

    def send_reliable(self, payload: bytes) -> None:
        packet_id = self._next_id
        self._next_id = (self._next_id + 1) & 0xFFFF
        packet = bytes([protocol.RELIABLE, packet_id >> 8, packet_id & 0xFF]) + payload
        self._pending[packet_id] = [packet, time.monotonic(), 0]
        self.recorder.note("out", payload, packet_id)
        self.server.send_raw(packet, self.address)

    def send_unreliable(self, payload: bytes) -> None:
        self.recorder.unreliable_out += 1
        self.server.send_raw(bytes([protocol.UNRELIABLE]) + payload, self.address)

    def disconnect(self, reason: int = protocol.DisconnectReason.EXIT_GAME, message: str = "") -> None:
        """
        Disconnects the player. With reason=CUSTOM, `message` is shown in the game.
        The packet looks like this:
            [0x09] [1 = "there is a reason"] [sub-message: reason (+ text)]
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
        self.server.forget(self, "the server disconnected the player")

    def resend_lost_packets(self, now: float) -> None:
        for packet_id, entry in list(self._pending.items()):
            packet, sent_at, tries = entry
            if now - sent_at < RESEND_AFTER_SECONDS:
                continue
            if tries >= MAX_RESENDS:
                log.warning("%s doesn't answer packet %d, giving up", self, packet_id)
                self.recorder.note_text("!!", f"the game never answered our packet {packet_id}")
                self._pending.pop(packet_id, None)
                continue
            entry[1] = now
            entry[2] = tries + 1
            self.recorder.note_text("out", f"sending packet #{packet_id} again (try {tries + 1})")
            self.server.send_raw(packet, self.address)


class HazelServer(asyncio.DatagramProtocol):
    """Listens on UDP and keeps track of all connected players."""

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

    # --- asyncio calls these automatically -------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, address: Address) -> None:
        try:
            self._handle_packet(data, address)
        except Exception:  # a broken player must not crash the whole server
            log.exception("Error while handling a packet from %s", address)

    # --- Packets in --------------------------------------------------------

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
            # We don't know this sender and it's not a Hello. Ignore it.
            return

        connection.last_seen = time.monotonic()
        connection.recorder.last_in = connection.last_seen

        if kind == protocol.RELIABLE and len(data) >= 3:
            packet_id = (data[1] << 8) | data[2]
            is_new = connection.remember_id(packet_id)
            connection.send_ack(packet_id)
            if is_new:
                connection.recorder.note("in", data[3:], packet_id)
                self._dispatch(connection, data[3:], reliable=True)
            else:
                connection.recorder.note_text("in", f"#{packet_id} again (the game resent it, new receipt sent)")

        elif kind == protocol.UNRELIABLE:
            connection.recorder.unreliable_in += 1
            self._dispatch(connection, data[1:], reliable=False)

        elif kind == protocol.PING and len(data) >= 3:
            packet_id = (data[1] << 8) | data[2]
            connection.remember_id(packet_id)
            connection.send_ack(packet_id)
            connection.recorder.note_text("in", f"ping #{packet_id} -> ack sent")

        elif kind == protocol.ACK and len(data) >= 3:
            packet_id = (data[1] << 8) | data[2]
            recent = data[3] if len(data) >= 4 else None
            connection.handle_ack(packet_id, recent)

        elif kind == protocol.DISCONNECT:
            why = self._disconnect_reason(data)
            connection.recorder.note_text("in", f"Disconnect: {why}")
            self.forget(connection, why)

        elif kind not in connection._unknown_kinds_logged:
            # Something we don't understand. Write it once, it can explain problems.
            connection._unknown_kinds_logged.add(kind)
            log.warning(
                "%s sent a packet type the server doesn't know (0x%02x, %d bytes)",
                connection,
                kind,
                len(data),
            )
            connection.recorder.note_text("in", f"unknown packet type 0x{kind:02x}: {data[:24].hex(' ')}")

    @staticmethod
    def _disconnect_reason(data: bytes) -> str:
        """Reads why the game disconnected, if it sent a reason."""
        if len(data) < 2:
            return "the player left"
        try:
            reader = MessageReader(data[1:])
            if reader.read_byte() != 1:
                return "the player left (forced, without a reason)"
            inner = reader.read_message()
            reason = inner.read_byte()
            text = protocol.DISCONNECT_REASON_NAMES.get(reason, f"reason {reason}")
            if inner.remaining:
                text += f": {inner.read_string()}"
            return f"the game disconnected: {text}"
        except ValueError:
            return f"the player left ({data[1:20].hex(' ')})"

    def _handle_hello(self, data: bytes, address: Address, connection: Optional[Connection]) -> None:
        if len(data) < 4:
            return
        packet_id = (data[1] << 8) | data[2]

        if connection is not None:
            # The same Hello again (our receipt probably got lost). Just answer again.
            connection.send_ack(packet_id)
            return

        hazel_version = data[3]
        handshake = try_parse_handshake(hazel_version, data[4:])
        connection = Connection(self, address, handshake)
        connection.remember_id(packet_id)
        self.connections[address] = connection
        connection.send_ack(packet_id)

        if handshake is None:
            log.warning("Could not read the Hello packet from %s: %s", address, data.hex(" "))
        self.on_connect(connection)

    def _dispatch(self, connection: Connection, payload: bytes, reliable: bool) -> None:
        reader = MessageReader(payload)
        for message in reader.messages():
            self.on_message(connection, message, reliable)

    # --- Packets out and cleaning up ------------------------------------------

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
        """Runs all the time: resends lost packets and removes quiet players."""
        while True:
            await asyncio.sleep(0.1)
            now = time.monotonic()
            for connection in list(self.connections.values()):
                if now - connection.last_seen > TIMEOUT_SECONDS:
                    self.forget(connection, "no contact for a while (timeout)")
                else:
                    connection.resend_lost_packets(now)
