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
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import gamecode, protocol
from .hazel import Connection
from .messages import MessageReader, MessageWriter
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

    # --- För plugins -----------------------------------------------------

    @property
    def is_host(self) -> bool:
        """True om spelaren är värd i sin lobby."""
        return self.lobby.host_id == self.client_id

    @property
    def is_bot(self) -> bool:
        """True om spelaren är en bot som servern styr."""
        return getattr(self.connection, "is_bot", False)

    @property
    def color(self) -> str:
        """Färgen spelaren har valt, t.ex. "Red". Tom text om den inte är känd än."""
        number = self.lobby.colors.get(self.client_id)
        return protocol.COLORS.get(number, "") if number is not None else ""

    @property
    def platform(self) -> str:
        """Vad spelaren spelar på, t.ex. "Steam (PC)" eller "iPhone/iPad"."""
        hs = self.connection.handshake
        return hs.platform_text if hs else "Okänd"

    def send_chat(self, text: str) -> bool:
        """
        Skickar ett chattmeddelande som bara den här spelaren ser.
        Det ser ut som att spelaren själv skrev det. Fungerar först när
        spelarens gubbe finns i lobbyn (se on_player_spawned).
        """
        net_id = self.lobby.control_net_id(self.client_id)
        if net_id is None:
            log.debug("Kan inte skicka chatt till %s än, gubben finns inte", self.name)
            return False
        self.lobby.send_to(self.client_id, self.lobby.chat_payload(net_id, text, self.client_id))
        return True

    def disconnect(self, message: str = "Du kopplades bort av servern.") -> None:
        """Kopplar bort spelaren och visar `message` i spelet."""
        self.connection.disconnect(protocol.DisconnectReason.CUSTOM, message)


COSMETICS = ("hat", "pet", "skin", "visor", "nameplate")


@dataclass
class PlayerInfoObject:
    """
    Ett "spelarinfo"-objekt som servern äger. Där sparar spelet namn,
    färg, hatt, nivå med mera.

    Servern skapar objektet och håller det uppdaterat när värden byter namn
    eller färg och när spelaren byter hatt osv. Annars skulle spelare som går
    med senare se de andra som "gröna bönor" utan namn, färg och kläder,
    och det får spelet att krångla.
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
        for cosmetic in COSMETICS:  # hatt, husdjur, dräkt, visir, namnskylt
            w.write_string(self.cosmetics[cosmetic])
        for cosmetic in COSMETICS:  # ändringsräknare för de fem ovan
            w.write_byte(self.sequence[cosmetic])
        w.write_packed_uint32(self.level)
        w.write_byte(0)  # flaggor (frånkopplad, död)
        w.write_uint16(0)  # roll
        w.write_bool(False)  # roll när levande
        w.write_byte(0)  # antal uppdrag
        w.write_string(self.friend_code)
        w.write_string(self.puid)
        return w.to_bytes()

    def update_from_data(self, reader: MessageReader) -> None:
        """Läser ett helt spelarinfo-tillstånd (om värden skickar ett)."""
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
    """Det som har hänt under en runda. Visas när rundan är slut."""

    roles: Dict[int, int] = field(default_factory=dict)  # spelar-id -> roll
    deaths: List[Tuple[str, str]] = field(default_factory=list)  # (offer, mördare)
    exiled: List[str] = field(default_factory=list)
    meetings: int = 0
    tasks_done: Dict[int, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    dead: Set[int] = field(default_factory=set)  # döda gubbars objektnummer
    protected: Dict[int, float] = field(default_factory=dict)  # gubbe -> när en Guardian Angel skyddade den
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

        # Spellogiken som äger lobbyn (behövs för att skapa bots).
        self.server = None

        # Värdens "GameManager"-objekt, där inställningarna bor.
        self.game_manager_net_id: Optional[int] = None
        self.options_part = 4  # vilken del av GameManager som är inställningarna

        # Spelargubbarnas objektnummer -> vems gubbe det är (spelar-id).
        self.player_controls: Dict[int, int] = {}
        # En giltig namnskylt från spelet (bots använder den).
        self.known_nameplate = ""
        # Spelarinfo från förra rundan, så att färg och kläder kan behållas.
        self.previous_infos: Dict[int, PlayerInfoObject] = {}
        # Spelar-id -> färgnummer, så att vi bara loggar när färgen ändras.
        self.colors: Dict[int, int] = {}
        # Gubbens objektnummer -> spelarnummer i spelet (0, 1, 2 ...).
        self.control_player_ids: Dict[int, int] = {}
        # Gubbens objektnummer -> (rörelseobjektets nummer, sekvensnummer, position)
        # som värden skapade gubben med. Bots behöver veta var de står.
        self.transforms: Dict[int, Tuple[int, int, Tuple[float, float]]] = {}
        self.meeting_hud_net_id: Optional[int] = None
        # Vad som händer under rundan (roller, dödsfall, möten ...).
        self.round = RoundInfo()

    def __str__(self) -> str:
        return self.code

    @property
    def host(self) -> Optional[Player]:
        return self.players.get(self.host_id)

    @property
    def host_name(self) -> str:
        return self.host.name if self.host else "Ingen värd"

    @property
    def host_authority(self) -> bool:
        """True om värden har ett mod som själv bestämmer över dödande (version +25)."""
        host = self.host
        hs = host.connection.handshake if host is not None else None
        return hs is not None and hs.game_version % 50 >= protocol.HOST_AUTHORITY_REVISION

    def setting_number(self, name: str, default: float) -> float:
        """En inställning som tal, t.ex. "Discussion Time" -> 15.0."""
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

    # --- För plugins -----------------------------------------------------

    @property
    def player_list(self) -> List[Player]:
        """Alla spelare i lobbyn."""
        return list(self.players.values())

    def find_player(self, name: str) -> Optional[Player]:
        """Letar upp en spelare på namnet (stora/små bokstäver spelar ingen roll)."""
        for player in self.players.values():
            if player.name.lower() == name.lower():
                return player
        return None

    @property
    def settings(self) -> Dict[str, str]:
        """Alla spelinställningar, t.ex. lobby.settings["Kill Cooldown"] -> "25 s"."""
        return dict(self.options.settings)

    @property
    def map_name(self) -> str:
        return self.options.map_name

    @property
    def is_started(self) -> bool:
        return self.state == GameState.STARTED

    @property
    def bots(self) -> List[Player]:
        """Alla bots i lobbyn, i den ordning de lades till."""
        return [p for p in self.players.values() if p.is_bot]

    def add_bot(self, name: str, do_tasks: bool = False, walk: bool = True) -> Optional[Player]:
        """
        Lägger till en bot med namnet `name`. Returnerar boten, eller None
        om det inte gick (lobbyn är full, en runda pågår, eller ingen värd).
        Med do_tasks=True gör boten sina uppdrag och röstar skip under rundan.
        Med walk=False står boten still i stället för att gå runt.
        """
        if self.server is None:
            return None
        return self.server.add_bot(self, name, do_tasks, walk)

    def remove_bot(self, bot: Optional[Player] = None) -> bool:
        """Tar bort en bot (den senast tillagda om ingen anges). False om det inte fanns någon."""
        bots = self.bots
        if bot is None:
            bot = bots[-1] if bots else None
        if bot is None or not bot.is_bot:
            return False
        bot.connection.disconnect()
        return True

    def send_chat(self, text: str) -> bool:
        """
        Skickar ett chattmeddelande till alla i lobbyn. Det syns som att
        värden skrev det.
        """
        net_id = self.control_net_id(self.host_id)
        if net_id is None:
            log.debug("Kan inte skicka chatt i %s än, värdens gubbe finns inte", self.code)
            return False
        self.send_to_all(self.chat_payload(net_id, text))
        return True

    def player_by_control(self, net_id: int) -> Optional["Player"]:
        """Spelaren som äger gubben med objektnummer `net_id`."""
        owner = self.player_controls.get(net_id)
        return self.players.get(owner) if owner is not None else None

    def player_by_player_id(self, player_id: int) -> Optional["Player"]:
        """Spelaren med spelarnummer `player_id` (det nummer spelet använder i röstning m.m.)."""
        for obj in self.server_objects.values():
            if obj.player_id == player_id:
                return self.players.get(obj.client_id)
        for net_id, pid in self.control_player_ids.items():
            if pid == player_id:
                return self.player_by_control(net_id)
        return None

    def control_net_id(self, client_id: int) -> Optional[int]:
        """Objektnumret för en spelares gubbe (behövs för att skicka chatt)."""
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

    # --- Vilka spelare ska få meddelanden --------------------------------

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

    def info_for_control(self, net_id: int) -> Optional[PlayerInfoObject]:
        """Spelarinfon för ägaren av gubben med objektnummer `net_id`."""
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
        w.write_byte(0)  # spawn-flaggor
        w.write_packed_uint32(1)  # antal delar
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
        """Skapar spelarinfo för en spelare som just har laddat lobbyn."""
        if self.find_player_info(player.client_id) is not None:
            return
        player_id = self.next_player_id()
        obj = PlayerInfoObject(net_id=self._next_net_id, client_id=player.client_id, player_id=player_id)
        old = self.previous_infos.get(player.client_id)
        if old is not None:
            # Efter en runda: behåll färg och kläder från förra gången.
            obj.color, obj.cosmetics, obj.sequence = old.color, dict(old.cosmetics), dict(old.sequence)
            obj.level = old.level
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
        # Spelare som hämtat en token via HTTPS men inte anslutit via UDP än:
        # namn -> (tid, adress). Används för att hitta anslutningsproblem.
        self.waiting_for_udp: Dict[str, Tuple[float, str]] = {}

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
