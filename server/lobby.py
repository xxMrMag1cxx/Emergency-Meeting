"""
Lobbyer: ett spel med en spelkod och spelarna i det.

Viktigt att veta om Among Us: det mesta av spellogiken körs hos *värden*
(den som skapade spelet), inte på servern. Servern är mest en brevbärare
som skickar vidare meddelanden mellan spelarna. Men den behöver hålla koll
på vem som är med i vilket spel, vem som är värd, och skapa ett litet
"spelarinfo"-objekt för varje spelare.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from . import gamecode, protocol
from .hazel import Connection
from .messages import MessageWriter
from .options import GameOptions

log = logging.getLogger("lobby")


class GameState:
    NOT_STARTED = "i lobbyn"
    STARTED = "spelar"
    ENDED = "slut"


class Limbo:
    """Var i anslutningen en spelare är."""

    PRE_SPAWN = "ansluter"  # har inte kommit in i lobbyn än
    IN_GAME = "i spelet"  # är inne och ska få alla meddelanden
    WAITING_FOR_HOST = "väntar på värden"  # efter en runda, väntar på att värden kommer tillbaka


# --- Spelare och objekt --------------------------------------------------

class Player:
    def __init__(self, connection: Connection, lobby: "Lobby"):
        self.connection = connection
        self.lobby = lobby
        self.limbo = Limbo.PRE_SPAWN

    @property
    def client_id(self) -> int:
        return self.connection.client_id

    @property
    def name(self) -> str:
        return self.connection.name

    def write_platform(self, writer: MessageWriter) -> None:
        hs = self.connection.handshake
        if hs is None:
            writer.start_message(0).write_string("").end_message()
        else:
            writer.start_message(hs.platform).write_bytes(hs.platform_raw).end_message()


@dataclass
class PlayerInfoObject:
    """
    Ett "spelarinfo"-objekt som servern äger. Där sparar spelet namn,
    färg, hatt, roll med mera. Värden ändrar innehållet, servern skapar det.
    """

    net_id: int
    client_id: int
    player_id: int
    state: bytes = b""  # senaste innehållet, för nya spelare som går med


def default_player_info(player_id: int, client_id: int) -> bytes:
    w = MessageWriter()
    w.write_byte(player_id)
    w.write_packed_int32(client_id)
    w.write_byte(1)  # antal utstyrslar
    w.write_byte(0)  # utstyrsel: standard
    w.write_string("")  # namn (värden fyller i)
    w.write_packed_int32(0)  # färg
    for _ in range(5):  # hatt, husdjur, dräkt, visir, namnskylt
        w.write_string("missing")
    w.write_bytes(bytes(5))  # ändringsräknare för de fem ovan
    w.write_packed_uint32(0)  # nivå
    w.write_byte(0)  # flaggor (frånkopplad, död)
    w.write_uint16(0)  # roll
    w.write_bool(False)  # roll när levande
    w.write_byte(0)  # antal uppdrag
    w.write_string("")  # vänkod
    w.write_string("")  # konto-id
    return w.to_bytes()


# --- Lobbyn --------------------------------------------------------------

class Lobby:
    def __init__(self, code: str, options: GameOptions):
        self.code = code
        self.code_int = gamecode.code_to_int(code)
        self.options = options
        self.host_id = -1
        self.players: Dict[int, Player] = {}
        self.state = GameState.NOT_STARTED
        self.is_public = False
        self.created_at = time.monotonic()
        self.server_objects: Dict[int, PlayerInfoObject] = {}
        self._next_net_id = protocol.FIRST_SERVER_NET_ID

        # Värdens "GameManager"-objekt, där inställningarna bor.
        self.game_manager_net_id: Optional[int] = None
        self.options_part = 4  # vilken del av GameManager som är inställningarna

        # Spelargubbarnas objektnummer -> vems gubbe det är (spelar-id).
        self.player_controls: Dict[int, int] = {}
        # Spelar-id -> färgnummer, så att vi bara loggar när färgen ändras.
        self.colors: Dict[int, int] = {}

    def __str__(self) -> str:
        return self.code

    @property
    def host(self) -> Optional[Player]:
        return self.players.get(self.host_id)

    @property
    def host_name(self) -> str:
        return self.host.name if self.host else "Ingen värd"

    def in_game(self, except_id: Optional[int] = None) -> List[Player]:
        return [
            p
            for p in self.players.values()
            if p.limbo == Limbo.IN_GAME and p.client_id != except_id
        ]

    # --- Skicka ----------------------------------------------------------

    @staticmethod
    def send(players: Iterable[Player], payload: bytes, reliable: bool = True) -> None:
        for p in players:
            if reliable:
                p.connection.send_reliable(payload)
            else:
                p.connection.send_unreliable(payload)

    def send_to_all(self, payload: bytes, reliable: bool = True, except_id: Optional[int] = None) -> None:
        self.send(self.in_game(except_id), payload, reliable)

    def send_to(self, client_id: int, payload: bytes, reliable: bool = True) -> None:
        player = self.players.get(client_id)
        if player is not None:
            self.send([player], payload, reliable)

    # --- Spelarinfo-objekt ----------------------------------------------

    def next_player_id(self) -> int:
        used = {obj.player_id for obj in self.server_objects.values()}
        for i in range(255):
            if i not in used:
                return i
        return 255

    def find_player_info(self, client_id: int) -> Optional[PlayerInfoObject]:
        for obj in self.server_objects.values():
            if obj.client_id == client_id:
                return obj
        return None

    def spawn_message(self, obj: PlayerInfoObject, target_id: Optional[int] = None) -> bytes:
        w = MessageWriter()
        if target_id is None:
            w.start_message(protocol.GAME_DATA).write_int32(self.code_int)
        else:
            w.start_message(protocol.GAME_DATA_TO).write_int32(self.code_int)
            w.write_packed_int32(target_id)
        w.start_message(protocol.GameDataTag.SPAWN)
        w.write_packed_uint32(protocol.SPAWN_PLAYER_INFO)
        w.write_packed_int32(protocol.SERVER_OWNED)
        w.write_byte(0)  # spawn-flaggor
        w.write_packed_uint32(1)  # antal delar
        w.write_packed_uint32(obj.net_id)
        w.start_message(1).write_bytes(obj.state).end_message()
        w.end_message()
        w.end_message()
        return w.to_bytes()

    def despawn_message(self, obj: PlayerInfoObject) -> bytes:
        w = MessageWriter()
        w.start_message(protocol.GAME_DATA).write_int32(self.code_int)
        w.start_message(protocol.GameDataTag.DESPAWN).write_packed_uint32(obj.net_id).end_message()
        w.end_message()
        return w.to_bytes()

    def spawn_player_info(self, player: Player) -> None:
        """Skapar spelarinfo för en spelare som just har laddat lobbyn."""
        if self.find_player_info(player.client_id) is not None:
            return
        player_id = self.next_player_id()
        obj = PlayerInfoObject(
            net_id=self._next_net_id,
            client_id=player.client_id,
            player_id=player_id,
            state=default_player_info(player_id, player.client_id),
        )
        self._next_net_id += 1
        self.server_objects[obj.net_id] = obj
        log.debug("%s: skapar spelarinfo %d för %s", self, obj.net_id, player.name)
        self.send_to_all(self.spawn_message(obj))

    def sync_player_infos(self, player: Player) -> None:
        """Skickar alla befintliga spelarinfo-objekt till en ny spelare."""
        for obj in self.server_objects.values():
            self.send_to(player.client_id, self.spawn_message(obj, target_id=player.client_id))

    def despawn_player_info(self, client_id: int) -> None:
        obj = self.find_player_info(client_id)
        if obj is not None:
            del self.server_objects[obj.net_id]
            self.send_to_all(self.despawn_message(obj))


class LobbyManager:
    def __init__(self) -> None:
        self.lobbies: Dict[int, Lobby] = {}

    def create(self, options: GameOptions) -> Lobby:
        while True:
            code = gamecode.random_code()
            if gamecode.code_to_int(code) not in self.lobbies:
                break
        lobby = Lobby(code, options)
        self.lobbies[lobby.code_int] = lobby
        return lobby

    def find(self, code_int: int) -> Optional[Lobby]:
        return self.lobbies.get(code_int)

    def remove(self, lobby: Lobby) -> None:
        self.lobbies.pop(lobby.code_int, None)

    def all(self) -> List[Lobby]:
        return list(self.lobbies.values())

    def public_lobbies(self) -> List[Lobby]:
        return [
            lobby
            for lobby in self.all()
            if lobby.is_public
            and lobby.state == GameState.NOT_STARTED
            and len(lobby.players) < lobby.options.max_players
        ]
