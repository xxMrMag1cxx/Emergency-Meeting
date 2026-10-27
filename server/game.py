"""
Spellogiken: vad servern gör med meddelandena från spelarna.

Flödet när någon trycker "Create Game":

  1. HostGame   spelet skickar sina inställningar  -> vi skapar en lobby
                och svarar med spelkoden
  2. JoinGame   spelet går med i sitt eget spel     -> vi svarar JoinedGame
                och spelaren blir värd
  3. GameData   värden laddar lobbyn och skickar    -> vi skickar vidare till
                speldata hela tiden                    alla andra spelare

När fler går med med spelkoden händer samma sak från steg 2, och servern
berättar för alla i lobbyn att någon ny har kommit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List, Optional

from . import protocol
from .config import Config
from .hazel import Connection
from .lobby import GameState, Limbo, Lobby, LobbyManager, Player
from .messages import MessageReader, MessageWriter
from .options import GameOptions, differences, read_options
from .plugins import PluginManager

log = logging.getLogger("spel")

Reason = protocol.DisconnectReason
ALTER_GAME_PRIVACY = 1
EMPTY_LOBBY_TIMEOUT = 60  # sekunder innan en lobby utan spelare tas bort


class Game:
    def __init__(self, config: Config, lobbies: LobbyManager, plugins: Optional[PluginManager] = None):
        self.config = config
        self.lobbies = lobbies
        self.plugins = plugins or PluginManager()
        self._next_client_id = 0
        # Plugin-händelser som ska köras först när speldatan har skickats vidare.
        self._after_forward: List[Callable[[], None]] = []

    # =====================================================================
    # Anslutningar
    # =====================================================================

    def on_connect(self, connection: Connection) -> None:
        self._next_client_id += 1
        connection.client_id = self._next_client_id

        hs = connection.handshake
        if hs is None:
            log.info("En spelare anslöt från %s (kunde inte läsa detaljerna)", connection.address[0])
            return
        log.info(
            "%s anslöt (spelversion %s, %s)",
            hs.name,
            hs.game_version_text,
            hs.platform_text,
        )

    def on_disconnect(self, connection: Connection, why: str) -> None:
        player = self._player(connection)
        if player is not None:
            self.remove_player(player.lobby, player.client_id, Reason.EXIT_GAME)
        log.info("%s kopplade från (%s)", connection.name, why)

    # =====================================================================
    # Meddelanden
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
                log.info("%s skickade %s (hanteras inte än)", connection.name, protocol.message_name(tag))
            return

        try:
            handler(connection, message, reliable)
        except ValueError as error:
            log.warning(
                "Kunde inte läsa %s från %s: %s",
                protocol.message_name(tag),
                connection.name,
                error,
            )

    # --- Skapa och gå med ------------------------------------------------

    def handle_host_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        try:
            options = read_options(message)
        except ValueError:
            log.warning("Kunde inte läsa spelinställningarna från %s, använder standardvärden", connection.name)
            options = GameOptions()

        lobby = self.lobbies.create(options)
        log.info(
            "%s skapade spelet %s (%s, %s, max %d spelare, %d impostor%s)",
            connection.name,
            lobby.code,
            options.map_name,
            options.mode_name,
            options.max_players,
            options.num_impostors,
            "s" if options.num_impostors != 1 else "",
        )

        # Svara med spelkoden. Spelet skickar sedan JoinGame med den.
        w = MessageWriter().start_message(protocol.HOST_GAME).write_int32(lobby.code_int).end_message()
        connection.send_reliable(w.to_bytes())

    def handle_join_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        code_int = message.read_int32()
        lobby = self.lobbies.find(code_int)
        if lobby is None:
            log.info("%s försökte gå med i ett spel som inte finns", connection.name)
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
            if player is not None:  # var med i ett annat spel
                self.remove_player(player.lobby, player.client_id, Reason.EXIT_GAME)
            player = Player(connection, lobby)
            connection.player = player
            lobby.players[player.client_id] = player
            if lobby.host_id == -1:
                lobby.host_id = player.client_id
        elif player.limbo == Limbo.IN_GAME:
            connection.disconnect(Reason.CUSTOM, "Du är redan med i spelet.")
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
        role = "värd" if player.client_id == lobby.host_id else "spelare"
        self._warn_if_other_version(lobby, player)
        log.info(
            "%s gick med i %s som %s (%d/%d spelare)",
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

    @staticmethod
    def _warn_if_other_version(lobby: Lobby, player: Player) -> None:
        host = lobby.host
        if host is None or host is player or not host.connection.handshake or not player.connection.handshake:
            return
        mine = player.connection.handshake.game_version
        theirs = host.connection.handshake.game_version
        if mine != theirs:
            log.warning(
                "%s har en annan spelversion (%s) än värden %s (%s). Det kan krångla, "
                "uppdatera spelet på båda om det blir konstigt.",
                player.name,
                protocol.decode_game_version(mine),
                host.name,
                protocol.decode_game_version(theirs),
            )

    def _join_after_round(self, lobby: Lobby, player: Player) -> None:
        """Efter en runda: värden måste komma tillbaka först."""
        if player.client_id == lobby.host_id:
            lobby.state = GameState.NOT_STARTED
            self._join_lobby(lobby, player)
            self._let_waiting_players_in(lobby)
            return

        log.info("%s väntar på att värden ska komma tillbaka till %s", player.name, lobby.code)
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

    # --- Spelets gång -----------------------------------------------------

    def handle_start_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player, lobby = self._host_check(connection, message)
        if lobby is None:
            return
        lobby.state = GameState.STARTED
        log.info("%s: spelet startar! (%d spelare)", lobby.code, len(lobby.players))
        lobby.send_to_all(self._forward(message))
        self.plugins.fire("on_game_started", lobby)

    def handle_end_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player, lobby = self._host_check(connection, message)
        if lobby is None:
            return
        lobby.state = GameState.ENDED
        log.info("%s: rundan är slut", lobby.code)
        lobby.send_to_all(self._forward(message))
        for p in lobby.players.values():
            p.limbo = Limbo.PRE_SPAWN
        # Spelarinfo skapas på nytt när alla kommer tillbaka till lobbyn.
        lobby.server_objects.clear()
        lobby.player_controls.clear()
        self.plugins.fire("on_game_ended", lobby)

    def handle_alter_game(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player, lobby = self._host_check(connection, message)
        if lobby is None:
            return
        tag = message.read_byte()
        value = message.read_bool()
        lobby.send_to_all(self._forward(message), except_id=player.client_id)
        if tag == ALTER_GAME_PRIVACY:
            lobby.is_public = value
            log.info("%s är nu %s", lobby.code, "offentligt" if value else "privat")
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
        log.info("%s: %s blev %s av värden", lobby.code, target.name, "bannad" if ban else "utsparkad")

        w = MessageWriter().start_message(protocol.KICK_PLAYER)
        w.write_int32(lobby.code_int).write_packed_int32(client_id).write_bool(ban).end_message()
        lobby.send_to_all(w.to_bytes())
        self.remove_player(lobby, client_id, Reason.BANNED if ban else Reason.KICKED)

        # Om spelaren inte lämnar själv kopplar vi bort hen efter en stund.
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

    # --- Speldata: det som händer i själva spelet ------------------------

    def handle_game_data(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        player = self._player(connection)
        if player is None or player.limbo != Limbo.IN_GAME:
            return
        lobby = player.lobby
        if message.read_int32() != lobby.code_int:
            return

        to_one = message.tag == protocol.GAME_DATA_TO
        target_id = message.read_packed_int32() if to_one else None

        # Titta på innehållet: några saker måste servern själv reagera på.
        # Ett plugin kan också stoppa en del, t.ex. ett chattmeddelande.
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
            log.debug("Kunde inte tolka speldata från %s: %s", player.name, error)
            blocked = False  # skicka vidare allt oförändrat om vi inte förstod

        # ...och skicka sedan vidare till de andra.
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
        """Bygger ett nytt GameData-meddelande med bara vissa delar kvar."""
        w = MessageWriter().start_message(tag).write_int32(code_int)
        if target_id is not None:
            w.write_packed_int32(target_id)
        for part in parts:
            w.write_message(part)
        w.end_message()
        return w.to_bytes()

    def _inspect_game_data(self, lobby: Lobby, player: Player, part: MessageReader) -> Optional[bool]:
        """Returnerar False om den här delen inte ska skickas vidare."""
        tag = part.tag

        if tag == protocol.GameDataTag.SCENE_CHANGE:
            client_id = part.read_packed_int32()
            scene = part.read_string()
            if client_id == player.client_id and scene == "OnlineGame":
                log.debug("%s har laddat lobbyn i %s", player.name, lobby.code)
                lobby.sync_player_infos(player)
                lobby.spawn_player_info(player)

        elif tag == protocol.GameDataTag.SPAWN:
            self._inspect_spawn(lobby, part)

        elif tag == protocol.GameDataTag.DATA:
            net_id = part.read_packed_uint32()
            obj = lobby.server_objects.get(net_id)
            if obj is not None:
                obj.state = part.read_rest()  # spara senaste namn, färg osv.
            elif net_id == lobby.game_manager_net_id:
                self._inspect_game_manager(lobby, player, part)

        elif tag == protocol.GameDataTag.RPC:
            return self._inspect_rpc(lobby, player, part)

        elif tag == protocol.GameDataTag.DESPAWN:
            net_id = part.read_packed_uint32()
            lobby.server_objects.pop(net_id, None)
            lobby.player_controls.pop(net_id, None)
        return None

    # --- Saker som händer i lobbyn: inställningar, färger, chatt ---------

    def _inspect_spawn(self, lobby: Lobby, part: MessageReader) -> None:
        """Någon (oftast värden) skapar ett objekt. Vissa vill vi hålla koll på."""
        spawn_type = part.read_packed_uint32()
        owner = part.read_packed_int32()
        part.read_byte()  # flaggor
        if part.read_packed_uint32() < 1:
            return
        net_id = part.read_packed_uint32()
        data = part.read_message()

        if spawn_type == protocol.SPAWN_PLAYER_CONTROL:
            lobby.player_controls[net_id] = owner
            spawned = lobby.players.get(owner)
            if spawned is not None:
                # Vänta tills alla har fått veta om gubben, annars hamnar t.ex.
                # ett välkomstmeddelande från ett plugin ingenstans.
                self._after_forward.append(
                    lambda: self.plugins.fire("on_player_spawned", lobby, spawned)
                )

        elif spawn_type in (protocol.SPAWN_NORMAL_GAME_MANAGER, protocol.SPAWN_HIDE_AND_SEEK_MANAGER):
            lobby.game_manager_net_id = net_id
            lobby.options_part = 4 if spawn_type == protocol.SPAWN_NORMAL_GAME_MANAGER else 5
            for component in data.messages():
                if component.tag == lobby.options_part:
                    lobby.options = read_options(component)
                    log.debug("%s: inställningarna lästa från GameManager", lobby.code)

    def _inspect_game_manager(self, lobby: Lobby, player: Player, part: MessageReader) -> None:
        """Värden har ändrat något i GameManager. Del nummer 4 (eller 5) är inställningarna."""
        for component in part.messages():
            if component.tag != lobby.options_part:
                continue
            new_options = read_options(component)
            changes = differences(lobby.options, new_options)
            for change in changes:
                log.info("%s: %s ändrade %s", lobby.code, player.name, change)
            lobby.options = new_options
            if changes:
                self.plugins.fire("on_settings_changed", lobby, player, changes)

    def _inspect_rpc(self, lobby: Lobby, player: Player, part: MessageReader) -> Optional[bool]:
        net_id = part.read_packed_uint32()
        call = part.read_byte()

        if call == protocol.RPC_SEND_CHAT:
            text = part.read_string()
            if self.plugins.fire("on_chat", lobby, player, text) is False:
                log.info("%s chatt  %s: %s  (stoppat av ett plugin)", lobby.code, player.name, text)
                return False
            log.info("%s chatt  %s: %s", lobby.code, player.name, text)

        elif call == protocol.RPC_SET_COLOR:
            part.read_uint32()
            color = part.read_byte()
            owner = lobby.player_controls.get(net_id)
            target = lobby.players.get(owner) if owner is not None else None
            if target is not None and lobby.colors.get(target.client_id) != color:
                lobby.colors[target.client_id] = color
                log.info(
                    "%s: %s har färgen %s",
                    lobby.code,
                    target.name,
                    protocol.COLORS.get(color, f"nr {color}"),
                )
                self._after_forward.append(
                    lambda: self.plugins.fire("on_color_changed", lobby, target, target.color)
                )
        return None

    def handle_packed_game_data_to(self, connection: Connection, message: MessageReader, reliable: bool) -> None:
        """Värden kan skicka flera "till en spelare"-meddelanden i ett paket."""
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
    # Lämna spel och byta värd
    # =====================================================================

    def remove_player(self, lobby: Lobby, client_id: int, reason: int) -> None:
        player = lobby.players.pop(client_id, None)
        if player is None:
            return
        player.connection.player = None
        lobby.colors.pop(client_id, None)
        log.info("%s lämnade %s", player.name, lobby.code)

        if client_id == lobby.host_id:
            self._migrate_host(lobby)

        self.plugins.fire("on_player_left", lobby, player)

        if not lobby.players:
            log.info("%s är tomt och har tagits bort", lobby.code)
            self.lobbies.remove(lobby)
            return

        if lobby.state == GameState.NOT_STARTED:
            lobby.despawn_player_info(client_id)

        w = MessageWriter().start_message(protocol.REMOVE_PLAYER)
        w.write_int32(lobby.code_int).write_int32(client_id).write_int32(lobby.host_id)
        w.write_byte(reason).end_message()
        lobby.send_to_all(w.to_bytes(), except_id=client_id)

    def _migrate_host(self, lobby: Lobby) -> None:
        new_host = next(iter(lobby.players.values()), None)
        if new_host is None:
            lobby.host_id = -1
            return
        lobby.host_id = new_host.client_id
        log.info("%s: %s är ny värd", lobby.code, new_host.name)
        self.plugins.fire("on_host_changed", lobby, new_host)
        if lobby.state == GameState.ENDED and new_host.limbo == Limbo.WAITING_FOR_HOST:
            lobby.state = GameState.NOT_STARTED
            self._join_lobby(lobby, new_host)
            self._let_waiting_players_in(lobby)

    async def cleanup_loop(self) -> None:
        """Tar bort spel som skapades men där ingen gick med."""
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(10)
            for lobby in self.lobbies.all():
                if not lobby.players and loop.time() - lobby.created_at > EMPTY_LOBBY_TIMEOUT:
                    log.debug("Tar bort tomma spelet %s", lobby.code)
                    self.lobbies.remove(lobby)

    # =====================================================================
    # Hjälpfunktioner
    # =====================================================================

    @staticmethod
    def _player(connection: Connection) -> Optional[Player]:
        player = connection.player
        return player if isinstance(player, Player) else None

    def _host_check(self, connection: Connection, message: MessageReader):
        """Kollar att avsändaren är värd i rätt spel. Läser spelkoden ur meddelandet."""
        player = self._player(connection)
        if player is None:
            return None, None
        lobby = player.lobby
        if message.read_int32() != lobby.code_int:
            return None, None
        if player.client_id != lobby.host_id:
            log.warning(
                "%s skickade %s, men bara värden får göra det",
                player.name,
                protocol.message_name(message.tag or -1),
            )
            return None, None
        return player, lobby

    @staticmethod
    def _forward(message: MessageReader) -> bytes:
        """Gör om ett mottaget meddelande till bytes som kan skickas vidare oförändrat."""
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
            w.write_packed_uint32(1)  # nivå
            w.write_string("")  # vänkod
            w.write_string("")  # konto-id
        w.end_message()
        return w.to_bytes()

    @staticmethod
    def _join_game_message(lobby: Lobby, player: Player) -> bytes:
        """Berättar för de andra i lobbyn att `player` har kommit."""
        w = MessageWriter().start_message(protocol.JOIN_GAME)
        w.write_int32(lobby.code_int).write_int32(player.client_id).write_int32(lobby.host_id)
        w.write_string(player.name)
        player.write_platform(w)
        w.write_packed_uint32(1)  # nivå
        w.write_string("")  # vänkod
        w.write_string("")  # konto-id
        w.end_message()
        return w.to_bytes()

    @staticmethod
    def _alter_game_message(lobby: Lobby) -> bytes:
        w = MessageWriter().start_message(protocol.ALTER_GAME)
        w.write_int32(lobby.code_int).write_byte(ALTER_GAME_PRIVACY).write_bool(lobby.is_public)
        w.end_message()
        return w.to_bytes()
