"""
Läser spelets "Hello"-paket, alltså det allra första paketet som
spelet skickar när det ansluter till servern.

Där står bl.a. spelarens namn, spelversion och plattform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import protocol
from .messages import MessageReader

# Datumen när Among Us lade till nya fält i Hello-paketet.
# Äldre spel skickar färre fält, så vi kollar versionen innan vi läser.
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
    extra_bytes: bytes = b""

    @property
    def game_version_text(self) -> str:
        return protocol.decode_game_version(self.game_version)

    @property
    def platform_text(self) -> str:
        return protocol.PLATFORMS.get(self.platform, f"Plattform {self.platform}")


def parse_handshake(hazel_version: int, data: bytes) -> Handshake:
    """
    `data` är allt efter de fyra första byten i Hello-paketet:
        [0x08] [paketnummer: 2 bytes] [hazel-version: 1 byte] [data...]
    """
    reader = MessageReader(data)
    hs = Handshake(hazel_version=hazel_version, game_version=reader.read_int32())

    hs.name = reader.read_string()

    if hs.game_version >= V1:
        reader.read_uint32()  # "lastNonceReceived", alltid 0 numera

    if hs.game_version >= V2:
        hs.language = reader.read_uint32()
        hs.chat_mode = reader.read_byte()

    if hs.game_version >= V3:
        platform = reader.read_message()
        hs.platform = platform.tag or 0
        hs.platform_name = platform.read_string()
        reader.read_int32()  # "crossplayFlags", används inte än

    if hs.game_version >= V4:
        reader.read_byte()  # okänd betydelse, alltid 0

    # Om nyare versioner av spelet skickar mer data sparar vi den,
    # så att vi kan titta på den i loggen.
    hs.extra_bytes = reader.read_rest()
    return hs


def try_parse_handshake(hazel_version: int, data: bytes) -> Optional[Handshake]:
    try:
        return parse_handshake(hazel_version, data)
    except ValueError:
        return None
