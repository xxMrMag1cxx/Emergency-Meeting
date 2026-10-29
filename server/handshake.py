"""
Reads the game's "Hello" packet, the very first packet that the
game sends when it connects to the server.

It contains among other things the player's name, game version and platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import protocol
from .messages import MessageReader

# The dates when Among Us added new fields to the Hello packet.
# Older games send fewer fields, so we check the version before we read.
V1 = protocol.encode_game_version(2021, 4, 25)
V2 = protocol.encode_game_version(2021, 6, 30)
V3 = protocol.encode_game_version(2021, 11, 9)
V4 = protocol.encode_game_version(2021, 12, 14)


@dataclass
class Handshake:
    hazel_version: int
    game_version: int
    name: str = ""
    language: int = 0
    chat_mode: int = 0
    platform: int = 0
    platform_name: str = ""
    # The platform part exactly as it came, so that we can pass it on
    # to the other players in the lobby.
    platform_raw: bytes = b""
    extra_bytes: bytes = b""

    @property
    def game_version_text(self) -> str:
        return protocol.decode_game_version(self.game_version)

    @property
    def platform_text(self) -> str:
        return protocol.PLATFORMS.get(self.platform, f"Platform {self.platform}")


def parse_handshake(hazel_version: int, data: bytes) -> Handshake:
    """
    `data` is everything after the first four bytes of the Hello packet:
        [0x08] [packet number: 2 bytes] [hazel version: 1 byte] [data...]
    """
    reader = MessageReader(data)
    hs = Handshake(hazel_version=hazel_version, game_version=reader.read_int32())

    hs.name = reader.read_string()

    if hs.game_version >= V1:
        reader.read_uint32()  # "lastNonceReceived", always 0 nowadays

    if hs.game_version >= V2:
        hs.language = reader.read_uint32()
        hs.chat_mode = reader.read_byte()

    if hs.game_version >= V3:
        platform = reader.read_message()
        hs.platform = platform.tag or 0
        hs.platform_raw = platform.data
        hs.platform_name = platform.read_string()
        reader.read_int32()  # "crossplayFlags", not used yet

    if hs.game_version >= V4:
        reader.read_byte()  # unknown meaning, always 0

    # If newer versions of the game send more data we save it,
    # so that we can look at it in the log.
    hs.extra_bytes = reader.read_rest()
    return hs


def try_parse_handshake(hazel_version: int, data: bytes) -> Optional[Handshake]:
    try:
        return parse_handshake(hazel_version, data)
    except ValueError:
        return None
