# Plugins

A plugin is a Python file that the server loads when it starts. The plugin
can react to things that happen, for example when someone joins or writes
in the chat, and can send chat messages or disconnect players itself.

## Turning plugins on and off

- All `.py` files in this folder are loaded when the server starts.
- Files that start with `_` are skipped. Rename `botplugin.py` to
  `_botplugin.py` to turn it off, and back to turn it on.
- Restart the server after you have changed something.
- All plugins can be turned off with `"plugins": false` in `config.json`.

The server has no built-in plugins. Ready-made plugins are in
[Common Emergency Meeting Plugins (CEMP)](https://github.com/xxMrMag1cxx/Common-Emergency-Meeting-Plugins),
for example `botplugin.py` that adds bots with `/bot_add`.

## Plugins from another repo

Download the repo as a ZIP, unpack it and put the whole folder here in
`plugins/`. Every `.py` file in that folder becomes its own plugin:

```
plugins/
  README.md
  Common-Emergency-Meeting-Plugins-main/
    botplugin.py
```

A bigger plugin can also be its own folder with an `__init__.py` in it.

## Writing your own plugin

Create a new file here, for example `my_plugin.py`:

```python
NAME = "My plugin"
VERSION = "1.0"
AUTHOR = "Johannes"
DESCRIPTION = "says hi when the game starts"


def on_game_started(lobby):
    lobby.send_chat("Good luck everyone! Trust no one...")
```

`NAME`, `VERSION`, `AUTHOR` and `DESCRIPTION` are optional but are shown when
the server starts. Save, restart the server, and look at the box
**LOADING PLUGINS** that comes after the HTTPS box:

```
================================================================
  LOADING PLUGINS

  Loaded 1 plugin...
    - My plugin 1.0 by Johannes
        says hi when the game starts
================================================================
```

If a plugin can't be loaded, the box says so, and the whole error is printed
below it. The server keeps working anyway.

Write to the server window with `print(...)`, or with a logger:

```python
import logging
log = logging.getLogger("plugin.my_plugin")

def on_player_joined(lobby, player):
    log.info("%s came into %s", player.name, lobby.code)
```

## Translations

Everything in Emergency Meeting is written in English, but the server's
Terminal window can be in Swedish (the `"language"` setting in
`config.json`). A plugin can translate its own log messages and its
`DESCRIPTION` with a `TRANSLATIONS` dictionary:

```python
TRANSLATIONS = {
    "sv": {
        "says hi when the game starts": "säger hej när spelet startar",
        "%s came into %s": "%s kom in i %s",
    },
}
```

- Log messages are looked up by the text with the `%s`, before the values are
  filled in. The `%s` placeholders must be the same, in the same order, in
  both languages.
- Only the Terminal window is translated. Chat messages in the game and
  everything a plugin gets from the server (settings, results, colors) are
  always in English.
- `log.debug(...)` messages are never translated.

## Events

A plugin listens to an event by having a function with the same name.

| Function | When it runs |
|----------|--------------|
| `on_server_started()` | The server has started |
| `on_game_created(lobby, player)` | Someone has hosted a game and gone in as host |
| `on_player_joined(lobby, player)` | A player has joined the lobby |
| `on_player_spawned(lobby, player)` | The player's character has appeared (now `player.send_chat` works) |
| `on_player_left(lobby, player)` | A player has left |
| `on_host_changed(lobby, player)` | `player` is the new host |
| `on_chat(lobby, player, text)` | Someone writes in the chat. Return `False` to stop the message |
| `on_color_changed(lobby, player, color)` | Someone has changed color, for example `"Lime"` |
| `on_settings_changed(lobby, player, changes)` | The host changed settings. `changes` is a list of text, for example `["Kill Cooldown: 30 s -> 25 s"]` |
| `on_privacy_changed(lobby, is_public)` | The game became public (`True`) or private (`False`) |
| `on_game_started(lobby)` | A round starts |
| `on_player_killed(lobby, killer, victim)` | Someone was killed during the round |
| `on_meeting_started(lobby, reporter, body)` | A meeting starts. `body` is the dead player, or `None` if someone pressed the emergency button |
| `on_player_exiled(lobby, player)` | The voting is done. `player` was voted out, or `None` if nobody was voted out |
| `on_game_ended(lobby, result)` | A round is over. `result` is a text, for example `"The crew won by doing all tasks"` |

## What a plugin can use

**`lobby`** (a game):

| | |
|---|---|
| `lobby.code` | The game code, for example `"NUORZH"` |
| `lobby.player_list` | List of all players |
| `lobby.host` | The host |
| `lobby.find_player("Blobi")` | Looks up a player by name |
| `lobby.settings` | All settings, for example `lobby.settings["Kill Cooldown"]` → `"25 s"` |
| `lobby.map_name` | The map, for example `"The Skeld"` |
| `lobby.is_public` | `True` if the game is public |
| `lobby.is_started` | `True` if a round is going on |
| `lobby.send_chat("text")` | Writes in the chat to everyone (shows as if the host wrote it) |
| `lobby.bots` | List of all bots in the lobby |
| `lobby.add_bot("Bot_1")` | Adds a bot. Returns the bot, or `None` if it didn't work |
| `lobby.add_bot("Bot_1", do_tasks=True)` | The same, but the bot does tasks and votes skip during the round |
| `lobby.add_bot("Bot_1", walk=False)` | A bot that stands still instead of walking around |
| `lobby.remove_bot(bot)` | Removes a bot (the latest one if none is given) |

**`player`** (a player):

| | |
|---|---|
| `player.name` | The name |
| `player.color` | The color, for example `"Red"` (empty text if it isn't chosen yet) |
| `player.platform` | For example `"Steam (PC)"` or `"iPhone/iPad"` |
| `player.is_host` | `True` if the player is the host |
| `player.is_bot` | `True` if the player is a bot |
| `player.send_chat("text")` | Writes in the chat only to this player |
| `player.disconnect("text")` | Disconnects the player and shows the text |

Chat messages from the server show as if someone in the lobby wrote them,
because Among Us has no way of showing messages "from the server".

## Bots

A bot is a pretend player that the server controls. To the others it looks
like an ordinary player: it joins, gets a name and a color from the host and
says "ready" when a round starts.

The bot walks around in the lobby and on the map, around the walls. With
`do_tasks=True` it walks to its tasks and does them on the spot, and votes
skip in meetings when the discussion time is over. Impostor bots pretend to
do tasks. During a meeting the bot stands still at the table. It can't kill
or report and can never become the host. Bots can only be added in the
lobby, not during a round.

The maps (walls and where the tasks are) are in `server/mapdata/`.
