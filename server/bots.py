"""
Bots: låtsasspelare som finns på servern i stället för i en telefon eller dator.

För de riktiga spelarna ser en bot ut precis som en vanlig spelare. Servern
låtsas att boten har en egen anslutning och gör samma saker som spelet gör
när någon går med:

  1. går med i spelet (JoinGame)
  2. "laddar lobbyn" (SceneChange), då skapar värden en gubbe åt boten
  3. ber värden om ett namn och en färg (CheckName, CheckColor)
  4. säger "redo" när en runda startar, och går med igen när rundan är slut

Boten kan inte röra sig eller göra uppdrag än. Plugins skapar bots med
lobby.add_bot("Bot_1") och tar bort dem med lobby.remove_bot(bot).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from . import protocol
from .handshake import Handshake
from .messages import MessageReader, MessageWriter

if TYPE_CHECKING:
    from .game import Game

log = logging.getLogger("bot")

RPC_CHECK_NAME = 5
RPC_CHECK_COLOR = 7


class BotConnection:
    """Ser ut som en anslutning för resten av servern, men är en bot."""

    is_bot = True

    def __init__(self, game: "Game", client_id: int, name: str, game_version: int, color: int):
        self.game = game
        self.client_id = client_id
        self.color = color
        self.handshake = Handshake(
            hazel_version=1,
            game_version=game_version,
            name=name,
            chat_mode=1,
            platform=protocol.STEAM,
            platform_name="Bot",
            platform_raw=MessageWriter().write_string("Bot").to_bytes(),
        )
        self.address = ("bot", 0)
        self.player: Optional[object] = None
        self.connected = True
        self.control_net_id: Optional[int] = None

    @property
    def name(self) -> str:
        return self.handshake.name

    def __str__(self) -> str:
        return f"{self.name} (bot)"

    # --- Servern skickar till boten --------------------------------------

    def send_reliable(self, payload: bytes) -> None:
        loop = asyncio.get_event_loop()
        try:
            messages = list(MessageReader(payload).messages())
        except ValueError:
            return
        for message in messages:
            if message.tag == protocol.JOINED_GAME:
                loop.call_soon(self.load_lobby)
            elif message.tag == protocol.START_GAME:
                loop.call_later(0.5, self.send_ready)
            elif message.tag == protocol.END_GAME:
                loop.call_later(1.0, self.join_again)

    def send_unreliable(self, payload: bytes) -> None:
        pass  # rörelser och liknande, boten bryr sig inte

    def disconnect(self, reason: int = protocol.DisconnectReason.EXIT_GAME, message: str = "") -> None:
        if not self.connected:
            return
        self.connected = False
        player = self.player
        if player is not None:
            self.game.remove_player(player.lobby, self.client_id, protocol.DisconnectReason.EXIT_GAME)

    # --- Boten skickar till servern (som om den vore spelet) -------------

    def _send_as_game(self, tag: int, payload: bytes, handler) -> None:
        if self.connected:
            handler(self, MessageReader(payload, tag), True)

    def _game_data(self, *parts: bytes, to: Optional[int] = None) -> None:
        lobby = getattr(self.player, "lobby", None)
        if lobby is None:
            return
        w = MessageWriter().write_int32(lobby.code_int)
        if to is not None:
            w.write_packed_int32(to)
        for part in parts:
            w.write_bytes(part)
        tag = protocol.GAME_DATA if to is None else protocol.GAME_DATA_TO
        self._send_as_game(tag, w.to_bytes(), self.game.handle_game_data)

    def join(self, code_int: int) -> None:
        payload = MessageWriter().write_int32(code_int).write_bool(False).to_bytes()
        self._send_as_game(protocol.JOIN_GAME, payload, self.game.handle_join_game)

    def join_again(self) -> None:
        """Efter en runda går alla med i lobbyn igen, boten också."""
        lobby = getattr(self.player, "lobby", None)
        if lobby is not None and self.connected:
            self.join(lobby.code_int)

    def load_lobby(self) -> None:
        part = MessageWriter().start_message(protocol.GameDataTag.SCENE_CHANGE)
        part.write_packed_int32(self.client_id).write_string("OnlineGame").end_message()
        self._game_data(part.to_bytes())

    def on_spawned(self, net_id: int) -> None:
        """Värden har skapat botens gubbe. Be om namn och färg, som spelet gör."""
        self.control_net_id = net_id
        lobby = getattr(self.player, "lobby", None)
        if lobby is None:
            return
        name = MessageWriter().start_message(protocol.GameDataTag.RPC)
        name.write_packed_uint32(net_id).write_byte(RPC_CHECK_NAME).write_string(self.name).end_message()
        color = MessageWriter().start_message(protocol.GameDataTag.RPC)
        color.write_packed_uint32(net_id).write_byte(RPC_CHECK_COLOR).write_byte(self.color).end_message()
        self._game_data(name.to_bytes(), color.to_bytes(), to=lobby.host_id)
        log.debug("%s bad värden om namn och färg", self.name)

    def send_ready(self) -> None:
        part = MessageWriter().start_message(protocol.GameDataTag.READY)
        part.write_packed_int32(self.client_id).end_message()
        self._game_data(part.to_bytes())
