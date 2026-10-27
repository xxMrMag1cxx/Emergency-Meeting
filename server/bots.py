"""
Bots: låtsasspelare som finns på servern i stället för i en telefon eller dator.

För de riktiga spelarna ser en bot ut precis som en vanlig spelare. Servern
låtsas att boten har en egen anslutning och gör samma saker som spelet gör
när någon går med:

  1. går med i spelet (JoinGame)
  2. "laddar lobbyn" (SceneChange), då skapar värden en gubbe åt boten
  3. ber värden om ett namn och en färg (CheckName, CheckColor)
  4. säger "redo" när en runda startar, och går med igen när rundan är slut

Boten kan gå (om walk är på). Den skickar sin position tio gånger i
sekunden, precis som spelet gör när man går. Vägen räknas ut med kartorna i
navigation.py, så att boten går runt väggarna.

  - I lobbyn går boten runt lite då och då.
  - Under en runda går boten till sina uppdrag och gör dem på plats.
    Impostor-bots låtsas göra uppdrag (men gör dem inte på riktigt).
  - När allt är klart vandrar boten mellan rummen.
  - På möten står boten still vid bordet och röstar skip när
    diskussionstiden är slut (om do_tasks är på).

Boten kan inte döda eller rapportera. Plugins skapar bots med
lobby.add_bot("Bot_1") och tar bort dem med lobby.remove_bot(bot).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import TYPE_CHECKING, List, Optional, Set

from . import navigation, protocol
from .handshake import Handshake
from .messages import MessageReader, MessageWriter
from .navigation import FEET_OFFSET, NavMap, Point, distance

if TYPE_CHECKING:
    from .game import Game

log = logging.getLogger("bot")

RPC_CHECK_NAME = protocol.RPC_CHECK_NAME
RPC_CHECK_COLOR = protocol.RPC_CHECK_COLOR

TICK = 0.1  # hur ofta (sekunder) boten skickar sin position när den går
BASE_SPEED = 2.5  # enheter per sekund vid "Player Speed" 1x
INTRO_TIME = 6.5  # rundans intro ("Shhh!" och rollen) innan man kan gå
MEETING_INTRO = 6.0  # mötets intro innan diskussionstiden börjar räknas
EXILE_TIME = 8.0  # utröstningen efter ett möte innan man kan gå igen
DEATH_PAUSE = 3.0  # efter att ha blivit dödad, innan spöket börjar gå

STOP_TIME = {"Short": (2.5, 5.0), "Common": (2.5, 5.0), "Long": (4.0, 8.0)}  # tid vid varje konsol
WANDER_PAUSE = (2.0, 6.0)  # paus mellan promenader när alla uppdrag är klara
LOBBY_PAUSE = (3.0, 9.0)
LOBBY_RADIUS = 2.5

# Utan kartdata (en ny karta vi inte känner till): så lång tid tar ett uppdrag.
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
        walk: bool = True,
    ):
        self.game = game
        self.client_id = client_id
        self.color = color
        self.do_tasks = do_tasks
        self.walk = walk
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

        # Rörelser
        self.transform_net_id: Optional[int] = None
        self.sequence = 0
        self.pos: Optional[Point] = None  # var fötterna är
        self._activity: Optional[asyncio.Future] = None

        # Det boten vet om den pågående rundan.
        self.round = 0  # ökar varje runda, så att gamla timers inte gör något
        self._reset_round()

    def _reset_round(self) -> None:
        self.role = 0
        self.alive = True
        self.in_meeting = False
        self.round_started = False
        self.task_types: List[int] = []  # uppdragens typnummer på kartan
        self.done: Set[int] = set()  # uppdrag (plats i listan) som är gjorda
        self.task_count = 0
        self.tasks_done = 0

    @property
    def name(self) -> str:
        return self.handshake.name

    @property
    def is_impostor(self) -> bool:
        return self.role in protocol.IMPOSTOR_ROLES

    def __str__(self) -> str:
        return f"{self.name} (bot)"

    def _lobby(self):
        return getattr(self.player, "lobby", None)

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
                self._stop()
                self._reset_round()
                loop.call_later(0.5, self.send_ready)
            elif message.tag == protocol.END_GAME:
                self.round += 1
                self._stop()
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
        lobby = self._lobby()
        for part in reader.messages():
            if part.tag == protocol.GameDataTag.DESPAWN:
                net_id = part.read_packed_uint32()
                if self.in_meeting and lobby is not None and net_id == lobby.meeting_hud_net_id:
                    self._meeting_ended()
                continue
            if part.tag != protocol.GameDataTag.RPC:
                continue
            net_id = part.read_packed_uint32()
            call = part.read_byte()
            if call == protocol.RPC_SET_ROLE and net_id == self.control_net_id:
                self.role = part.read_uint16()
                log.debug("%s fick rollen %s", self.name, protocol.ROLES.get(self.role, self.role))
                self._later(INTRO_TIME + 2.0, self._round_begins)  # om SetTasks aldrig kommer
            elif call == protocol.RPC_SET_TASKS and my_info is not None and net_id == my_info.net_id:
                count = part.read_packed_uint32()
                self.task_types = list(part.read_bytes(count))
                self.task_count = count
                self.tasks_done = 0
                self.done = set()
                self._round_begins()
            elif call == protocol.RPC_MURDER_PLAYER:
                target = part.read_packed_uint32()
                result = part.read_int32()
                if target == self.control_net_id and result & protocol.MURDER_SUCCEEDED and self.alive:
                    self._killed()
            elif call == protocol.RPC_EXILED and net_id == self.control_net_id:
                self.alive = False
            elif call == protocol.RPC_START_MEETING:
                self._meeting_started()
            elif call == protocol.RPC_CLOSE_MEETING and self.in_meeting:
                self._meeting_ended()

    def _my_info(self):
        lobby = self._lobby()
        return lobby.find_player_info(self.client_id) if lobby is not None else None

    def send_unreliable(self, payload: bytes) -> None:
        pass  # de andras rörelser, boten bryr sig inte

    def close(self) -> None:
        """Boten slutar med allt (t.ex. när spelet stängs)."""
        self.connected = False
        self._stop()

    def disconnect(self, reason: int = protocol.DisconnectReason.EXIT_GAME, message: str = "") -> None:
        if not self.connected:
            return
        self.close()
        player = self.player
        if player is not None:
            self.game.remove_player(player.lobby, self.client_id, protocol.DisconnectReason.EXIT_GAME)

    # --- Boten skickar till servern (som om den vore spelet) -------------

    def _send_as_game(self, tag: int, payload: bytes, handler) -> None:
        if self.connected:
            handler(self, MessageReader(payload, tag), True)

    def _game_data(self, *parts: bytes, to: Optional[int] = None) -> None:
        lobby = self._lobby()
        if lobby is None:
            return
        w = MessageWriter().write_int32(lobby.code_int)
        if to is not None:
            w.write_packed_int32(to)
        for part in parts:
            w.write_bytes(part)
        tag = protocol.GAME_DATA if to is None else protocol.GAME_DATA_TO
        self._send_as_game(tag, w.to_bytes(), self.game.handle_game_data)

    def _rpc(self, net_id: int, call: int, args: bytes = b"") -> bytes:
        w = MessageWriter().start_message(protocol.GameDataTag.RPC)
        w.write_packed_uint32(net_id).write_byte(call).write_bytes(args).end_message()
        return w.to_bytes()

    def join(self, code_int: int) -> None:
        payload = MessageWriter().write_int32(code_int).write_bool(False).to_bytes()
        self._send_as_game(protocol.JOIN_GAME, payload, self.game.handle_join_game)

    def join_again(self) -> None:
        """Efter en runda går alla med i lobbyn igen, boten också."""
        lobby = self._lobby()
        if lobby is not None and self.connected:
            self.join(lobby.code_int)

    def load_lobby(self) -> None:
        part = MessageWriter().start_message(protocol.GameDataTag.SCENE_CHANGE)
        part.write_packed_int32(self.client_id).write_string("OnlineGame").end_message()
        self._game_data(part.to_bytes())

    def on_spawned(self, net_id: int) -> None:
        """Värden har skapat botens gubbe. Be om namn och färg, som spelet gör."""
        self.control_net_id = net_id
        lobby = self._lobby()
        if lobby is None:
            return
        name = MessageWriter().write_string(self.name).to_bytes()
        color = MessageWriter().write_byte(self.color).to_bytes()
        self._game_data(
            self._rpc(net_id, RPC_CHECK_NAME, name),
            self._rpc(net_id, RPC_CHECK_COLOR, color),
            to=lobby.host_id,
        )
        # Som ett riktigt spel: berätta nivå och kläder för alla. Utan kläder
        # blir boten en "grön böna" med ofullständig spelarinfo, och det kan
        # få värdens spel att krångla.
        parts = [self._rpc(net_id, protocol.RPC_SET_LEVEL, MessageWriter().write_packed_uint32(0).to_bytes())]
        for kind, item in self._outfit(lobby).items():
            args = MessageWriter().write_string(item).write_byte(5).to_bytes()  # 5 = ny version av plagget
            parts.append(self._rpc(net_id, protocol.COSMETIC_RPCS[kind], args))
        self._game_data(*parts)
        log.debug("%s bad värden om namn och färg och tog på sig kläder", self.name)

        # Var står gubben? Värden skrev det när den skapade gubben.
        transform = lobby.transforms.get(net_id)
        if transform is not None:
            self.transform_net_id, self.sequence, (x, y) = transform
            self.pos = (x, y - FEET_OFFSET)
            if self.walk and not lobby.is_started:
                self._start(self._wander_lobby)

    @staticmethod
    def _outfit(lobby) -> dict:
        outfit = dict(protocol.EMPTY_COSMETICS)
        if getattr(lobby, "known_nameplate", ""):
            outfit["nameplate"] = lobby.known_nameplate  # en namnskylt vi vet att spelet känner till
        return outfit

    def send_ready(self) -> None:
        part = MessageWriter().start_message(protocol.GameDataTag.READY)
        part.write_packed_int32(self.client_id).end_message()
        self._game_data(part.to_bytes())

    # --- Gå ----------------------------------------------------------------

    def _send_position(self) -> None:
        """Berättar för alla var boten är (som spelet gör när man går)."""
        lobby = self._lobby()
        if lobby is None or self.transform_net_id is None or self.pos is None:
            return
        self.sequence = (self.sequence + 1) & 0xFFFF
        x, y = self.pos
        w = MessageWriter().start_message(protocol.GAME_DATA).write_int32(lobby.code_int)
        w.start_message(protocol.GameDataTag.DATA).write_packed_uint32(self.transform_net_id)
        w.write_uint16(self.sequence).write_packed_uint32(1).write_vector2(x, y + FEET_OFFSET)
        w.end_message().end_message()
        # Osäkert paket (som riktiga rörelser): om ett försvinner kommer nästa strax.
        lobby.send_to_all(w.to_bytes(), reliable=False, except_id=self.client_id)

    def _snap_to(self, point: Point) -> None:
        """Flyttar boten direkt till en plats (som när man åker genom en ventil)."""
        if self.transform_net_id is None:
            return
        self.pos = point
        self.sequence = (self.sequence + 1) & 0xFFFF
        args = MessageWriter().write_vector2(point[0], point[1] + FEET_OFFSET).write_uint16(self.sequence)
        self._game_data(self._rpc(self.transform_net_id, protocol.RPC_SNAP_TO, args.to_bytes()))

    def _speed(self) -> float:
        lobby = self._lobby()
        modifier = lobby.setting_number("Player Speed", 1.0) if lobby is not None else 1.0
        return BASE_SPEED * max(0.25, modifier)

    async def _walk_to(self, nav: NavMap, goal: Point) -> bool:
        """Går till goal runt väggarna. False om det inte finns någon väg dit."""
        if self.pos is None or self.transform_net_id is None:
            return False
        loop = asyncio.get_event_loop()
        path = await loop.run_in_executor(None, nav.find_path, self.pos, goal)
        if not path:
            return False
        speed = self._speed()
        last = loop.time()
        for waypoint in path:
            while self.pos != waypoint:
                await asyncio.sleep(TICK)
                now = loop.time()
                step = speed * min(now - last, 0.3)
                last = now
                x, y = self.pos
                left = distance(self.pos, waypoint)
                if left <= step:
                    self.pos = waypoint
                else:
                    self.pos = (x + (waypoint[0] - x) / left * step, y + (waypoint[1] - y) / left * step)
                self._send_position()
        return True

    # --- Saker boten håller på med (en i taget) ---------------------------

    def _start(self, activity, *args) -> None:
        """Börjar med något nytt (och slutar med det gamla)."""
        self._stop()
        if self.connected:
            self._activity = asyncio.ensure_future(self._run(activity(*args)))

    def _stop(self) -> None:
        if self._activity is not None:
            self._activity.cancel()
            self._activity = None

    async def _run(self, coroutine) -> None:
        try:
            await coroutine
        except asyncio.CancelledError:
            raise
        except Exception:  # en bot som krånglar får inte krascha servern
            log.exception("%s: något gick fel", self.name)

    def _later(self, seconds: float, action) -> None:
        """Kör `action` om en stund, men bara om det fortfarande är samma runda."""
        current = self.round

        def run() -> None:
            if self.connected and self.round == current:
                action()

        asyncio.get_event_loop().call_later(seconds, run)

    async def _load_map(self, key: str) -> Optional[NavMap]:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, navigation.load, key)
        except (OSError, ValueError, KeyError) as error:
            log.warning("Kunde inte läsa kartan %s: %s", key, error)
            return None

    async def _current_map(self) -> Optional[NavMap]:
        lobby = self._lobby()
        key = navigation.MAP_FILES.get(lobby.options.map_id) if lobby is not None else None
        return await self._load_map(key) if key else None

    # --- I lobbyn ----------------------------------------------------------

    async def _wander_lobby(self) -> None:
        nav = await self._load_map("lobby")
        if nav is None or self.pos is None or not nav.is_walkable(self.pos):
            return  # lobbyn ser inte ut som vi tror: stå still hellre än att gå in i väggar
        while True:
            await asyncio.sleep(random.uniform(*LOBBY_PAUSE))
            target = nav.random_point_near(self.pos, LOBBY_RADIUS)
            if target is not None:
                await self._walk_to(nav, target)

    # --- Rundan -------------------------------------------------------------

    def _round_begins(self) -> None:
        """Roller och uppdrag är utdelade: snart börjar rundan."""
        if self.round_started:
            return
        self.round_started = True
        lobby = self._lobby()
        self._snap_to_spawn(initial=True)
        if lobby is not None and lobby.options.map_id == 4:
            # The Airship: alla väljer var de börjar efter introt.
            self._later(INTRO_TIME + random.uniform(1.0, 4.0), lambda: self._resume(airship_spawn=True))
            return
        self._later(INTRO_TIME, self._resume)

    def _snap_to_spawn(self, initial: bool) -> None:
        lobby, info = self._lobby(), self._my_info()
        if lobby is None or info is None:
            return
        nav = navigation.load(navigation.MAP_FILES.get(lobby.options.map_id, ""))
        if nav is None or not nav.spawn:
            return
        self._snap_to(nav.spawn_position(info.player_id, len(lobby.server_objects), initial))

    def _resume(self, airship_spawn: bool = False) -> None:
        """Börja (eller fortsätt) gå runt och göra uppdrag."""
        lobby = self._lobby()
        if self.in_meeting or lobby is None or not lobby.is_started:
            return
        if airship_spawn:
            nav = navigation.load("airship")
            if nav is not None and nav.spawn_points:
                spot = nav.nearest_walkable(random.choice(nav.spawn_points), 1.5)
                if spot is not None:
                    self._snap_to(spot)
        self._start(self._play_round)

    async def _play_round(self) -> None:
        nav = await self._current_map()
        if nav is None or not self.walk or self.pos is None:
            await self._play_without_walking()
            return
        await asyncio.sleep(random.uniform(0.0, 1.5))  # alla börjar inte gå exakt samtidigt
        while True:
            index = self._next_task(nav)
            if index is not None:
                await self._do_task(nav, index)
            else:
                await self._wander(nav)

    def _wants_tasks(self) -> bool:
        if self.is_impostor:
            return True  # låtsas göra uppdrag
        return self.do_tasks

    def _next_task(self, nav: NavMap) -> Optional[int]:
        """Det närmaste uppdraget som inte är gjort än."""
        if not self._wants_tasks():
            return None
        left = [i for i in range(len(self.task_types)) if i not in self.done]
        if not left:
            return None

        def how_far(index: int) -> float:
            task = nav.tasks.get(self.task_types[index])
            consoles = task["consoles"] if task else []
            nearest = min((distance(self.pos, c) for c in consoles), default=20.0)
            # Lite slump, annars går alla bots till samma uppdrag i en lång rad.
            return nearest * random.uniform(0.6, 1.8)

        return min(left, key=how_far)

    def _task_stops(self, nav: NavMap, type_id: int) -> List[Point]:
        """Konsolerna boten ska gå till för ett uppdrag, i den ordning den går."""
        task = nav.tasks.get(type_id)
        consoles = list(task["consoles"]) if task else []
        if not consoles:
            # Vi vet inte var uppdraget görs: gå till något rum i stället.
            rooms = nav.room_spots(self.pos)
            return [random.choice(rooms)] if rooms else []
        if task["type"] == "FixWiring":
            count = 3
        elif task["length"] == "Long" and len(consoles) > 1:
            count = 2
        else:
            count = 1
        stops: List[Point] = []
        here = self.pos
        for _ in range(min(count, len(consoles))):
            # En av de två närmaste konsolerna (då väljer inte alla bots samma).
            console = random.choice(sorted(consoles, key=lambda c: distance(here, c))[:2])
            consoles.remove(console)
            stops.append(console)
            here = console
        return stops

    async def _do_task(self, nav: NavMap, index: int) -> None:
        type_id = self.task_types[index]
        task = nav.tasks.get(type_id)
        length = task["length"] if task else "Short"
        log.debug("%s går till uppdraget %s", self.name, task["type"] if task else type_id)
        for stop in self._task_stops(nav, type_id):
            spot = nav.console_spot(stop) or nav.nearest_walkable(stop, 1.6)
            if spot is not None:
                await self._walk_to(nav, spot)
            await asyncio.sleep(random.uniform(*STOP_TIME.get(length, STOP_TIME["Short"])))
        self.done.add(index)
        if not self.is_impostor:
            self.complete_task(index, task["type"] if task else "")

    async def _wander(self, nav: NavMap) -> None:
        """Alla uppdrag är klara: gå till ett slumpat rum och vänta lite."""
        rooms = nav.room_spots(self.pos)
        if rooms:
            room = random.choice(rooms)
            target = nav.random_point_near(room, 1.5) or room
            await self._walk_to(nav, target)
        await asyncio.sleep(random.uniform(*WANDER_PAUSE))

    async def _play_without_walking(self) -> None:
        """Ingen karta (eller walk av): gör uppdragen på stället, med en stund emellan."""
        if self.is_impostor or not self.do_tasks:
            return
        for index in range(len(self.task_types)):
            if index in self.done:
                continue
            await asyncio.sleep(random.uniform(*TASK_TIME))
            self.done.add(index)
            self.complete_task(index)

    def complete_task(self, index: int, kind: str = "") -> None:
        if self.control_net_id is None or self.is_impostor or not self.connected:
            return
        self._game_data(self._rpc(self.control_net_id, protocol.RPC_COMPLETE_TASK,
                                  MessageWriter().write_packed_uint32(index).to_bytes()))
        self.tasks_done += 1
        what = " (" + re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", kind) + ")" if kind else ""
        log.info("%s gjorde ett uppdrag%s (%d/%d)", self.name, what, self.tasks_done, self.task_count)

    def _killed(self) -> None:
        self.alive = False
        self._stop()
        log.debug("%s blev dödad", self.name)
        self._later(DEATH_PAUSE, self._resume)  # spöken kan fortsätta göra uppdrag

    # --- Möten ---------------------------------------------------------------

    def _meeting_started(self) -> None:
        self.in_meeting = True
        self._stop()
        if self.alive:
            self._snap_to_spawn(initial=False)
            if self.do_tasks:
                self._plan_vote()

    def _meeting_ended(self) -> None:
        self.in_meeting = False
        lobby = self._lobby()
        airship = lobby is not None and lobby.options.map_id == 4
        self._later(EXILE_TIME + (random.uniform(1.0, 4.0) if airship else 0.0),
                    lambda: self._resume(airship_spawn=airship))

    def _plan_vote(self) -> None:
        """Rösta skip en stund efter att diskussionstiden är slut."""
        lobby = self._lobby()
        discussion = lobby.setting_number("Discussion Time", 15.0) if lobby is not None else 15.0
        voting = lobby.setting_number("Voting Time", 120.0) if lobby is not None else 120.0
        earliest = MEETING_INTRO + discussion
        delay = earliest + random.uniform(2.0, 6.0)
        if voting > 0:
            delay = min(delay, max(earliest + 1.0, earliest + voting - 3.0))
        self._later(delay, self.vote_skip)

    def vote_skip(self) -> None:
        lobby = self._lobby()
        info = self._my_info()
        if lobby is None or info is None or lobby.meeting_hud_net_id is None or not self.alive or not self.in_meeting:
            return
        args = MessageWriter().write_byte(info.player_id).write_byte(protocol.VOTE_SKIP).to_bytes()
        self._game_data(self._rpc(lobby.meeting_hud_net_id, protocol.RPC_CAST_VOTE, args), to=lobby.host_id)
        log.debug("%s röstade skip", self.name)
