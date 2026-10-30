# Changelog

All versions of Emergency Meeting. Versions before 0.12.1 had Swedish texts.

## 0.13.4-alpha (2026-10-30)

- Windows 10 and 11: start the server with `start.bat`. Colors, the input line
  at the bottom, the arrow-key language menu, hidden keys and `/reboot` work
  in the Windows console and Windows Terminal
- Linux: start the server with `./start.sh`
- On Windows and Linux the server downloads playitd (playit.gg's own files)
  and cloudflared by itself when they are missing. ngrok is downloaded on all
  three
- Releases get one zip file for each system under Assets (macOS, Windows,
  Linux), made by GitHub Actions (`tools/make_release.py`)
- The Terminal window says "computer" instead of "Mac"
- Fixed: Cloudflare's own address (`api.trycloudflare.com`) in an error
  message was taken for the tunnel's address, and the server then waited 90
  seconds for nothing

## 0.13.3-alpha (2026-10-30)

- Bans that last: when the host bans someone, the server saves it in
  `bans.json` (with the player's account, so a new name doesn't help). New
  commands `/ban`, `/unban` and `/bans`
- Allowed names: with `"only_allowed_names": true`, only the names in
  `allowed-names.txt` can join. New commands `/allow`, `/disallow` and
  `/allowed`
- A password for the join page with `page_password`
- Log files: everything in the Terminal window is saved in `logs/<date>.log`,
  every round gets a summary in `logs/games/`, and old files are removed after
  `keep_logs_days` (14)
- Game versions per game: a player whose version doesn't fit with the host's
  gets a message and can't join that game. `allow_version_mixing` lets them in
  anyway. PC and phone versions from the same update fit together, and the log
  no longer warns about them

## 0.13.2-alpha (2026-10-30)

- If a room is online, `/reboot` first warns that all online rooms will be
  disconnected and asks you to type yes or no. (This was meant to be in
  0.13.1-alpha, but came after the release was made.)
- `/reload` keeps playit.gg running if it works, so friends who play from home
  stay connected. If playit.gg has to be restarted while someone plays from
  home, it warns first in the same way
- The line you type on stays at the bottom of the Terminal window, and new
  messages show up above it. The up and down arrows bring back earlier
  commands. Turn it off with `"input_line": false`
- New commands `/settings` (shows all settings) and `/setting <name> = <value>`
  (changes one, used after a restart). `/setting <name>` shows the value
- The server is made for Among Us 19.0. New settings
  `allow_future_game_versions` and `allow_older_game_versions` (both true):
  with false, newer or older versions of the game can't join and get a message
  in the game. The log says when someone has another version
- playit.gg: the server waits until the old playitd has closed before it
  starts a new one, and gives playit.gg a few seconds to let go of it. If the
  test packet doesn't come through, playitd is restarted once. The messages
  playitd writes while it signs in again ("timeout waiting for register
  response") are only shown with `"debug": true`
- Copyright line in the README, LICENSE and the box at the top of the window

## 0.13.1-alpha (2026-10-29)

- The first start is a guide, one thing at a time: the language, the name,
  ngrok and playit.gg (approve the server, get a tunnel and wait until its
  address works). Enter skips ngrok or playit.gg
- The server starts one part at a time and checks each part before the next:
  plugins, the game server, the join page, playit.gg and last the HTTPS
  address. SERVER IS ONLINE! comes only when everything is ready
- If a part doesn't start, the server restarts itself once. If it goes wrong
  again, it starts the rest as well as it can and shows what to do
- New command `/reload`: starts playit.gg and the HTTPS address again
- New command `/reboot`: restarts the whole server in the same window
- playit.gg: the server waits until playitd is connected before it creates
  the tunnel, and tries several times. If it still doesn't work, the box shows
  playit.gg's answer (for example "confirm your email first")
- Test packets check that the game server and the way through playit.gg work
- READMEs: "Made with AI"
- Fixed: "Setup 3 of 4" and the text after it ended up on the same line when
  ngrok or playit.gg already had a key

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
