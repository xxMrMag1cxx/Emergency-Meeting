"""
Lobbies: a game with a game code and the players in it.

Important to know about Among Us: most of the game logic runs on the *host*
(the one who created the game), not on the server. The server is mostly a
mail carrier that passes messages on between the players. But it needs to
keep track of who is in which game and who is host, and create a small
"player info" object for each player.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import gamecode, protocol
from .hazel import Connection
from .messages import MessageReader, MessageWriter
from .options import GameOptions

log = logging.getLogger("lobby")


class GameState:
    NOT_STARTED = "in the lobby"
    STARTED = "playing"
    ENDED = "over"


class Limbo:
    """Where in connecting a player is."""

    PRE_SPAWN = "connecting"  # hasn't come into the lobby yet
    IN_GAME = "in the game"  # is in and should get all messages
    WAITING_FOR_HOST = "waiting for the host"  # after a round, waiting for the host to come back


# --- Players and objects --------------------------------------------------

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

    # --- For plugins -----------------------------------------------------

    @property
    def is_host(self) -> bool:
        """True if the player is host in their lobby."""
        return self.lobby.host_id == self.client_id

    @property
    def is_bot(self) -> bool:
        """True if the player is a bot that the server controls."""
        return getattr(self.connection, "is_bot", False)

    @property
    def color(self) -> str:
        """The color the player has picked, for example "Red". Empty text if it isn't known yet."""
        number = self.lobby.colors.get(self.client_id)
        return protocol.COLORS.get(number, "") if number is not None else ""

    @property
    def platform(self) -> str:
        """What the player plays on, for example "Steam (PC)" or "iPhone/iPad"."""
        hs = self.connection.handshake
        return hs.platform_text if hs else "Unknown"

    def send_chat(self, text: str) -> bool:
        """
        Sends a chat message that only this player sees.
        It looks like the player wrote it themselves. Works only once the
        player's character is in the lobby (see on_player_spawned).
        """
        net_id = self.lobby.control_net_id(self.client_id)
        if net_id is None:
            log.debug("Can't send chat to %s yet, the character doesn't exist", self.name)
            return False
        self.lobby.send_to(self.client_id, self.lobby.chat_payload(net_id, text, self.client_id))
        return True

    def disconnect(self, message: str = "You were disconnected by the server.") -> None:
        """Disconnects the player and shows `message` in the game."""
        self.connection.disconnect(protocol.DisconnectReason.CUSTOM, message)


COSMETICS = ("hat", "pet", "skin", "visor", "nameplate")


@dataclass
class PlayerInfoObject:
    """
    A "player info" object that the server owns. That's where the game keeps
    the name, color, hat, level and more.

    The server creates the object and keeps it updated when the host changes
    name or color and when the player changes hat etc. Otherwise players who
    join later would see the others as "green beans" without name, color and
    cosmetics, and that makes the game act up.
    """

    net_id: int
    client_id: int
    player_id: int
    name: str = ""
    color: int = 0
    cosmetics: Dict[str, str] = field(default_factory=lambda: {c: "missing" for c in COSMETICS})
    sequence: Dict[str, int] = field(default_factory=lambda: {c: 0 for c in COSMETICS})
    level: int = 0
    friend_code: str = ""
    puid: str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.name) and all(v != "missing" for v in self.cosmetics.values())

    def serialize(self) -> bytes:
        w = MessageWriter()
        w.write_byte(self.player_id)
        w.write_packed_int32(self.client_id)
        w.write_byte(1)  # antal utstyrslar
        w.write_byte(0)  # utstyrsel: standard
        w.write_string(self.name)
        w.write_packed_int32(self.color)
        for cosmetic in COSMETICS:  # hat, pet, skin, visor, nameplate
            w.write_string(self.cosmetics[cosmetic])
        for cosmetic in COSMETICS:  # change counters for the five above
            w.write_byte(self.sequence[cosmetic])
        w.write_packed_uint32(self.level)
        w.write_byte(0)  # flags (disconnected, dead)
        w.write_uint16(0)  # roll
        w.write_bool(False)  # role when alive
        w.write_byte(0)  # number of tasks
        w.write_string(self.friend_code)
        w.write_string(self.puid)
        return w.to_bytes()

    def update_from_data(self, reader: MessageReader) -> None:
        """Reads a whole player info state (if the host sends one)."""
        reader.read_byte()  # spelarnummer
        reader.read_packed_int32()  # klient-id
        for _ in range(reader.read_byte()):
            kind = reader.read_byte()
            name = reader.read_string()
            color = reader.read_packed_int32()
            ids = [reader.read_string() for _ in COSMETICS]
            seqs = [reader.read_byte() for _ in COSMETICS]
            if kind == 0:  # standardutstyrseln
                self.name, self.color = name, color
                self.cosmetics = dict(zip(COSMETICS, ids))
                self.sequence = dict(zip(COSMETICS, seqs))
        self.level = reader.read_packed_uint32()


@dataclass
class RoundInfo:
    """What has happened during a round. Shown when the round is over."""

    roles: Dict[int, int] = field(default_factory=dict)  # spelar-id -> roll
    deaths: List[Tuple[str, str]] = field(default_factory=list)  # (victim, killer)
    exiled: List[str] = field(default_factory=list)
    meetings: int = 0
    tasks_done: Dict[int, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    dead: Set[int] = field(default_factory=set)  # the object numbers of dead characters
    protected: Dict[int, float] = field(default_factory=dict)  # character -> when a Guardian Angel protected it
    in_meeting: bool = False


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

        # The game logic that owns the lobby (needed to create bots).
        self.server = None

        # The host's "GameManager" object, where the settings live.
        self.game_manager_net_id: Optional[int] = None
        self.options_part = 4  # which part of GameManager holds the settings

        # The player characters' object numbers -> whose character it is (client id).
        self.player_controls: Dict[int, int] = {}
        # A valid nameplate from the game (bots use it).
        self.known_nameplate = ""
        # Player info from the last round, so that color and cosmetics can be kept.
        self.previous_infos: Dict[int, PlayerInfoObject] = {}
        # Client id -> color number, so that we only log when the color changes.
        self.colors: Dict[int, int] = {}
        # The character's object number -> player number in the game (0, 1, 2 ...).
        self.control_player_ids: Dict[int, int] = {}
        # The character's object number -> (the movement object's number, sequence number, position)
        # that the host created the character with. Bots need to know where they stand.
        self.transforms: Dict[int, Tuple[int, int, Tuple[float, float]]] = {}
        self.meeting_hud_net_id: Optional[int] = None
        # What happens during the round (roles, deaths, meetings ...).
        self.round = RoundInfo()

    def __str__(self) -> str:
        return self.code

    @property
    def host(self) -> Optional[Player]:
        return self.players.get(self.host_id)

    @property
    def host_name(self) -> str:
        return self.host.name if self.host else "No host"

    @property
    def host_authority(self) -> bool:
        """True if the host has a mod that decides about killing by itself (version +25)."""
        host = self.host
        hs = host.connection.handshake if host is not None else None
        return hs is not None and hs.game_version % 50 >= protocol.HOST_AUTHORITY_REVISION

    def setting_number(self, name: str, default: float) -> float:
        """A setting as a number, for example "Discussion Time" -> 15.0."""
        text = self.options.settings.get(name, "")
        number = ""
        for char in text:
            if char.isdigit() or char in ".-":
                number += char
            else:
                break
        try:
            return float(number)
        except ValueError:
            return default

    # --- For plugins -----------------------------------------------------

    @property
    def player_list(self) -> List[Player]:
        """All players in the lobby."""
        return list(self.players.values())

    def find_player(self, name: str) -> Optional[Player]:
        """Finds a player by name (upper/lower case doesn't matter)."""
        for player in self.players.values():
            if player.name.lower() == name.lower():
                return player
        return None

    @property
    def settings(self) -> Dict[str, str]:
        """All game settings, for example lobby.settings["Kill Cooldown"] -> "25 s"."""
        return dict(self.options.settings)

    @property
    def map_name(self) -> str:
        return self.options.map_name

    @property
    def is_started(self) -> bool:
        return self.state == GameState.STARTED

    @property
    def bots(self) -> List[Player]:
        """All bots in the lobby, in the order they were added."""
        return [p for p in self.players.values() if p.is_bot]

    def add_bot(self, name: str, do_tasks: bool = False, walk: bool = True) -> Optional[Player]:
        """
        Adds a bot with the name `name`. Returns the bot, or None if it
        didn't work (the lobby is full, a round is going on, or there is no host).
        With do_tasks=True the bot does its tasks and votes skip during the round.
        With walk=False the bot stands still instead of walking around.
        """
        if self.server is None:
            return None
        return self.server.add_bot(self, name, do_tasks, walk)

    def remove_bot(self, bot: Optional[Player] = None) -> bool:
        """Removes a bot (the last one added if none is given). False if there wasn't one."""
        bots = self.bots
        if bot is None:
            bot = bots[-1] if bots else None
        if bot is None or not bot.is_bot:
            return False
        bot.connection.disconnect()
        return True

    def send_chat(self, text: str) -> bool:
        """
        Sends a chat message to everyone in the lobby. It looks like the
        host wrote it.
        """
        net_id = self.control_net_id(self.host_id)
        if net_id is None:
            log.debug("Can't send chat in %s yet, the host's character doesn't exist", self.code)
            return False
        self.send_to_all(self.chat_payload(net_id, text))
        return True

    def player_by_control(self, net_id: int) -> Optional["Player"]:
        """The player who owns the character with object number `net_id`."""
        owner = self.player_controls.get(net_id)
        return self.players.get(owner) if owner is not None else None

    def player_by_player_id(self, player_id: int) -> Optional["Player"]:
        """The player with player number `player_id` (the number the game uses in voting etc.)."""
        for obj in self.server_objects.values():
            if obj.player_id == player_id:
                return self.players.get(obj.client_id)
        for net_id, pid in self.control_player_ids.items():
            if pid == player_id:
                return self.player_by_control(net_id)
        return None

    def control_net_id(self, client_id: int) -> Optional[int]:
        """The object number of a player's character (needed to send chat)."""
        for net_id, owner in self.player_controls.items():
            if owner == client_id:
                return net_id
        return None

    def chat_payload(self, net_id: int, text: str, target_id: Optional[int] = None) -> bytes:
        w = MessageWriter()
        if target_id is None:
            w.start_message(protocol.GAME_DATA).write_int32(self.code_int)
        else:
            w.start_message(protocol.GAME_DATA_TO).write_int32(self.code_int)
            w.write_packed_int32(target_id)
        w.start_message(protocol.GameDataTag.RPC)
        w.write_packed_uint32(net_id).write_byte(protocol.RPC_SEND_CHAT).write_string(text)
        w.end_message()
        w.end_message()
        return w.to_bytes()

    # --- Which players should get messages --------------------------------

    def in_game(self, except_id: Optional[int] = None) -> List[Player]:
        return [
            p
            for p in self.players.values()
            if p.limbo == Limbo.IN_GAME and p.client_id != except_id
        ]

    # --- Send ------------------------------------------------------------

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

    def info_for_control(self, net_id: int) -> Optional[PlayerInfoObject]:
        """The player info for the owner of the character with object number `net_id`."""
        owner = self.player_controls.get(net_id)
        return self.find_player_info(owner) if owner is not None else None

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
        w.write_byte(0)  # spawn flags
        w.write_packed_uint32(1)  # number of parts
        w.write_packed_uint32(obj.net_id)
        w.start_message(1).write_bytes(obj.serialize()).end_message()
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
        """Creates player info for a player who has just loaded the lobby."""
        if self.find_player_info(player.client_id) is not None:
            return
        player_id = self.next_player_id()
        obj = PlayerInfoObject(net_id=self._next_net_id, client_id=player.client_id, player_id=player_id)
        old = self.previous_infos.get(player.client_id)
        if old is not None:
            # After a round: keep color and cosmetics from last time.
            obj.color, obj.cosmetics, obj.sequence = old.color, dict(old.cosmetics), dict(old.sequence)
            obj.level = old.level
        self._next_net_id += 1
        self.server_objects[obj.net_id] = obj
        log.debug("%s: creating player info %d for %s", self, obj.net_id, player.name)
        self.send_to_all(self.spawn_message(obj))

    def sync_player_infos(self, player: Player) -> None:
        """Sends all existing player info objects to a new player."""
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
        # Players who fetched a token over HTTPS but haven't connected over UDP yet:
        # name -> (time, address). Used to find connection problems.
        self.waiting_for_udp: Dict[str, Tuple[float, str]] = {}
        # name -> the account id ("Puid") the game sent when it fetched its token
        self.puids: Dict[str, str] = {}

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
