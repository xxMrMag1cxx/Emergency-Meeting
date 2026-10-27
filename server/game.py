"""
Spellogiken: vad servern gör med meddelandena från spelarna.

STEG 1: Just nu tar vi bara emot spelarna, skriver ut vad de skickar,
och svarar med ett välkomstmeddelande som visas i spelet.

I nästa steg bygger vi riktiga lobbyer med spelkoder här.
"""

from __future__ import annotations

import logging

from . import protocol
from .config import Config
from .hazel import Connection
from .messages import MessageReader

log = logging.getLogger("spel")


class Game:
    def __init__(self, config: Config):
        self.config = config

    def on_connect(self, connection: Connection) -> None:
        hs = connection.handshake
        if hs is None:
            log.info("En spelare anslöt från %s (kunde inte läsa detaljerna)", connection.address[0])
            return

        log.info(
            "%s anslöt! Spelversion %s, plattform: %s",
            hs.name,
            hs.game_version_text,
            hs.platform_text,
        )
        if hs.extra_bytes:
            log.debug("Hello hade %d extra bytes: %s", len(hs.extra_bytes), hs.extra_bytes.hex(" "))

    def on_message(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        tag = message.tag if message.tag is not None else -1
        log.info(
            "%s skickade %s (%d bytes)",
            connection.name,
            protocol.message_name(tag),
            len(message.data),
        )

        if tag in (protocol.HOST_GAME, protocol.JOIN_GAME):
            # Vi kan inte skapa eller gå med i spel än, så vi säger hej
            # och kopplar bort spelaren med vårt eget meddelande.
            text = self.config.welcome_message.replace("{namn}", connection.name)
            log.info("Skickar välkomstmeddelandet till %s", connection.name)
            connection.disconnect(protocol.DisconnectReason.CUSTOM, text)

    def on_disconnect(self, connection: Connection, why: str) -> None:
        log.info("%s är inte längre ansluten (%s)", connection.name, why)
