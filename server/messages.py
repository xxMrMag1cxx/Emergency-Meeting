"""
Reading and writing Among Us messages.

Among Us sends everything as bytes (ones and zeros). This file
contains two helper classes:

  - MessageReader: picks numbers, text and sub-messages out of bytes
  - MessageWriter: puts together bytes that we want to send

A "message" in Among Us looks like this:

    [length: 2 bytes] [tag: 1 byte] [content: <length> bytes]

The tag says what kind of message it is, for example 0 = "host game".
"""

from __future__ import annotations

import struct
from typing import Iterator, List, Optional, Tuple

# Positions are sent as two numbers between 0 and 65535 that mean -50 to 50.
VECTOR_RANGE = 50.0


class MessageReader:
    """Reads data from a piece of bytes, step by step from start to end."""

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
                f"Tried to read {count} bytes but only {self.remaining} are left"
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

    def read_int16(self) -> int:
        return struct.unpack("<h", self._take(2))[0]

    def read_float(self) -> float:
        return struct.unpack("<f", self._take(4))[0]

    def read_uint32(self) -> int:
        return struct.unpack("<I", self._take(4))[0]

    def read_int32(self) -> int:
        return struct.unpack("<i", self._take(4))[0]

    def read_uint64(self) -> int:
        return struct.unpack("<Q", self._take(8))[0]

    def read_packed_uint32(self) -> int:
        """
        "Packed" numbers save space: small numbers take 1 byte, big ones take more.
        Every byte carries 7 bits of the number. The top bit says
        "another byte is coming".
        """
        result = 0
        shift = 0
        while True:
            b = self.read_byte()
            result |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                return result

    def read_packed_int32(self) -> int:
        """Like read_packed_uint32, but can be negative (for example -4)."""
        value = self.read_packed_uint32() & 0xFFFFFFFF
        return value - (1 << 32) if value >= (1 << 31) else value

    def read_vector2(self) -> Tuple[float, float]:
        """A position on the map: two numbers 0-65535 that mean -50 to 50."""
        x = self.read_uint16() / 65535.0
        y = self.read_uint16() / 65535.0
        return (-VECTOR_RANGE + 2 * VECTOR_RANGE * x, -VECTOR_RANGE + 2 * VECTOR_RANGE * y)

    def read_string(self) -> str:
        length = self.read_packed_uint32()
        return self._take(length).decode("utf-8", errors="replace")

    def read_bytes(self, count: int) -> bytes:
        return self._take(count)

    def read_rest(self) -> bytes:
        return self._take(self.remaining)

    def read_message(self) -> "MessageReader":
        """Reads a sub-message: [length 2][tag 1][content]."""
        length = self.read_uint16()
        tag = self.read_byte()
        return MessageReader(self._take(length), tag=tag)

    def messages(self) -> Iterator["MessageReader"]:
        """Goes through all sub-messages that are left, one at a time."""
        while self.remaining >= 3:
            yield self.read_message()


class MessageWriter:
    """Puts together bytes that will be sent to the game."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        # Here we remember where every started sub-message begins,
        # so that we can fill in the length when it's done.
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

    def write_packed_int32(self, value: int) -> "MessageWriter":
        # Negative numbers are written as big positive ones, just like in the game.
        return self.write_packed_uint32(value & 0xFFFFFFFF)

    def write_message(self, message: "MessageReader") -> "MessageWriter":
        """Writes back a whole message we have received (to pass it on)."""
        self.start_message(message.tag or 0)
        self.write_bytes(message.data)
        return self.end_message()

    def write_vector2(self, x: float, y: float) -> "MessageWriter":
        for value in (x, y):
            t = min(1.0, max(0.0, (value + VECTOR_RANGE) / (2 * VECTOR_RANGE)))
            self.write_uint16(int(t * 65535))
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
        self.buffer += b"\x00\x00"  # space for the length, filled in later
        self.buffer.append(tag)
        return self

    def end_message(self) -> "MessageWriter":
        start = self._open_messages.pop()
        length = len(self.buffer) - start - 3
        self.buffer[start : start + 2] = struct.pack("<H", length)
        return self

    def to_bytes(self) -> bytes:
        if self._open_messages:
            raise ValueError("A message was started but never ended")
        return bytes(self.buffer)
