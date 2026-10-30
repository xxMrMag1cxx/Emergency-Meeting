"""
The game logic: what the server does with the messages from the players.

The flow when someone presses "Create Game":

  1. HostGame   the game sends its settings         -> we create a lobby
                                                       and answer with the game code
  2. JoinGame   the game joins its own game         -> we answer JoinedGame
                                                       and the player becomes host
  3. GameData   the host loads the lobby and sends  -> we pass it on to
                game data all the time                 all the other players

When more people join with the game code the same thing happens from step 2,
and the server tells everyone in the lobby that someone new has arrived.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Callable, List, Optional

from . import __version__, protocol
from .config import Config
from .i18n import tr
from .bots import BotConnection
from .hazel import Connection
from .access import Access
from .lobby import GameState, Limbo, Lobby, LobbyManager, Player, RoundInfo
from .logfile import save_game_summary
from .messages import MessageReader, MessageWriter
from .options import GameOptions, differences, read_options
from .plugins import PluginManager

log = logging.getLogger("game")

Reason = protocol.DisconnectReason
ALTER_GAME_PRIVACY = 1
EMPTY_LOBBY_TIMEOUT = 60  # seconds before a lobby without players is removed


def translate_reason(why: str) -> str:
    """Why someone disconnected, in the terminal's language (the report file is always English)."""
    prefix = "the game disconnected: "
    if why.startswith(prefix):
        reason, _, text = why[len(prefix):].partition(": ")
        reason = tr(reason) + (f": {text}" if text else "")
        return tr("the game disconnected: {reason}", reason=reason)
    return tr(why)


class Game:
    def __init__(self, config: Config, lobbies: LobbyManager, plugins: Optional[PluginManager] = None,
                 access: Optional[Access] = None):
        self.config = config
        self.lobbies = lobbies
        self.plugins = plugins or PluginManager()
        self.access = access or Access()
        self._next_client_id = 0
        # Plugin events that should run only after the game data has been passed on.
        self._after_forward: List[Callable[[], None]] = []

    # =====================================================================
    # Connections
    # =====================================================================

    def on_connect(self, connection: Connection) -> None:
        self._next_client_id += 1
        connection.client_id = self._next_client_id

        hs = connection.handshake
        if hs is None:
            log.info("A player connected from %s (could not read the details)", connection.address[0])
            return
        self.lobbies.waiting_for_udp.pop(hs.name, None)
        log.info(
            "%s connected (game version %s, %s)",
            hs.name,
            hs.game_version_text,
            tr(hs.platform_text),
        )
        connection.puid = self.lobbies.puids.get(hs.name, "")
        self._check_game_version(connection)
        if connection.connected:
            self._check_access(connection)

    def _check_access(self, connection: Connection) -> None:
        """Banned players, and names that aren't allowed, get a message and are disconnected."""
        hs = connection.handshake
        assert hs is not None
        ban = self.access.find_ban(hs.name, connection.puid)
        if ban is not None:
            log.warning("%s can't join: banned since %s. Use /unban %s to let them in again.",
                        hs.name, ban.banned_at, ban.name)
            connection.disconnect(Reason.CUSTOM, "You are banned from this server.")
        elif self.config.only_allowed_names and not self.access.is_allowed(hs.name):
            log.warning("%s can't join: the name isn't in allowed-names.txt. Use /allow %s to let them in.",
                        hs.name, hs.name.strip())
            connection.disconnect(Reason.CUSTOM, "This server only lets in players on its list. "
                                                 "Ask the host to add your name.")

    def _check_game_version(self, connection: Connection) -> None:
        """
        Says in the log if the game isn't the version the server is made for,
        and disconnects it if config.json doesn't allow that version.
        """
        hs = connection.handshake
        assert hs is not None
        compared = protocol.compare_game_version(hs.game_version)
        if compared == 0:
            return
        built_for = protocol.BUILT_FOR
        if compared > 0 and self.config.allow_future_game_versions:
            log.info("%s has a newer game version than the server is made for (Among Us %s). "
                     "It's allowed, but something might not work.", hs.name, built_for)
        elif compared < 0 and self.config.allow_older_game_versions:
            log.info("%s has an older game version than the server is made for (Among Us %s). "
                     "It's allowed, but something might not work.", hs.name, built_for)
        elif compared > 0:
            log.warning("%s can't join: a newer game version than the server is made for (Among Us %s), "
                        "and allow_future_game_versions is false", hs.name, built_for)
            connection.disconnect(Reason.CUSTOM, f"This server is made for Among Us {built_for} "
                                                 "and doesn't allow newer versions of the game.")
        else:
            log.warning("%s can't join: an older game version than the server is made for (Among Us %s), "
                        "and allow_older_game_versions is false", hs.name, built_for)
            connection.disconnect(Reason.CUSTOM, f"This server is made for Among Us {built_for}. "
                                                 "Update Among Us to play here.")

    def on_disconnect(self, connection: Connection, why: str) -> None:
        player = self._player(connection)
        lobby_code = player.lobby.code if player is not None else None
        if player is not None:
            self.remove_player(player.lobby, player.client_id, Reason.EXIT_GAME)
        log.info("%s disconnected (%s)", connection.name, translate_reason(why))

        # Save the black box if the player was in a game.
        recorder = getattr(connection, "recorder", None)
        if lobby_code is not None and recorder is not None:
            path = recorder.save(connection.name, why, lobby_code)
            if path is not None:
                log.info("Saved what happened just before in logs/%s", path.name)

    # =====================================================================
    # Messages
    # =====================================================================

    def on_message(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        tag = message.tag if message.tag is not None else -1
        handler = {
            protocol.HOST_GAME: self.handle_host_game,
            protocol.HOST_MODDED_GAME: self.handle_host_game,
            protocol.JOIN_GAME: self.handle_join_game,
            protocol.START_GAME: self.handle_start_game,
            protocol.END_GAME: self.handle_end_game,
            protocol.REMOVE_PLAYER: self.handle_remove_player,
            protocol.GAME_DATA: self.handle_game_data,
            protocol.GAME_DATA_TO: self.handle_game_data,
            protocol.PACKED_GAME_DATA_TO: self.handle_packed_game_data_to,
            protocol.ALTER_GAME: self.handle_alter_game,
            protocol.KICK_PLAYER: self.handle_kick_player,
            protocol.QUERY_PLATFORM_IDS: self.handle_query_platform_ids,
        }.get(tag)

        if handler is None:
            if tag != protocol.SET_ACTIVE_POD_TYPE:
                log.info("%s sent %s (not handled yet)", connection.name, protocol.message_name(tag))
            return

        try:
            handler(connection, message, reliable)
        except ValueError as error:
            log.warning(
                "Could not read %s from %s: %s",
                protocol.message_name(tag),
                connection.name,
                error,
            )

    # --- Create and join ------------------------------------------------

    def handle_host_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        try:
            options = read_options(message)
        except ValueError:
            log.warning("Could not read the game settings from %s, using the default values", connection.name)
            options = GameOptions()

        lobby = self.lobbies.create(options)
        lobby.server = self
        log.info(
            "%s created the game %s (%s, %s, max %d players, %d impostor%s)",
            connection.name,
            lobby.code,
            options.map_name,
            tr(options.mode_name),
            options.max_players,
            options.num_impostors,
            "s" if options.num_impostors != 1 else "",
        )

        # Answer with the game code. The game then sends JoinGame with it.
        w = MessageWriter().start_message(protocol.HOST_GAME).write_int32(lobby.code_int).end_message()
        connection.send_reliable(w.to_bytes())

    def handle_join_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        code_int = message.read_int32()
        lobby = self.lobbies.find(code_int)
        if lobby is None:
            log.info("%s tried to join a game that doesn't exist", connection.name)
            connection.disconnect(Reason.GAME_NOT_FOUND)
            return
        if lobby.state == GameState.STARTED:
            connection.disconnect(Reason.GAME_STARTED)
            return

        player = self._player(connection)
        is_new = player is None or player.lobby is not lobby

        if is_new:
            if len(lobby.players) >= lobby.options.max_players:
                connection.disconnect(Reason.GAME_FULL)
                return
            if not self._version_fits(lobby, connection):
                return
            if player is not None:  # was in another game
                self.remove_player(player.lobby, player.client_id, Reason.EXIT_GAME)
            player = Player(connection, lobby)
            connection.player = player
            lobby.players[player.client_id] = player
            if lobby.host_id == -1:
                lobby.host_id = player.client_id
        elif player.limbo == Limbo.IN_GAME:
            connection.disconnect(Reason.CUSTOM, "You are already in the game.")
            return

        if lobby.state == GameState.ENDED:
            self._join_after_round(lobby, player)
        else:
            self._join_lobby(lobby, player)

        if is_new and player.connection.player is player:
            if player.is_host and len(lobby.players) == 1:
                self.plugins.fire("on_game_created", lobby, player)
            self.plugins.fire("on_player_joined", lobby, player)

    def _join_lobby(self, lobby: Lobby, player: Player) -> None:
        if player.client_id == lobby.host_id:
            role = tr("host")
        elif player.is_bot:
            role = tr("bot")
        else:
            role = tr("player")
        self._warn_if_other_version(lobby, player)
        log.info(
            "%s joined %s as %s (%d/%d players)",
            player.name,
            lobby.code,
            role,
            len(lobby.players),
            lobby.options.max_players,
        )
        others = [p for p in lobby.players.values() if p is not player]
        welcome = self._joined_game_message(lobby, player, others) + self._alter_game_message(lobby)
        player.limbo = Limbo.IN_GAME
        player.connection.send_reliable(welcome)
        lobby.send_to_all(self._join_game_message(lobby, player), except_id=player.client_id)

    def _version_fits(self, lobby: Lobby, connection: Connection) -> bool:
        """
        Can this player's version of Among Us play with the host's? If not (and
        "allow_version_mixing" is false), the player gets a message and False.
        """
        host = lobby.host
        if host is None or connection.handshake is None or host.connection.handshake is None:
            return True
        mine = connection.handshake.game_version
        theirs = host.connection.handshake.game_version
        if protocol.versions_fit(theirs, mine) or self.config.allow_version_mixing:
            return True
        log.warning(
            "%s can't join %s: their game version (%s) doesn't fit with the host %s (%s). "
            "allow_version_mixing is false",
            connection.name, lobby.code, protocol.decode_game_version(mine),
            host.name, protocol.decode_game_version(theirs),
        )
        connection.disconnect(Reason.CUSTOM, (
            f"You and the host of this game have different versions of Among Us "
            f"(you: {protocol.decode_game_version(mine)}, the host: {protocol.decode_game_version(theirs)}). "
            f"Update Among Us so that you both have the newest version."
        ))
        return False

    @staticmethod
    def _warn_if_other_version(lobby: Lobby, player: Player) -> None:
        """Versions that don't fit together, let in because of allow_version_mixing: a warning in the log."""
        host = lobby.host
        if host is None or host is player or not host.connection.handshake or not player.connection.handshake:
            return
        mine = player.connection.handshake.game_version
        theirs = host.connection.handshake.game_version
        if not protocol.versions_fit(theirs, mine):
            log.warning(
                "%s has a game version (%s) that doesn't fit with the host %s (%s). Things can act up.",
                player.name,
                protocol.decode_game_version(mine),
                host.name,
                protocol.decode_game_version(theirs),
            )

    def _join_after_round(self, lobby: Lobby, player: Player) -> None:
        """After a round: the host has to come back first."""
        if player.client_id == lobby.host_id:
            lobby.state = GameState.NOT_STARTED
            self._join_lobby(lobby, player)
            self._let_waiting_players_in(lobby)
            return

        log.info("%s is waiting for the host to come back to %s", player.name, lobby.code)
        player.limbo = Limbo.WAITING_FOR_HOST
        w = MessageWriter().start_message(protocol.WAIT_FOR_HOST)
        w.write_int32(lobby.code_int).write_int32(player.client_id).end_message()
        player.connection.send_reliable(w.to_bytes())
        lobby.send_to_all(self._join_game_message(lobby, player), except_id=player.client_id)

    def _let_waiting_players_in(self, lobby: Lobby) -> None:
        for player in list(lobby.players.values()):
            if player.limbo == Limbo.WAITING_FOR_HOST:
                others = [p for p in lobby.players.values() if p is not player]
                payload = self._joined_game_message(lobby, player, others) + self._alter_game_message(lobby)
                player.limbo = Limbo.IN_GAME
                player.connection.send_reliable(payload)

    # --- The course of the game --------------------------------------------

    def handle_start_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player, lobby = self._host_check(connection, message)
        if lobby is None:
            return
        lobby.state = GameState.STARTED
        lobby.round = RoundInfo()
        log.info(
            "%s: the game is starting! (%d players, %s)",
            lobby.code,
            len(lobby.players),
            lobby.options.map_name,
        )
        lobby.send_to_all(self._forward(message))
        self.plugins.fire("on_game_started", lobby)

    def handle_end_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player, lobby = self._host_check(connection, message)
        if lobby is None:
            return
        try:
            reason = message.read_byte()
        except ValueError:
            reason = -1
        result = protocol.GAME_OVER_REASONS.get(reason, f"the round is over (reason {reason})")
        lobby.state = GameState.ENDED
        lobby.send_to_all(self._forward(message))
        self._log_round_summary(lobby, result)
        for p in lobby.players.values():
            p.limbo = Limbo.PRE_SPAWN
        # Player info and characters are created again when everyone comes back to the lobby.
        lobby.previous_infos = {obj.client_id: obj for obj in lobby.server_objects.values()}
        lobby.server_objects.clear()
        lobby.player_controls.clear()
        lobby.control_player_ids.clear()
        lobby.transforms.clear()
        lobby.meeting_hud_net_id = None
        lobby.round.in_meeting = False
        self.plugins.fire("on_game_ended", lobby, result)

    def _log_round_summary(self, lobby: Lobby, result: str) -> None:
        r = lobby.round
        minutes, seconds = divmod(int(time.monotonic() - r.started_at), 60)
        log.info("%s: THE ROUND IS OVER. %s (%d min %d s, %d meetings)", lobby.code, tr(result), minutes, seconds, r.meetings)
        impostors = [
            lobby.players[cid].name
            for cid, role in r.roles.items()
            if role in protocol.IMPOSTOR_ROLES and cid in lobby.players
        ]
        if impostors:
            log.info("%s:   Impostors: %s", lobby.code, ", ".join(impostors))
        for cid, role in r.roles.items():
            if cid in lobby.players and role not in (0, 1):
                log.info("%s:   %s was %s", lobby.code, lobby.players[cid].name, tr(str(protocol.ROLES.get(role, role))))
        for victim, killer in r.deaths:
            log.info("%s:   %s was killed by %s", lobby.code, victim, killer)
        for name in r.exiled:
            log.info("%s:   %s was voted out", lobby.code, name)
        if self.config.log_files:
            path = save_game_summary(lobby.code, self._round_summary_lines(lobby, result, minutes, seconds))
            if path is not None:
                log.info("%s: the round is saved in logs/games/%s", lobby.code, path.name)

    @staticmethod
    def _round_summary_lines(lobby: Lobby, result: str, minutes: int, seconds: int) -> List[str]:
        """The round as text for logs/games/ (always English, so that it can be sent with a bug report)."""
        r = lobby.round
        options = lobby.options
        lines = [
            f"Emergency Meeting {__version__}: a round in {lobby.code}",
            f"Date:     {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Map:      {options.map_name} ({options.mode_name}), {options.num_impostors} impostor(s)",
            f"Result:   {result}",
            f"Length:   {minutes} min {seconds} s, {r.meetings} meeting(s)",
            "",
            "Players:",
        ]
        for client_id, player in lobby.players.items():
            hs = player.connection.handshake
            role = r.roles.get(client_id)
            details = [
                "host" if client_id == lobby.host_id else ("bot" if player.is_bot else "player"),
                str(protocol.ROLES.get(role, f"role {role}")) if role is not None else "no role",
            ]
            if hs is not None and not player.is_bot:
                details.append(f"{hs.platform_text}, game version {hs.game_version_text}")
            lines.append(f"  {player.name}: " + ", ".join(details))
        lines += ["", "Killed:"] + [f"  {victim} by {killer}" for victim, killer in r.deaths] + (
            [] if r.deaths else ["  nobody"])
        lines += ["", "Voted out:"] + [f"  {name}" for name in r.exiled] + ([] if r.exiled else ["  nobody"])
        return lines

    def handle_alter_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player, lobby = self._host_check(connection, message)
        if lobby is None:
            return
        tag = message.read_byte()
        value = message.read_bool()
        lobby.send_to_all(self._forward(message), except_id=player.client_id)
        if tag == ALTER_GAME_PRIVACY:
            lobby.is_public = value
            log.info("%s is now %s", lobby.code, tr("public") if value else tr("private"))
            self.plugins.fire("on_privacy_changed", lobby, value)

    def handle_remove_player(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player, lobby = self._host_check(connection, message)
        if lobby is None:
            return
        client_id = message.read_packed_int32()
        reason = message.read_byte()
        self.remove_player(lobby, client_id, reason)

    def handle_kick_player(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player, lobby = self._host_check(connection, message)
        if lobby is None:
            return
        client_id = message.read_packed_int32()
        ban = message.read_bool()
        target = lobby.players.get(client_id)
        if target is None:
            return
        log.info("%s: %s was %s by the host", lobby.code, target.name, tr("banned") if ban else tr("kicked"))
        if ban and not target.is_bot:
            saved = self.access.ban(target.name, getattr(target.connection, "puid", ""), f"host:{player.name}")
            log.info("%s can't join the server again. Use /unban %s to change that.", saved.name, saved.name)

        w = MessageWriter().start_message(protocol.KICK_PLAYER)
        w.write_int32(lobby.code_int).write_packed_int32(client_id).write_bool(ban).end_message()
        lobby.send_to_all(w.to_bytes())
        self.remove_player(lobby, client_id, Reason.BANNED if ban else Reason.KICKED)

        # If the player doesn't leave by themselves, we disconnect them after a while.
        def force_disconnect() -> None:
            if target.connection.connected and target.connection.player is None:
                target.connection.disconnect(Reason.BANNED if ban else Reason.KICKED)

        asyncio.get_event_loop().call_later(5, force_disconnect)

    def handle_query_platform_ids(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        code_int = message.read_int32()
        lobby = self.lobbies.find(code_int)
        w = MessageWriter().start_message(protocol.QUERY_PLATFORM_IDS).write_int32(code_int)
        if lobby is not None:
            for p in lobby.players.values():
                p.write_platform(w)
        w.end_message()
        connection.send_reliable(w.to_bytes())

    # --- Game data: what happens in the game itself ------------------------

    def handle_game_data(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player = self._player(connection)
        if player is None or player.limbo != Limbo.IN_GAME:
            return
        lobby = player.lobby
        if message.read_int32() != lobby.code_int:
            return

        to_one = message.tag == protocol.GAME_DATA_TO
        target_id = message.read_packed_int32() if to_one else None

        # Look at the contents: some things the server has to react to itself.
        # A plugin can also stop a part, for example a chat message.
        kept: List[MessageReader] = []
        blocked = False
        parts = MessageReader(message.data[message.pos :]).messages()
        try:
            for part in parts:
                if self._inspect_game_data(lobby, player, part) is False:
                    blocked = True
                else:
                    kept.append(part)
        except ValueError as error:
            log.debug("Could not understand game data from %s: %s", player.name, error)
            blocked = False  # pass everything on unchanged if we didn't understand

        # ...and then pass it on to the others.
        if blocked:
            if not kept:
                self._run_after_forward()
                return
            payload = self._rebuild(message.tag or 0, lobby.code_int, target_id, kept)
        else:
            payload = self._forward(message)
        if target_id is not None:
            target = lobby.players.get(target_id)
            if target is not None and target.limbo == Limbo.IN_GAME:
                lobby.send([target], payload, reliable)
        else:
            lobby.send_to_all(payload, reliable, except_id=player.client_id)
        self._run_after_forward()

    def _run_after_forward(self) -> None:
        events, self._after_forward = self._after_forward, []
        for event in events:
            event()

    @staticmethod
    def _rebuild(tag: int, code_int: int, target_id: Optional[int], parts: List[MessageReader]) -> bytes:
        """Builds a new GameData message with only some parts left."""
        w = MessageWriter().start_message(tag).write_int32(code_int)
        if target_id is not None:
            w.write_packed_int32(target_id)
        for part in parts:
            w.write_message(part)
        w.end_message()
        return w.to_bytes()

    def _inspect_game_data(self, lobby: Lobby, player: Player, part: MessageReader) -> Optional[bool]:
        """Returns False if this part should not be passed on."""
        tag = part.tag

        if tag == protocol.GameDataTag.SCENE_CHANGE:
            client_id = part.read_packed_int32()
            scene = part.read_string()
            if client_id == player.client_id and scene == "OnlineGame":
                log.debug("%s has loaded the lobby in %s", player.name, lobby.code)
                lobby.sync_player_infos(player)
                lobby.spawn_player_info(player)

        elif tag == protocol.GameDataTag.SPAWN:
            self._inspect_spawn(lobby, part)

        elif tag == protocol.GameDataTag.DATA:
            net_id = part.read_packed_uint32()
            obj = lobby.server_objects.get(net_id)
            if obj is not None:
                try:
                    obj.update_from_data(part)  # save the latest name, color etc.
                except ValueError:
                    pass
            elif net_id == lobby.game_manager_net_id:
                self._inspect_game_manager(lobby, player, part)

        elif tag == protocol.GameDataTag.RPC:
            return self._inspect_rpc(lobby, player, part)

        elif tag == protocol.GameDataTag.DESPAWN:
            net_id = part.read_packed_uint32()
            lobby.server_objects.pop(net_id, None)
            lobby.player_controls.pop(net_id, None)
            lobby.transforms.pop(net_id, None)
            if net_id == lobby.meeting_hud_net_id:
                lobby.round.in_meeting = False
        return None

    # --- Things that happen in the lobby: settings, colors, chat ---------

    def _inspect_spawn(self, lobby: Lobby, part: MessageReader) -> None:
        """Someone (usually the host) creates an object. Some of them we want to keep track of."""
        spawn_type = part.read_packed_uint32()
        owner = part.read_packed_int32()
        part.read_byte()  # flags
        components = []  # (object number, data) for each part of the object
        for _ in range(part.read_packed_uint32()):
            components.append((part.read_packed_uint32(), part.read_message()))
        if not components:
            return
        net_id, data = components[0]

        if spawn_type == protocol.SPAWN_PLAYER_CONTROL:
            # The host sends ALL characters again to every new player who joins.
            # Only the first time is the character new; otherwise events would come twice.
            is_new = net_id not in lobby.player_controls
            lobby.player_controls[net_id] = owner
            try:
                data.read_bool()  # "is new"
                lobby.control_player_ids[net_id] = data.read_byte()
                if is_new and len(components) >= 3:
                    # Part 3 is the movement: sequence number and where the character stands.
                    transform_id, transform = components[2]
                    sequence = transform.read_uint16()
                    lobby.transforms[net_id] = (transform_id, sequence, transform.read_vector2())
            except ValueError:
                pass
            spawned = lobby.players.get(owner)
            if spawned is not None and is_new:
                # Wait until everyone knows about the character, otherwise for example
                # a welcome message from a plugin ends up nowhere.
                def after_spawn() -> None:
                    if isinstance(spawned.connection, BotConnection):
                        spawned.connection.on_spawned(net_id)
                    self.plugins.fire("on_player_spawned", lobby, spawned)

                self._after_forward.append(after_spawn)

        elif spawn_type == protocol.SPAWN_MEETING_HUD:
            lobby.meeting_hud_net_id = net_id

        elif spawn_type in (protocol.SPAWN_NORMAL_GAME_MANAGER, protocol.SPAWN_HIDE_AND_SEEK_MANAGER):
            lobby.game_manager_net_id = net_id
            lobby.options_part = 4 if spawn_type == protocol.SPAWN_NORMAL_GAME_MANAGER else 5
            for component in data.messages():
                if component.tag == lobby.options_part:
                    lobby.options = read_options(component)
                    log.debug("%s: the settings were read from GameManager", lobby.code)

    def _inspect_game_manager(self, lobby: Lobby, player: Player, part: MessageReader) -> None:
        """The host changed something in GameManager. Part number 4 (or 5) is the settings."""
        for component in part.messages():
            if component.tag != lobby.options_part:
                continue
            new_options = read_options(component)
            changes = differences(lobby.options, new_options)  # in English, for plugins
            for change in differences(lobby.options, new_options, translate=True):
                log.info("%s: %s changed %s", lobby.code, player.name, change)
            lobby.options = new_options
            if changes:
                self.plugins.fire("on_settings_changed", lobby, player, changes)

    def _inspect_rpc(self, lobby: Lobby, player: Player, part: MessageReader) -> Optional[bool]:
        net_id = part.read_packed_uint32()
        call = part.read_byte()
        later = self._after_forward.append  # runs when the message has been passed on
        fire = self.plugins.fire

        if call == protocol.RPC_SEND_CHAT:
            text = part.read_string()
            if fire("on_chat", lobby, player, text) is False:
                log.info("%s chat  %s: %s  (stopped by a plugin)", lobby.code, player.name, text)
                return False
            log.info("%s chat  %s: %s", lobby.code, player.name, text)

        elif call == protocol.RPC_SET_NAME:
            info = lobby.server_objects.get(part.read_uint32()) or lobby.info_for_control(net_id)
            name = part.read_string()
            if info is not None:
                info.name = name

        elif call in protocol.RPC_COSMETICS:
            info = lobby.info_for_control(net_id)
            item = part.read_string()
            sequence = part.read_byte()
            if info is not None:
                kind = protocol.RPC_COSMETICS[call]
                info.cosmetics[kind] = item
                info.sequence[kind] = sequence
                if kind == "nameplate" and item:
                    lobby.known_nameplate = item

        elif call == protocol.RPC_SET_LEVEL:
            info = lobby.info_for_control(net_id)
            if info is not None:
                info.level = part.read_packed_uint32()

        elif call == protocol.RPC_SET_COLOR:
            info_net_id = part.read_uint32()
            color = part.read_byte()
            # The color is for the player info with that number (safest), otherwise the character's owner.
            info = lobby.server_objects.get(info_net_id) or lobby.info_for_control(net_id)
            if info is not None:
                info.color = color
            owner = info.client_id if info is not None else lobby.player_controls.get(net_id)
            target = lobby.players.get(owner) if owner is not None else None
            if target is not None and lobby.colors.get(target.client_id) != color:
                lobby.colors[target.client_id] = color
                log.info("%s: %s has the color %s", lobby.code, target.name, protocol.COLORS.get(color, f"no. {color}"))
                later(lambda: fire("on_color_changed", lobby, target, target.color))

        elif call == protocol.RPC_SET_ROLE:
            target = lobby.player_by_control(net_id)
            role = part.read_uint16()
            if target is not None:
                lobby.round.roles[target.client_id] = role

        elif call == protocol.RPC_CHECK_MURDER:
            # The game asks the SERVER whether an impostor may kill. The server decides
            # and sends MurderPlayer to everyone (that's what Among Us's own servers do).
            if lobby.host_authority:
                return None  # the host has a mod and decides by itself
            target_net_id = part.read_packed_uint32()
            later(lambda: self._server_murder(lobby, player, net_id, target_net_id))
            return False

        elif call == protocol.RPC_CHECK_VANISH:
            if lobby.host_authority:
                return None
            later(lambda: self._server_phantom(lobby, player, net_id, protocol.RPC_START_VANISH, b""))
            return False

        elif call == protocol.RPC_CHECK_APPEAR:
            if lobby.host_authority:
                return None
            animate = MessageWriter().write_bool(part.read_bool()).to_bytes()
            later(lambda: self._server_phantom(lobby, player, net_id, protocol.RPC_START_APPEAR, animate))
            return False

        elif call == protocol.RPC_PROTECT_PLAYER:
            lobby.round.protected[part.read_packed_uint32()] = time.monotonic()

        elif call == protocol.RPC_MURDER_PLAYER:
            killer = lobby.player_by_control(net_id)
            victim_net_id = part.read_packed_uint32()
            victim = lobby.player_by_control(victim_net_id)
            result = part.read_int32()
            if result & protocol.MURDER_SUCCEEDED and victim is not None:
                lobby.round.dead.add(victim_net_id)
                lobby.round.deaths.append((victim.name, killer.name if killer else "?"))
                # Who killed isn't written now, then the log would give away the impostor.
                log.info("%s: %s has been killed! (%d dead)", lobby.code, victim.name, len(lobby.round.deaths))
                later(lambda: fire("on_player_killed", lobby, killer, victim))
            elif result & protocol.MURDER_FAILED_PROTECTED and victim is not None:
                log.info("%s: someone tried to kill %s, but a Guardian Angel protected them", lobby.code, victim.name)

        elif call == protocol.RPC_EXILED:
            lobby.round.dead.add(net_id)

        elif call == protocol.RPC_CLOSE_MEETING:
            lobby.round.in_meeting = False

        elif call == protocol.RPC_START_MEETING:
            reporter = lobby.player_by_control(net_id)
            body_id = part.read_byte()
            body = lobby.player_by_player_id(body_id) if body_id != protocol.NO_PLAYER else None
            who = reporter.name if reporter else tr("Someone")
            lobby.round.meetings += 1
            lobby.round.in_meeting = True
            if body is None:
                log.info("%s: MEETING! %s pressed the emergency button", lobby.code, who)
            else:
                log.info("%s: MEETING! %s found %s", lobby.code, who, body.name)
            later(lambda: fire("on_meeting_started", lobby, reporter, body))

        elif call == protocol.RPC_CAST_VOTE:
            voter = lobby.player_by_player_id(part.read_byte())
            part.read_byte()  # who the vote is for, not given away in the log
            if voter is not None:
                log.info("%s: %s has voted", lobby.code, voter.name)

        elif call == protocol.RPC_VOTING_COMPLETE:
            for _ in range(part.read_packed_uint32()):
                part.read_message()  # how each player voted
            exiled_id = part.read_byte()
            tie = part.read_bool()
            exiled = lobby.player_by_player_id(exiled_id) if exiled_id != protocol.NO_PLAYER else None
            if exiled is not None:
                lobby.round.exiled.append(exiled.name)
                log.info("%s: %s was voted out", lobby.code, exiled.name)
            else:
                log.info("%s: nobody was voted out%s", lobby.code, tr(" (tie)") if tie else "")
            later(lambda: fire("on_player_exiled", lobby, exiled))

        elif call == protocol.RPC_COMPLETE_TASK:
            if player is not None:
                lobby.round.tasks_done[player.client_id] = lobby.round.tasks_done.get(player.client_id, 0) + 1
        return None

    def handle_packed_game_data_to(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        """The host can send several "to one player" messages in one packet."""
        player = self._player(connection)
        if player is None or player.client_id != player.lobby.host_id:
            return
        lobby = player.lobby
        if message.read_packed_int32() != lobby.code_int:
            return
        for inner in message.messages():
            if inner.tag != protocol.GAME_DATA_TO:
                continue
            reader = MessageReader(inner.data, inner.tag)
            if reader.read_int32() != lobby.code_int:
                continue
            target = lobby.players.get(reader.read_packed_int32())
            for part in reader.messages():
                self._inspect_game_data(lobby, player, part)
            if target is not None and target.limbo == Limbo.IN_GAME:
                lobby.send([target], self._forward(inner), reliable)
        self._run_after_forward()

    # =====================================================================
    # Things the server decides: killing and the Phantom
    # =====================================================================

    def _server_murder(self, lobby: Lobby, sender: Player, killer_net_id: int, victim_net_id: int) -> None:
        """
        An impostor has pressed "Kill". Among Us lets the server (not the host)
        check that it's okay, and then tell everyone that someone died.
        """
        killer = lobby.player_by_control(killer_net_id)
        victim = lobby.player_by_control(victim_net_id)
        r = lobby.round
        if killer is None or victim is None or lobby.state != GameState.STARTED:
            return
        if killer.client_id != sender.client_id:
            log.warning("%s tried to kill with someone else's character, ignored", sender.name)
            return
        if killer_net_id in r.dead or victim_net_id in r.dead or r.in_meeting:
            return  # for example if you press Kill several times quickly
        role = r.roles.get(killer.client_id)
        if role in protocol.ROLES and role not in protocol.KILLER_ROLES:
            # (A role we don't know, for example from a new game version, may kill.)
            log.warning("%s tried to kill but is not an impostor, ignored", sender.name)
            return
        if r.roles.get(victim.client_id) in protocol.IMPOSTOR_ROLES:
            return  # impostors can't kill each other

        result = protocol.MURDER_SUCCEEDED
        protected_at = r.protected.pop(victim_net_id, None)
        duration = lobby.setting_number("Guardian Angel: Protection Duration", 10.0)
        if protected_at is not None and time.monotonic() - protected_at <= duration:
            result = protocol.MURDER_FAILED_PROTECTED

        args = MessageWriter().write_packed_uint32(victim_net_id).write_int32(result).to_bytes()
        self._server_rpc(lobby, sender, killer_net_id, protocol.RPC_MURDER_PLAYER, args)

    def _server_phantom(self, lobby: Lobby, sender: Player, net_id: int, call: int, args: bytes) -> None:
        """A Phantom wants to vanish or appear again. The server says yes."""
        owner = lobby.player_by_control(net_id)
        if owner is None or owner.client_id != sender.client_id or lobby.state != GameState.STARTED:
            return
        if lobby.round.roles.get(owner.client_id) != protocol.PHANTOM:
            return
        self._server_rpc(lobby, sender, net_id, call, args)

    def _server_rpc(self, lobby: Lobby, sender: Player, net_id: int, call: int, args: bytes) -> None:
        """Sends an RPC from the server to EVERYONE in the game (also the one who asked)."""
        rpc = MessageWriter().start_message(protocol.GameDataTag.RPC)
        rpc.write_packed_uint32(net_id).write_byte(call).write_bytes(args).end_message()
        rpc_bytes = rpc.to_bytes()
        # Let the server look at it itself (the log, plugins and bots), as if it came from the game.
        part = MessageReader(rpc_bytes).read_message()
        self._inspect_rpc(lobby, sender, part)
        w = MessageWriter().start_message(protocol.GAME_DATA).write_int32(lobby.code_int)
        w.write_bytes(rpc_bytes).end_message()
        lobby.send_to_all(w.to_bytes())
        self._run_after_forward()

    # =====================================================================
    # Leaving games and changing host
    # =====================================================================

    def remove_player(self, lobby: Lobby, client_id: int, reason: int) -> None:
        player = lobby.players.pop(client_id, None)
        if player is None:
            return
        player.connection.player = None
        lobby.colors.pop(client_id, None)
        log.info("%s left %s", player.name, lobby.code)

        if client_id == lobby.host_id:
            self._migrate_host(lobby)

        self.plugins.fire("on_player_left", lobby, player)

        if not any(not p.is_bot for p in lobby.players.values()):
            # Only bots (or nobody at all) left: close the game.
            for bot in list(lobby.players.values()):
                bot.connection.close()
                bot.connection.player = None
            lobby.players.clear()
            log.info("%s is empty and has been removed", lobby.code)
            self.lobbies.remove(lobby)
            return

        if lobby.state == GameState.NOT_STARTED:
            lobby.despawn_player_info(client_id)

        w = MessageWriter().start_message(protocol.REMOVE_PLAYER)
        w.write_int32(lobby.code_int).write_int32(client_id).write_int32(lobby.host_id)
        w.write_byte(reason).end_message()
        lobby.send_to_all(w.to_bytes(), except_id=client_id)

    def _migrate_host(self, lobby: Lobby) -> None:
        # A bot can't be host, so pick the first real player.
        new_host = next((p for p in lobby.players.values() if not p.is_bot), None)
        if new_host is None:
            lobby.host_id = -1
            return
        lobby.host_id = new_host.client_id
        log.info("%s: %s is the new host", lobby.code, new_host.name)
        self.plugins.fire("on_host_changed", lobby, new_host)
        if lobby.state == GameState.ENDED and new_host.limbo == Limbo.WAITING_FOR_HOST:
            lobby.state = GameState.NOT_STARTED
            self._join_lobby(lobby, new_host)
            self._let_waiting_players_in(lobby)

    def _warn_about_missing_udp(self) -> None:
        """If someone fetched a token but never connected: say so, it's a common problem."""
        now = time.monotonic()
        for name, (when, who) in list(self.lobbies.waiting_for_udp.items()):
            if now - when > 30:  # over mobile data it can take 10-15 seconds
                del self.lobbies.waiting_for_udp[name]
                log.warning(
                    "%s (%s) reached the server over HTTPS but never connected to the game over UDP.",
                    name,
                    who,
                )
                log.warning(
                    "  If you play through playit.gg: wait until the box PLAYIT IS READY! has been shown. "
                    "Otherwise: check that the device is on the same wifi as the server (on iPhone: "
                    "Settings > Privacy & Security > Local Network > turn on Among Us)."
                )

    # =====================================================================
    # Bots
    # =====================================================================

    def add_bot(self, lobby: Lobby, name: str, do_tasks: bool = False, walk: bool = True) -> Optional[Player]:
        host = lobby.host
        if host is None or lobby.state != GameState.NOT_STARTED:
            return None
        if len(lobby.players) >= lobby.options.max_players:
            return None

        taken = set(lobby.colors.values())
        color = next((c for c in protocol.COLORS if c not in taken), 0)
        version = host.connection.handshake.game_version if host.connection.handshake else 0

        self._next_client_id += 1
        bot = BotConnection(self, self._next_client_id, name, version, color, do_tasks, walk)
        bot.join(lobby.code_int)
        player = self._player(bot)  # type: ignore[arg-type]
        if player is None:
            return None
        return player

    async def cleanup_loop(self) -> None:
        """Removes games that were created but that nobody joined."""
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(5)
            self._warn_about_missing_udp()
            for lobby in self.lobbies.all():
                if not lobby.players and loop.time() - lobby.created_at > EMPTY_LOBBY_TIMEOUT:
                    log.debug("Removing the empty game %s", lobby.code)
                    self.lobbies.remove(lobby)

    # =====================================================================
    # Helpers
    # =====================================================================

    @staticmethod
    def _player(connection: Connection) -> Optional[Player]:
        player = connection.player
        return player if isinstance(player, Player) else None

    def _host_check(self, connection: Connection, message: MessageReader):
        """Checks that the sender is host in the right game. Reads the game code from the message."""
        player = self._player(connection)
        if player is None:
            return None, None
        lobby = player.lobby
        if message.read_int32() != lobby.code_int:
            return None, None
        if player.client_id != lobby.host_id:
            log.warning(
                "%s sent %s, but only the host may do that",
                player.name,
                protocol.message_name(message.tag or -1),
            )
            return None, None
        return player, lobby

    @staticmethod
    def _forward(message: MessageReader) -> bytes:
        """Turns a received message into bytes that can be passed on unchanged."""
        return MessageWriter().write_message(message).to_bytes()

    @staticmethod
    def _joined_game_message(lobby: Lobby, player: Player, others) -> bytes:
        w = MessageWriter().start_message(protocol.JOINED_GAME)
        w.write_int32(lobby.code_int).write_int32(player.client_id).write_int32(lobby.host_id)
        w.write_packed_uint32(len(others))
        for other in others:
            w.write_packed_int32(other.client_id)
            w.write_string(other.name)
            other.write_platform(w)
            w.write_packed_uint32(1)  # level
            w.write_string("")  # friend code
            w.write_string("")  # account id
        w.end_message()
        return w.to_bytes()

    @staticmethod
    def _join_game_message(lobby: Lobby, player: Player) -> bytes:
        """Tells the others in the lobby that `player` has arrived."""
        w = MessageWriter().start_message(protocol.JOIN_GAME)
        w.write_int32(lobby.code_int).write_int32(player.client_id).write_int32(lobby.host_id)
        w.write_string(player.name)
        player.write_platform(w)
        w.write_packed_uint32(1)  # level
        w.write_string("")  # friend code
        w.write_string("")  # account id
        w.end_message()
        return w.to_bytes()

    @staticmethod
    def _alter_game_message(lobby: Lobby) -> bytes:
        w = MessageWriter().start_message(protocol.ALTER_GAME)
        w.write_int32(lobby.code_int).write_byte(ALTER_GAME_PRIVACY).write_bool(lobby.is_public)
        w.end_message()
        return w.to_bytes()
