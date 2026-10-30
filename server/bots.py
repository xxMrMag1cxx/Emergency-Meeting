"""
Bots: pretend players that live on the server instead of in a phone or computer.

To the real players a bot looks exactly like an ordinary player. The server
pretends that the bot has its own connection and does the same things the
game does when someone joins:

  1. joins the game (JoinGame)
  2. "loads the lobby" (SceneChange), then the host creates a character for the bot
  3. asks the host for a name and a color (CheckName, CheckColor)
  4. says "ready" when a round starts, and joins again when the round is over

The bot can walk (if walk is on). It sends its position ten times a second,
just like the game does when you walk. The path is worked out with the maps
in navigation.py, so that the bot walks around the walls.

  - In the lobby the bot walks around a bit now and then.
  - During a round the bot walks to its tasks and does them on the spot.
    Impostor bots pretend to do tasks (but don't do them for real).
  - When everything is done the bot wanders between the rooms.
  - In meetings the bot stands still at the table and votes skip when
    the discussion time is over (if do_tasks is on).

The bot can't kill or report. Plugins create bots with
lobby.add_bot("Bot_1") and remove them with lobby.remove_bot(bot).
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

TICK = 0.1  # how often (seconds) the bot sends its position when it walks
BASE_SPEED = 2.5  # units per second at "Player Speed" 1x
INTRO_TIME = 6.5  # the round's intro ("Shhh!" and the role) before you can walk
MEETING_INTRO = 6.0  # the meeting's intro before the discussion time starts counting
EXILE_TIME = 8.0  # the ejection after a meeting before you can walk again
DEATH_PAUSE = 3.0  # after being killed, before the ghost starts walking

STOP_TIME = {"Short": (2.5, 5.0), "Common": (2.5, 5.0), "Long": (4.0, 8.0)}  # time at each console
WANDER_PAUSE = (2.0, 6.0)  # pause between walks when all tasks are done
LOBBY_PAUSE = (3.0, 9.0)
LOBBY_RADIUS = 2.5

# Without map data (a new map we don't know about): this is how long a task takes.
TASK_TIME = (12.0, 25.0)


class BotConnection:
    """Looks like a connection to the rest of the server, but is a bot."""

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
        self.puid = ""
        self.player: Optional[object] = None
        self.connected = True
        self.control_net_id: Optional[int] = None

        # Movement
        self.transform_net_id: Optional[int] = None
        self.sequence = 0
        self.pos: Optional[Point] = None  # where the feet are
        self._activity: Optional[asyncio.Future] = None

        # What the bot knows about the current round.
        self.round = 0  # goes up every round, so that old timers don't do anything
        self._reset_round()

    def _reset_round(self) -> None:
        self.role = 0
        self.alive = True
        self.in_meeting = False
        self.round_started = False
        self.task_types: List[int] = []  # the tasks' type numbers on the map
        self.done: Set[int] = set()  # tasks (place in the list) that are done
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

    # --- The server sends to the bot --------------------------------------

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
        """Looks for things that concern the bot: role, tasks, death and meetings."""
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
                log.debug("%s got the role %s", self.name, protocol.ROLES.get(self.role, self.role))
                self._later(INTRO_TIME + 2.0, self._round_begins)  # if SetTasks never comes
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
        pass  # the others' movements, the bot doesn't care

    def close(self) -> None:
        """The bot stops everything (for example when the game closes)."""
        self.connected = False
        self._stop()

    def disconnect(self, reason: int = protocol.DisconnectReason.EXIT_GAME, message: str = "") -> None:
        if not self.connected:
            return
        self.close()
        player = self.player
        if player is not None:
            self.game.remove_player(player.lobby, self.client_id, protocol.DisconnectReason.EXIT_GAME)

    # --- The bot sends to the server (as if it were the game) ------------

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
        """After a round everyone joins the lobby again, the bot too."""
        lobby = self._lobby()
        if lobby is not None and self.connected:
            self.join(lobby.code_int)

    def load_lobby(self) -> None:
        part = MessageWriter().start_message(protocol.GameDataTag.SCENE_CHANGE)
        part.write_packed_int32(self.client_id).write_string("OnlineGame").end_message()
        self._game_data(part.to_bytes())

    def on_spawned(self, net_id: int) -> None:
        """The host has created the bot's character. Ask for name and color, like the game does."""
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
        # Like a real game: tell everyone the level and clothes. Without clothes
        # the bot becomes a "green bean" with incomplete player info, and that can
        # make the host's game act up.
        parts = [self._rpc(net_id, protocol.RPC_SET_LEVEL, MessageWriter().write_packed_uint32(0).to_bytes())]
        for kind, item in self._outfit(lobby).items():
            args = MessageWriter().write_string(item).write_byte(5).to_bytes()  # 5 = new version of the item
            parts.append(self._rpc(net_id, protocol.COSMETIC_RPCS[kind], args))
        self._game_data(*parts)
        log.debug("%s asked the host for name and color and put on clothes", self.name)

        # Where does the character stand? The host wrote it when it created the character.
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
            outfit["nameplate"] = lobby.known_nameplate  # a nameplate we know the game knows about
        return outfit

    def send_ready(self) -> None:
        part = MessageWriter().start_message(protocol.GameDataTag.READY)
        part.write_packed_int32(self.client_id).end_message()
        self._game_data(part.to_bytes())

    # --- Walk --------------------------------------------------------------

    def _send_position(self) -> None:
        """Tells everyone where the bot is (like the game does when you walk)."""
        lobby = self._lobby()
        if lobby is None or self.transform_net_id is None or self.pos is None:
            return
        self.sequence = (self.sequence + 1) & 0xFFFF
        x, y = self.pos
        w = MessageWriter().start_message(protocol.GAME_DATA).write_int32(lobby.code_int)
        w.start_message(protocol.GameDataTag.DATA).write_packed_uint32(self.transform_net_id)
        w.write_uint16(self.sequence).write_packed_uint32(1).write_vector2(x, y + FEET_OFFSET)
        w.end_message().end_message()
        # Unreliable packet (like real movements): if one disappears the next one comes soon.
        lobby.send_to_all(w.to_bytes(), reliable=False, except_id=self.client_id)

    def _snap_to(self, point: Point) -> None:
        """Moves the bot straight to a place (like when you go through a vent)."""
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
        """Walks to goal around the walls. False if there is no path there."""
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

    # --- Things the bot is doing (one at a time) ---------------------------

    def _start(self, activity, *args) -> None:
        """Starts something new (and stops the old one)."""
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
        except Exception:  # a bot that acts up must not crash the server
            log.exception("%s: something went wrong", self.name)

    def _later(self, seconds: float, action) -> None:
        """Runs `action` in a while, but only if it is still the same round."""
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
            log.warning("Could not read the map %s: %s", key, error)
            return None

    async def _current_map(self) -> Optional[NavMap]:
        lobby = self._lobby()
        key = navigation.MAP_FILES.get(lobby.options.map_id) if lobby is not None else None
        return await self._load_map(key) if key else None

    # --- In the lobby ------------------------------------------------------

    async def _wander_lobby(self) -> None:
        nav = await self._load_map("lobby")
        if nav is None or self.pos is None or not nav.is_walkable(self.pos):
            return  # the lobby doesn't look like we think: stand still rather than walk into walls
        while True:
            await asyncio.sleep(random.uniform(*LOBBY_PAUSE))
            target = nav.random_point_near(self.pos, LOBBY_RADIUS)
            if target is not None:
                await self._walk_to(nav, target)

    # --- The round ----------------------------------------------------------

    def _round_begins(self) -> None:
        """Roles and tasks are handed out: the round starts soon."""
        if self.round_started:
            return
        self.round_started = True
        lobby = self._lobby()
        self._snap_to_spawn(initial=True)
        if lobby is not None and lobby.options.map_id == 4:
            # The Airship: everyone chooses where they start after the intro.
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
        """Start (or continue) walking around and doing tasks."""
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
        await asyncio.sleep(random.uniform(0.0, 1.5))  # not everyone starts walking at exactly the same time
        while True:
            index = self._next_task(nav)
            if index is not None:
                await self._do_task(nav, index)
            else:
                await self._wander(nav)

    def _wants_tasks(self) -> bool:
        if self.is_impostor:
            return True  # pretends to do tasks
        return self.do_tasks

    def _next_task(self, nav: NavMap) -> Optional[int]:
        """The nearest task that isn't done yet."""
        if not self._wants_tasks():
            return None
        left = [i for i in range(len(self.task_types)) if i not in self.done]
        if not left:
            return None

        def how_far(index: int) -> float:
            task = nav.tasks.get(self.task_types[index])
            consoles = task["consoles"] if task else []
            nearest = min((distance(self.pos, c) for c in consoles), default=20.0)
            # A bit of randomness, otherwise all bots walk to the same task in a long line.
            return nearest * random.uniform(0.6, 1.8)

        return min(left, key=how_far)

    def _task_stops(self, nav: NavMap, type_id: int) -> List[Point]:
        """The consoles the bot should walk to for a task, in the order it walks."""
        task = nav.tasks.get(type_id)
        consoles = list(task["consoles"]) if task else []
        if not consoles:
            # We don't know where the task is done: walk to some room instead.
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
            # One of the two nearest consoles (then not all bots choose the same one).
            console = random.choice(sorted(consoles, key=lambda c: distance(here, c))[:2])
            consoles.remove(console)
            stops.append(console)
            here = console
        return stops

    async def _do_task(self, nav: NavMap, index: int) -> None:
        type_id = self.task_types[index]
        task = nav.tasks.get(type_id)
        length = task["length"] if task else "Short"
        log.debug("%s walks to the task %s", self.name, task["type"] if task else type_id)
        for stop in self._task_stops(nav, type_id):
            spot = nav.console_spot(stop) or nav.nearest_walkable(stop, 1.6)
            if spot is not None:
                await self._walk_to(nav, spot)
            await asyncio.sleep(random.uniform(*STOP_TIME.get(length, STOP_TIME["Short"])))
        self.done.add(index)
        if not self.is_impostor:
            self.complete_task(index, task["type"] if task else "")

    async def _wander(self, nav: NavMap) -> None:
        """All tasks are done: walk to a random room and wait a bit."""
        rooms = nav.room_spots(self.pos)
        if rooms:
            room = random.choice(rooms)
            target = nav.random_point_near(room, 1.5) or room
            await self._walk_to(nav, target)
        await asyncio.sleep(random.uniform(*WANDER_PAUSE))

    async def _play_without_walking(self) -> None:
        """No map (or walk off): do the tasks on the spot, with a while in between."""
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
        log.info("%s did a task%s (%d/%d)", self.name, what, self.tasks_done, self.task_count)

    def _killed(self) -> None:
        self.alive = False
        self._stop()
        log.debug("%s was killed", self.name)
        self._later(DEATH_PAUSE, self._resume)  # ghosts can keep doing tasks

    # --- Meetings ------------------------------------------------------------

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
        """Vote skip a while after the discussion time is over."""
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
        log.debug("%s voted skip", self.name)
