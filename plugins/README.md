# Plugins

Ett plugin är en Python-fil som servern laddar när den startar. Pluginet
kan reagera på saker som händer, till exempel när någon går med eller
skriver i chatten, och kan själv skicka chattmeddelanden eller koppla bort
spelare.

## Slå på och av

- Alla `.py`-filer i den här mappen laddas när servern startar.
- Filer som börjar med `_` hoppas över. Byt namn på `_tarning.py` till
  `tarning.py` för att slå på det, och tillbaka för att slå av det.
- Starta om servern efter att ni har ändrat något.
- Alla plugins kan stängas av med `"plugins": false` i `config.json`.

Pluginen som följer med:

| Fil            | Påslagen | Vad den gör |
|----------------|----------|-------------|
| `halsning.py`  | ja       | Välkomnar nya spelare i chatten |
| `_tarning.py`  | nej      | Chattkommandon: `/tärning`, `/hjälp`, `/inställning` |
| `_ordfilter.py`| nej      | Stoppar chattmeddelanden med vissa ord |

## Plugins från ett annat repo

Ladda ner repot som ZIP, packa upp det och lägg hela mappen här i
`plugins/`. Varje `.py`-fil i den mappen blir ett eget plugin:

```
plugins/
  halsning.py
  Emergency-Meeting-Plugins-main/
    tarning.py
    mitt_plugin.py
```

Ett större plugin kan också vara en egen mapp med en `__init__.py` i.

## Skriva ett eget plugin

Skapa en ny fil här, t.ex. `mitt_plugin.py`:

```python
NAME = "Mitt plugin"
DESCRIPTION = "säger hej när spelet startar"


def on_game_started(lobby):
    lobby.send_chat("Lycka till alla! Lita inte på någon...")
```

Spara, starta om servern, och kolla att det står
`Laddade pluginet Mitt plugin` i serverfönstret. Om pluginet har ett fel
skrivs felet ut, men servern fortsätter att fungera.

Använd `log.info(...)` (se `halsning.py`) eller `print(...)` för att skriva
till serverfönstret.

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

**`player`** (en spelare):

| | |
|---|---|
| `player.name` | Namnet |
| `player.color` | Färgen, t.ex. `"Red"` (tom text om den inte är vald än) |
| `player.platform` | T.ex. `"Steam (PC)"` eller `"iPhone/iPad"` |
| `player.is_host` | `True` om spelaren är värd |
| `player.send_chat("text")` | Skriver i chatten bara till den här spelaren |
| `player.disconnect("text")` | Kopplar bort spelaren och visar texten |

Chattmeddelanden från servern syns som att någon i lobbyn skrev dem,
eftersom Among Us inte har något sätt att visa meddelanden "från servern".
