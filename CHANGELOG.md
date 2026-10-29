# Changelog

All versions of Emergency Meeting. Versions before 0.12.1 had Swedish texts.

## 0.13.0-alpha (2026-10-29)

The first public alpha.

- New README with a quick start, known limitations and the license
- Emergency Meeting is now licensed under GPL-3.0
- Bug report and idea templates on GitHub
- Scripts point to GitHub issues instead of asking you to send errors to someone

## 0.12.2 (2026-10-29)

- A join page from an older version that is still open in a browser asks for
  `/spel.json`. The server answers it again instead of logging
  "Unknown GET request" every few seconds

## 0.12.1 (2026-10-29)

- Everything is in English: the code, the join page, the scripts and the READMEs
- New setting `language` in `config.json`: the Terminal window can be in
  English or Swedish, everything else is always English
- The first start asks for the language with an arrow-key menu, before the name
- New command `/language`
- Plugins can translate their log messages with `TRANSLATIONS`
- New file names: `get-cloudflared.command`, `build-playit.command`,
  `test.command`, `playit-key.txt`, `ngrok-key.txt`, `ngrok-address.txt` and
  `logs/`. Files with the old Swedish names are renamed by the server

## 0.12.0 (2026-10-29)

- Name your server the first time it starts, change it with `/changeservername`.
  The name is the region in Among Us and the heading on the join page
- Commands in the Terminal window: `/help`, `/games`, `/address`, `/say`, `/stop`
- The box SERVER IS ONLINE! when everything is ready
- Colors in the log, following the Mac's dark or light mode
- `config.json` is created by the server instead of being part of the download

## 0.11.0 (2026-10-29)

- A new join page: the right steps for iPhone/iPad, Android, PC and Mac, the
  games on the server with their codes, a QR code and a ready-made message
  for friends
- The address as a QR code in the Terminal window

## 0.10.0 (2026-10-28)

- A fixed HTTPS address with ngrok, so friends only add the server once.
  The server downloads ngrok and asks for the key the first time.
  Cloudflare is the backup

## 0.9.0 (2026-10-28)

- Friends can play from their own homes through playit.gg, without changing
  anything in the router. The server starts playit.gg's program by itself
- GitHub builds playitd for Mac (Intel and Apple silicon)

## 0.8.0 (2026-10-27)

- The server decides kills, like Among Us's own servers (and the Phantom's
  vanish and appear)
- Bots walk around in the lobby and on the maps, walk to their tasks and
  stand at the table in meetings
- Meetings and votes fixed

## 0.7.1 (2026-10-27)

- Bots have clothes and complete player info
- A better "black box" report when someone is disconnected

## 0.7.0 (2026-10-27)

- Whole rounds and "Play Again"
- The log shows deaths, meetings, votes and a summary when the round is over
- Bots can do tasks and vote skip
- A "black box" that saves the latest messages when someone is disconnected
- New plugin events: `on_player_killed`, `on_meeting_started`, `on_player_exiled`

## 0.6.1 (2026-10-27)

- The box LOADING PLUGINS comes after the HTTPS box

## 0.6.0 (2026-10-27)

- Bots in the server (`lobby.add_bot`)
- The plugins moved to their own repo,
  [CEMP](https://github.com/xxMrMag1cxx/Common-Emergency-Meeting-Plugins)

## 0.5.0 (2026-10-27)

- The plugin system and the `plugins/` folder

## 0.4.0 (2026-10-27)

- Joining a game with the game code, several players in the same lobby
- The log shows changed game settings, colors and chat

## 0.3.0 (2026-10-27)

- Hosting a game, getting a game code and getting into the lobby

## 0.2.0 (2026-10-27)

- HTTPS through a Cloudflare tunnel, so the game can connect from other devices
- The first join page

## 0.1.0 (2026-10-27)

- The server receives Among Us, reads the player's name and version and
  answers with a message that shows up in the game
