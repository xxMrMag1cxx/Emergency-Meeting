"""
Bots: låtsasspelare som finns på servern i stället för i en telefon eller dator.

För de riktiga spelarna ser en bot ut precis som en vanlig spelare. Servern
låtsas att boten har en egen anslutning och gör samma saker som spelet gör
när någon går med:

  1. går med i spelet (JoinGame)
  2. "laddar lobbyn" (SceneChange), då skapar värden en gubbe åt boten
  3. ber värden om ett namn och en färg (CheckName, CheckColor)
  4. säger "redo" när en runda startar, och går med igen när rundan är slut

Under en runda kan boten också (om do_tasks är på):
  - göra sina uppdrag, ett i taget med en stund emellan (inte som impostor)
  - rösta "skip" på möten

Boten står still och kan inte döda eller rapportera. Plugins skapar bots
med lobby.add_bot("Bot_1") och tar bort dem med lobby.remove_bot(bot).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import TYPE_CHECKING, Optional

from . import protocol
from .handshake import Handshake
from .messages import MessageReader, MessageWriter

if TYPE_CHECKING:
    from .game import Game

log = logging.getLogger("bot")

RPC_CHECK_NAME = protocol.RPC_CHECK_NAME
RPC_CHECK_COLOR = protocol.RPC_CHECK_COLOR

# Hur lång tid (sekunder) boten tar på sig för varje uppdrag.
TASK_TIME = (12.0, 25.0)


class BotConnection:
    """Ser ut som en anslutning för resten av servern, men är en bot."""

    is_bot = True

    def __init__(
        self,
        game: "Game",
        client_id: int,
        name: str,
        game_version: int,
        color: int,
        do_tasks: bool = False,
    ):
        self.game = game
        self.client_id = client_id
        self.color = color
        self.do_tasks = do_tasks
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

        # Det boten vet om den pågående rundan.
        self.round = 0  # ökar varje runda, så att gamla timers inte gör något
        self.role = 0
        self.alive = True
        self.task_count = 0
        self.tasks_done = 0

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
                self.round += 1
                self.role, self.alive, self.task_count, self.tasks_done = 0, True, 0, 0
                loop.call_later(0.5, self.send_ready)
            elif message.tag == protocol.END_GAME:
                self.round += 1
                loop.call_later(1.0, self.join_again)
            elif message.tag in (protocol.GAME_DATA, protocol.GAME_DATA_TO):
                try:
                    self._watch_game_data(message)
                except ValueError:
                    pass

    def _watch_game_data(self, message: MessageReader) -> None:
        """Tittar efter saker som rör boten: roll, uppdrag, död och möten."""
        reader = MessageReader(message.data)
        reader.read_int32()
        if message.tag == protocol.GAME_DATA_TO:
            reader.read_packed_int32()
        my_info = self._my_info()
        for part in reader.messages():
            if part.tag != protocol.GameDataTag.RPC:
                continue
            net_id = part.read_packed_uint32()
            call = part.read_byte()
            if call == protocol.RPC_SET_ROLE and net_id == self.control_net_id:
                self.role = part.read_uint16()
                log.debug("%s fick rollen %s", self.name, protocol.ROLES.get(self.role, self.role))
            elif call == protocol.RPC_SET_TASKS and my_info is not None and net_id == my_info.net_id:
                self.task_count = part.read_packed_uint32()
                self.tasks_done = 0
                self._plan_next_task()
            elif call == protocol.RPC_MURDER_PLAYER:
                target = part.read_packed_uint32()
                result = part.read_int32()
                if target == self.control_net_id and result & protocol.MURDER_SUCCEEDED:
                    self.alive = False
            elif call == protocol.RPC_EXILED and net_id == self.control_net_id:
                self.alive = False
            elif call == protocol.RPC_START_MEETING and self.alive and self.do_tasks:
                self._plan_vote()

    def _my_info(self):
        lobby = getattr(self.player, "lobby", None)
        return lobby.find_player_info(self.client_id) if lobby is not None else None

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
        # Som ett riktigt spel: berätta nivå och kläder för alla. Utan kläder
        # blir boten en "grön böna" med ofullständig spelarinfo, och det kan
        # få värdens spel att krångla.
        parts = []
        level = MessageWriter().start_message(protocol.GameDataTag.RPC)
        level.write_packed_uint32(net_id).write_byte(protocol.RPC_SET_LEVEL).write_packed_uint32(0).end_message()
        parts.append(level.to_bytes())
        for kind, item in self._outfit(lobby).items():
            rpc = MessageWriter().start_message(protocol.GameDataTag.RPC)
            rpc.write_packed_uint32(net_id).write_byte(protocol.COSMETIC_RPCS[kind])
            rpc.write_string(item).write_byte(5).end_message()  # 5 = ny version av plagget
            parts.append(rpc.to_bytes())
        self._game_data(*parts)
        log.debug("%s bad värden om namn och färg och tog på sig kläder", self.name)

    @staticmethod
    def _outfit(lobby) -> dict:
        outfit = dict(protocol.EMPTY_COSMETICS)
        if getattr(lobby, "known_nameplate", ""):
            outfit["nameplate"] = lobby.known_nameplate  # en namnskylt vi vet att spelet känner till
        return outfit

    # --- Spela en runda ---------------------------------------------------

    def _later(self, seconds: float, action) -> None:
        """Kör `action` om en stund, men bara om det fortfarande är samma runda."""
        current = self.round

        def run() -> None:
            if self.connected and self.round == current:
                action()

        asyncio.get_event_loop().call_later(seconds, run)

    def _plan_next_task(self) -> None:
        if not self.do_tasks or self.role in protocol.IMPOSTOR_ROLES:
            return
        if self.tasks_done >= self.task_count:
            return
        self._later(random.uniform(*TASK_TIME), self.complete_task)

    def complete_task(self) -> None:
        if self.control_net_id is None or self.role in protocol.IMPOSTOR_ROLES:
            return
        task_id = self.tasks_done
        part = MessageWriter().start_message(protocol.GameDataTag.RPC)
        part.write_packed_uint32(self.control_net_id).write_byte(protocol.RPC_COMPLETE_TASK)
        part.write_packed_uint32(task_id).end_message()
        self._game_data(part.to_bytes())
        self.tasks_done += 1
        log.info("%s gjorde ett uppdrag (%d/%d)", self.name, self.tasks_done, self.task_count)
        self._plan_next_task()

    def _plan_vote(self) -> None:
        """Rösta skip en stund efter att diskussionstiden är slut."""
        lobby = getattr(self.player, "lobby", None)
        discussion = 15.0
        if lobby is not None:
            match = re.match(r"(\d+)", lobby.settings.get("Discussion Time", ""))
            if match:
                discussion = float(match.group(1))
        self._later(discussion + random.uniform(2.0, 6.0), self.vote_skip)

    def vote_skip(self) -> None:
        lobby = getattr(self.player, "lobby", None)
        info = self._my_info()
        if lobby is None or info is None or lobby.meeting_hud_net_id is None or not self.alive:
            return
        part = MessageWriter().start_message(protocol.GameDataTag.RPC)
        part.write_packed_uint32(lobby.meeting_hud_net_id).write_byte(protocol.RPC_CAST_VOTE)
        part.write_byte(info.player_id).write_byte(protocol.VOTE_SKIP).end_message()
        self._game_data(part.to_bytes(), to=lobby.host_id)
        log.debug("%s röstade skip", self.name)

    def send_ready(self) -> None:
        part = MessageWriter().start_message(protocol.GameDataTag.READY)
        part.write_packed_int32(self.client_id).end_message()
        self._game_data(part.to_bytes())
