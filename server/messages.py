"""
Läsa och skriva Among Us-meddelanden.

Among Us skickar allt som bytes (ettor och nollor). Den här filen
innehåller två hjälpklasser:

  - MessageReader: plockar ut tal, text och delmeddelanden ur bytes
  - MessageWriter: bygger ihop bytes som vi vill skicka

Ett "meddelande" i Among Us ser ut så här:

    [längd: 2 bytes] [tagg: 1 byte] [innehåll: <längd> bytes]

Taggen säger vad det är för sorts meddelande, t.ex. 0 = "skapa spel".
"""

from __future__ import annotations

import struct
from typing import Iterator, List, Optional


class MessageReader:
    """Läser data ur en bit bytes, steg för steg från början till slut."""

    def __init__(self, data: bytes, tag: Optional[int] = None):
        self.data = data
        self.pos = 0
        self.tag = tag

    @property
    def remaining(self) -> int:
        return len(self.data) - self.pos

    def _take(self, count: int) -> bytes:
        if self.remaining < count:
            raise ValueError(
                f"Försökte läsa {count} bytes men bara {self.remaining} finns kvar"
            )
        chunk = self.data[self.pos : self.pos + count]
        self.pos += count
        return chunk

    def read_byte(self) -> int:
        return self._take(1)[0]

    def read_bool(self) -> bool:
        return self.read_byte() != 0

    def read_uint16(self) -> int:
        return struct.unpack("<H", self._take(2))[0]

    def read_uint32(self) -> int:
        return struct.unpack("<I", self._take(4))[0]

    def read_int32(self) -> int:
        return struct.unpack("<i", self._take(4))[0]

    def read_uint64(self) -> int:
        return struct.unpack("<Q", self._take(8))[0]

    def read_packed_uint32(self) -> int:
        """
        "Packade" tal sparar plats: små tal tar 1 byte, stora tar fler.
        Varje byte bär 7 bitar av talet. Den översta biten säger
        "det kommer en byte till".
        """
        result = 0
        shift = 0
        while True:
            b = self.read_byte()
            result |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                return result

    def read_string(self) -> str:
        length = self.read_packed_uint32()
        return self._take(length).decode("utf-8", errors="replace")

    def read_bytes(self, count: int) -> bytes:
        return self._take(count)

    def read_rest(self) -> bytes:
        return self._take(self.remaining)

    def read_message(self) -> "MessageReader":
        """Läser ett delmeddelande: [längd 2][tagg 1][innehåll]."""
        length = self.read_uint16()
        tag = self.read_byte()
        return MessageReader(self._take(length), tag=tag)

    def messages(self) -> Iterator["MessageReader"]:
        """Går igenom alla delmeddelanden som finns kvar, ett i taget."""
        while self.remaining >= 3:
            yield self.read_message()


class MessageWriter:
    """Bygger ihop bytes som ska skickas till spelet."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        # Här kommer vi ihåg var varje påbörjat delmeddelande startar,
        # så att vi kan fylla i längden när det är klart.
        self._open_messages: List[int] = []

    def write_byte(self, value: int) -> "MessageWriter":
        self.buffer.append(value & 0xFF)
        return self

    def write_bool(self, value: bool) -> "MessageWriter":
        return self.write_byte(1 if value else 0)

    def write_uint16(self, value: int) -> "MessageWriter":
        self.buffer += struct.pack("<H", value)
        return self

    def write_uint32(self, value: int) -> "MessageWriter":
        self.buffer += struct.pack("<I", value)
        return self

    def write_int32(self, value: int) -> "MessageWriter":
        self.buffer += struct.pack("<i", value)
        return self

    def write_packed_uint32(self, value: int) -> "MessageWriter":
        while True:
            b = value & 0x7F
            value >>= 7
            if value:
                self.buffer.append(b | 0x80)
            else:
                self.buffer.append(b)
                return self

    def write_string(self, text: str) -> "MessageWriter":
        encoded = text.encode("utf-8")
        self.write_packed_uint32(len(encoded))
        self.buffer += encoded
        return self

    def write_bytes(self, data: bytes) -> "MessageWriter":
        self.buffer += data
        return self

    def start_message(self, tag: int) -> "MessageWriter":
        self._open_messages.append(len(self.buffer))
        self.buffer += b"\x00\x00"  # plats för längden, fylls i senare
        self.buffer.append(tag)
        return self

    def end_message(self) -> "MessageWriter":
        start = self._open_messages.pop()
        length = len(self.buffer) - start - 3
        self.buffer[start : start + 2] = struct.pack("<H", length)
        return self

    def to_bytes(self) -> bytes:
        if self._open_messages:
            raise ValueError("Ett meddelande startades men avslutades aldrig")
        return bytes(self.buffer)
