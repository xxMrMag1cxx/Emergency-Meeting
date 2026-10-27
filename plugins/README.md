# Plugins

Ett plugin är en Python-fil som servern laddar när den startar. Pluginet
kan reagera på saker som händer, till exempel när någon går med eller
skriver i chatten, och kan själv skicka chattmeddelanden eller koppla bort
spelare.

## Slå på och av

- Alla `.py`-filer i den här mappen laddas när servern startar.
- Filer som börjar med `_` hoppas över. Byt namn på `botplugin.py` till
  `_botplugin.py` för att slå av det, och tillbaka för att slå på det.
- Starta om servern efter att ni har ändrat något.
- Alla plugins kan stängas av med `"plugins": false` i `config.json`.

Servern har inga plugins inbyggda. Färdiga plugins finns i
[Common Emergency Meeting Plugins (CEMP)](https://github.com/xxMrMag1cxx/Common-Emergency-Meeting-Plugins),
till exempel `botplugin.py` som lägger till bots med `/bot_add`.

## Plugins från ett annat repo

Ladda ner repot som ZIP, packa upp det och lägg hela mappen här i
`plugins/`. Varje `.py`-fil i den mappen blir ett eget plugin:

```
plugins/
  README.md
  Common-Emergency-Meeting-Plugins-main/
    botplugin.py
```

Ett större plugin kan också vara en egen mapp med en `__init__.py` i.

## Skriva ett eget plugin

Skapa en ny fil här, t.ex. `mitt_plugin.py`:

```python
NAME = "Mitt plugin"
VERSION = "1.0"
AUTHOR = "Johannes"
DESCRIPTION = "säger hej när spelet startar"


def on_game_started(lobby):
    lobby.send_chat("Lycka till alla! Lita inte på någon...")
```

`NAME`, `VERSION`, `AUTHOR` och `DESCRIPTION` är frivilliga men visas när
servern startar. Spara, starta om servern, och kolla rutan
**LADDAR PLUGINS** som kommer efter HTTPS-rutan:

```
================================================================
  LADDAR PLUGINS

  Laddat 1 plugin...
    - Mitt plugin 1.0 av Johannes
        säger hej när spelet startar
================================================================
```

Om ett plugin inte går att ladda står det i rutan, och hela felet skrivs
ut under den. Servern fortsätter att fungera ändå.

Skriv till serverfönstret med `print(...)`, eller med en logger:

```python
import logging
log = logging.getLogger("plugin.mitt_plugin")

def on_player_joined(lobby, player):
    log.info("%s kom in i %s", player.name, lobby.code)
```

## Händelser

Ett plugin lyssnar på en händelse genom att ha en funktion med samma namn.

| Funktion | När den körs |
|----------|--------------|
| `on_server_started()` | Servern har startat |
| `on_game_created(lobby, player)` | Någon har skapat ett spel och gått in som värd |
| `on_player_joined(lobby, player)` | En spelare har gått med i lobbyn |
| `on_player_spawned(lobby, player)` | Spelarens gubbe har dykt upp (nu fungerar `player.send_chat`) |
| `on_player_left(lobby, player)` | En spelare har lämnat |
| `on_host_changed(lobby, player)` | `player` är ny värd |
| `on_chat(lobby, player, text)` | Någon skriver i chatten. Returnera `False` för att stoppa meddelandet |
| `on_color_changed(lobby, player, color)` | Någon har bytt färg, t.ex. `"Lime"` |
| `on_settings_changed(lobby, player, changes)` | Värden ändrade inställningar. `changes` är en lista med text, t.ex. `["Kill Cooldown: 30 s -> 25 s"]` |
| `on_privacy_changed(lobby, is_public)` | Spelet blev offentligt (`True`) eller privat (`False`) |
| `on_game_started(lobby)` | En runda startar |
| `on_game_ended(lobby)` | En runda är slut |

## Vad ett plugin kan använda

**`lobby`** (ett spel):

| | |
|---|---|
| `lobby.code` | Spelkoden, t.ex. `"NUORZH"` |
| `lobby.player_list` | Lista med alla spelare |
| `lobby.host` | Värden |
| `lobby.find_player("Blobi")` | Letar upp en spelare på namnet |
| `lobby.settings` | Alla inställningar, t.ex. `lobby.settings["Kill Cooldown"]` → `"25 s"` |
| `lobby.map_name` | Kartan, t.ex. `"The Skeld"` |
| `lobby.is_public` | `True` om spelet är offentligt |
| `lobby.is_started` | `True` om en runda pågår |
| `lobby.send_chat("text")` | Skriver i chatten till alla (syns som att värden skrev) |
| `lobby.bots` | Lista med alla bots i lobbyn |
| `lobby.add_bot("Bot_1")` | Lägger till en bot. Ger tillbaka boten, eller `None` om det inte gick |
| `lobby.remove_bot(bot)` | Tar bort en bot (den senaste om ingen anges) |

**`player`** (en spelare):

| | |
|---|---|
| `player.name` | Namnet |
| `player.color` | Färgen, t.ex. `"Red"` (tom text om den inte är vald än) |
| `player.platform` | T.ex. `"Steam (PC)"` eller `"iPhone/iPad"` |
| `player.is_host` | `True` om spelaren är värd |
| `player.is_bot` | `True` om spelaren är en bot |
| `player.send_chat("text")` | Skriver i chatten bara till den här spelaren |
| `player.disconnect("text")` | Kopplar bort spelaren och visar texten |

Chattmeddelanden från servern syns som att någon i lobbyn skrev dem,
eftersom Among Us inte har något sätt att visa meddelanden "från servern".

## Bots

En bot är en låtsasspelare som servern styr. För de andra ser den ut som en
vanlig spelare: den går med, får namn och färg av värden och säger "redo"
när en runda startar. Den kan inte röra sig eller göra uppdrag än, och den
kan aldrig bli värd. Bots kan bara läggas till i lobbyn, inte under en runda.
