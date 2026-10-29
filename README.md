# Emergency Meeting

Our own Among Us server, built from scratch in Python. The server runs on a
Mac (macOS 12.7 Monterey or newer) and the goal is for it to run the game
with our own plugins.

## Roadmap

- [x] **Step 1:** The server receives the game, reads the player's name and
      version, and answers with its own message that shows up in the game
- [x] **Step 2:** HTTPS through a Cloudflare tunnel, so that the game can
      connect from other devices
- [x] **Step 3:** Host a game, get a game code and get into the lobby
      (needs testing with the real game)
- [x] **Step 3b:** The log shows every change of the game settings
- [ ] **Step 4:** Join a game with the game code, several players in the same
      lobby (done in the server, needs testing with two devices)
- [x] **Step 5:** Play a whole round and "Play Again". The log shows meetings,
      deaths and votes, and a summary when the round is over
      (needs testing with the real game)
- [x] **Step 6:** Our own plugin system, see [plugins/README.md](plugins/README.md)
- [x] **Step 7:** Impostors can kill (the server decides, like Among Us's own
      servers). Bots walk around in the lobby and on all maps and walk to
      their tasks (needs testing with the real game)
- [x] **Step 8:** Friends can play from their own homes, on a computer or a
      phone, through playit.gg. Nothing needs to be changed in the router
- [x] **Step 9:** An HTTPS address that is the same every time (ngrok), so
      that friends only have to add the server once
- [x] **Step 10:** A join page that shows the right steps for every device,
      the game codes, a QR code and a ready-made message for friends
- [x] **Step 11:** Our own name for the server, commands in the Terminal
      window (`/help`) and colors in the log (needs testing on the Mac)
- [x] **Step 12:** Everything in English, and the Terminal window in English
      or Swedish (needs testing on the Mac)

## Get started on the Mac

### 1. Check that Python is there

Open **Terminal** (in Applications → Utilities) and type:

```
python3 --version
```

If it says `Python 3.8` or higher, everything is ready. If it says something
else, download the latest Python from <https://www.python.org/downloads/macos/>
(choose "macOS 64-bit universal2 installer") and install it.

The server only uses what comes with Python.

### 2. Get the code

On the project's GitHub page: click the green **Code** button and choose
**Download ZIP**. Unpack the folder. It doesn't matter where it ends up, all
the files below are started with a double-click in Finder.

> The first time macOS says a file can't be opened because it comes from the
> internet: right-click the file, choose **Open** and then **Open** again.

### 3. Get cloudflared (once)

Double-click **`get-cloudflared.command`**.

Among Us requires HTTPS when the game and the server are on different
devices. The server prefers ngrok (see below), and cloudflared is the backup
if ngrok doesn't work. cloudflared gives a free HTTPS address through
Cloudflare, without an account. The script picks a version that works on
your macOS by itself.

### 4. Start the server

Double-click **`start.command`**. If macOS asks if Python may accept
incoming connections, choose **Allow**.

The first time, the server asks for a few things. They are only needed once:

- **Select server language**: choose **English** or **Swedish** with the
  arrow keys and press Enter. That is the language of the server's Terminal
  window, see [Language](#language).
- **NAME YOUR SERVER**: type a name for the server and press Enter (or
  just Enter to keep *Emergency Meeting*). The name shows up as the region in
  Among Us and on the join page. It can be changed later with
  `/changeservername`, see [Commands](#commands).
- **FIXED HTTPS ADDRESS WITH NGROK**: paste a key from ngrok, see
  [Fixed HTTPS address with ngrok](#fixed-https-address-with-ngrok).
- **CONNECT THE SERVER TO PLAYIT.GG**: open a link and approve the server, see
  [Play with friends from home](#play-with-friends-from-home).

After 10–30 seconds the server prints **HTTPS IS READY!** and an address,
for example:

```
https://happy-penguin-1234.ngrok-free.dev
```

With ngrok the address is the same every time. Without ngrok it becomes a
Cloudflare address (`...trycloudflare.com`) that changes every start.

When everything is ready, the box **SERVER IS ONLINE!** appears. Then you can
join.

Stop the server with **Ctrl+C** (or type `/stop`).

### Updating to a new version

Download the code as a ZIP again and move these from the old folder, so
that you don't have to redo the things that are only needed the first time:

- `config.json` (the settings, the server's name and language)
- `playit-key.txt`, `ngrok-key.txt` and `ngrok-address.txt`
- `cloudflared` and the `plugins` folder

> Coming from 0.12.0 or older? Those files had Swedish names then
> (`playit-nyckel.txt`, `ngrok-nyckel.txt`, `ngrok-adress.txt` and the
> `loggar` folder). Just move them over as they are, the server gives them
> their new names by itself.

## Language

Everything in Emergency Meeting is in English: the code, the join page, the
files and the chat messages in the game. Only the server's **Terminal window**
(the one `start.command` opens) can be in Swedish instead.

The language is chosen the first time the server starts. Change it with
`/language English` or `/language Swedish` while the server is running, or
with `"language"` in `config.json`. The change is saved in `config.json`.

The translations are in `server/locales/sv.json`. Run
`python3 tools/check_translations.py` to find text that has no translation
yet. Plugins can bring their own translations, see
[plugins/README.md](plugins/README.md).

## Commands

While the server is running you can type commands in the Terminal window and
press Enter:

| Command | What it does |
|---------|--------------|
| `/help` | Shows all commands |
| `/changeservername <name>` | Changes the server's name, for example `/changeservername Blobi's server` |
| `/games` | Shows the games on the server with game code, number of players and map |
| `/address` | Shows the join page's address and the QR code again |
| `/say <message>` | Sends a chat message to everyone in all games |
| `/language <English\|Swedish>` | Changes the language in the Terminal window |
| `/stop` | Stops the server (the same as Ctrl+C) |

When the server changes its name, the region in `regionInfo.json`, the button
on the join page and the heading change right away. Those who have already
added the server see the old name in Among Us until they add the server
again from the join page. You can play anyway, the address is the same.

### 5. Test without the game (optional)

Leave the server running and double-click **`test.command`**. The test client
pretends to be two Among Us players: one hosts a game, the other joins with
the game code. If everything works it prints `Everything works!`.

## Connecting with Among Us

With playit.gg (see the next part) the player can be anywhere. Without
playit.gg the device must be on the **same wifi** as the Mac.

1. Open the HTTPS address the server printed in a browser on the device
   that will play, or scan the QR code in the Terminal window with the
   phone camera.
2. The page shows the steps for that device (iPhone/iPad, Android, PC or
   Mac). On phones it's enough to tap the button **Add to Among Us**. On a
   PC you download `regionInfo.json`, and the page has a button that copies
   the address of the folder where the file should go.
3. Restart Among Us completely, choose the server **Emergency Meeting** and
   tap **Create Game**, or **Enter Code** and type in a code.

### The join page

The join page has three parts:

- **Add the server**: the steps for the device you use. Wrong device? Switch
  with the tabs at the top.
- **Play**: all games on the server with game code, host, map and number of
  players. The list updates by itself. **Copy code** puts the code on the
  clipboard.
- **Invite friends**: a QR code and a ready-made message. Tap **Invite to this
  game** next to a game, and the code is included in the message. Copy it
  or tap **Share** (on the phone) and send it in a chat.

If you open `http://localhost:22023` on the Mac, it shows the address the
friends should use, with a big QR code, the games and the message.

With ngrok you only have to do steps 1–2 once. With a Cloudflare address
the address changes every restart, and then you have to redo steps 1–2.

## Fixed HTTPS address with ngrok

**ngrok** (free) gives the server an HTTPS address that is the same every
time, for example `https://happy-penguin-1234.ngrok-free.dev`. Then friends
only have to add the server to Among Us once.

### The first time (only the host)

1. Start the server. It shows the box **FIXED HTTPS ADDRESS WITH NGROK**.
2. Create a free account at <https://dashboard.ngrok.com/signup> (or log
   in).
3. Open <https://dashboard.ngrok.com/get-started/your-authtoken> and copy
   your **Authtoken**.
4. Click in the Terminal window, paste the key (Cmd+V) and press **Enter**.
   The key doesn't show when you paste it, because it's secret. It doesn't
   matter if other lines show up in the window meanwhile.
5. The server downloads the program ngrok by itself and then prints
   **HTTPS IS READY!** with the new address.

The key is saved in `ngrok-key.txt` and the address in `ngrok-address.txt`.
Don't share the key with anyone (the file is already excluded in
`.gitignore`).

Until the key is pasted, Cloudflare is used, so the server works anyway.
Just press Enter if you want to skip ngrok that time.

### Good to know

- The first time you open the address in a browser, ngrok shows a warning
  page. Tap **Visit Site**. The game itself gets no warning page.
- If ngrok doesn't get going within 40 seconds, the server uses Cloudflare
  instead. The box **HTTPS IS READY!** says which address to use.
- The free account is plenty: ngrok allows 20,000 requests a month, and a
  player who joins only makes a few.
- If someone else has seen the key, for example in a screenshot or a copied
  log: create a new one at
  <https://dashboard.ngrok.com/get-started/your-authtoken> (**Reset
  Authtoken**). The next time the server starts it says that the key doesn't
  work and asks for the new one.
- If you only want to use Cloudflare: set `"ngrok": false` in `config.json`.

## Play with friends from home

The server uses **playit.gg** (free) so that friends can play with you from
their own homes, on wifi or mobile data. Nothing needs to be changed in the
router. The game gets a fixed address at playit.gg that is the same every
time.

### The first time (only the host)

1. Start the server. It shows the box **CONNECT THE SERVER TO PLAYIT.GG** with
   a link, for example `https://playit.gg/claim/3fa91c0d2e`.
2. Open the link in a browser. Log in, or create a free account, and
   approve the server.
3. The server then creates a tunnel at playit.gg by itself. If that doesn't
   work, it shows the box **CREATE A TUNNEL ON PLAYIT.GG** with what to click
   on playit.gg. The server notices by itself when the tunnel is ready.
4. When the box **PLAYIT IS READY!** shows up, everything is ready.

The server saves a secret key in `playit-key.txt`. After that everything
happens by itself every time the server starts. Don't share the file with
anyone, and don't put it on GitHub (it's already excluded in `.gitignore`).

### How friends join

Just like on wifi: they open the HTTPS address the server printed, tap
**Add to Among Us**, restart the game, choose **Emergency Meeting** and type
in the game code. Send them the address in a chat.

With ngrok they only do that once. The next time they just choose
**Emergency Meeting** in the game and type in the game code.

Phones no longer need the "Local Network" permission, because the game goes
through the internet instead of directly to the Mac.

### If something goes wrong

- **PLAYIT.GG DOESN'T RECOGNIZE THE SERVER**: the key doesn't work anymore
  (for example if the server was removed on playit.gg). Delete
  `playit-key.txt` and restart the server, and a new link comes up.
- **"playit.gg isn't here"** in the log: the file `playit/playitd-macos` is
  missing. Download the code as a ZIP again, or double-click
  `build-playit.command` (see [playit/README.md](playit/README.md)).
- If you only want to play on your wifi: set `"playit": false` in `config.json`.

## What the log shows

The server prints what happens, for example:

```
15:01:12  game    Blobi created the game NUORZH (The Skeld, Normal, max 10 players, 1 impostor)
15:01:12  game    Blobi joined NUORZH as host (1/10 players)
15:02:40  game    NUORZH: Blobi has the color Lime
15:03:05  game    NUORZH: Blobi changed Kill Cooldown: 30 s -> 25 s
15:03:30  game    Kalle joined NUORZH as player (2/10 players)
15:03:41  game    NUORZH chat  Kalle: hi!
15:05:02  game    NUORZH: the game is starting! (4 players, The Skeld)
15:05:31  bot     Bot_1 did a task (Fix Wiring) (1/4)
15:06:10  game    NUORZH: Bot_2 has been killed! (1 dead)
15:06:30  game    NUORZH: MEETING! Blobi found Bot_2
15:07:05  game    NUORZH: Bot_1 was voted out
15:07:20  game    NUORZH: THE ROUND IS OVER. The crew won by voting out the impostors
15:07:20  game    NUORZH:   Impostors: Bot_1
15:07:20  game    NUORZH:   Bot_2 was killed by Bot_1
```

During the round the log doesn't say who killed someone or who the impostors
are, so that whoever watches the server window doesn't find out. That only
comes in the summary when the round is over.

The log has colors: the boxes' titles are red and every kind of line has its
own color (the server and the games orange, playit.gg yellow, ngrok blue,
HTTP green, bots turquoise and plugins purple). Warnings are yellow and
errors red. The colors follow whether the Mac is in dark or light mode. If
you want other colors or none, there are `color_theme` and `colors` in
`config.json`.

## Killing

In Among Us it's the server, not the host, that decides if an impostor may
kill. The game asks the server ("CheckMurder"), the server checks that the
killer is a living impostor, that the victim is alive and isn't an impostor
and that no meeting is going on, and then sends "MurderPlayer" to everyone.
If a Guardian Angel has protected the victim, the kill fails. The server
also handles the Phantom's "vanish" and "appear" the same way.

## Bots that walk

Bots (from the bot plugin) walk around in the lobby and on the map. During a
round they walk to their tasks, stand at the console for a while and do the
task. When everything is done they wander between the rooms. In meetings
they stand at the table and vote skip when the discussion time is over.

The maps are in `server/mapdata/`: the walls, where the tasks are done and
where the players start. The server splits the map into small cells and finds
a path around the walls (see `server/navigation.py`). The Skeld, MIRA HQ,
Polus, dlekS ehT and The Airship have real walls. On The Fungle only some of
the walls are included, so there a bot can sometimes walk through a tree or a
rock. On The Airship bots can't climb ladders or ride the platform, so they do
the tasks they can walk to.

The settings have the same names as in the game's menu. If the game gets a
new setting that the server doesn't know about, it says "Other settings".

## Plugins

The `plugins/` folder is for plugins that the server loads when it starts.
A plugin is a Python file that can react to things that happen (someone
joins, writes in the chat, changes settings...) and send chat messages or
add bots itself.

Ready-made plugins are in
[Common Emergency Meeting Plugins (CEMP)](https://github.com/xxMrMag1cxx/Common-Emergency-Meeting-Plugins).
Download that repo as a ZIP, unpack it and put the whole folder in
`plugins/`. Then restart the server.

How to write your own plugins is in [plugins/README.md](plugins/README.md).

## The server's settings

The server's own settings are in `config.json`. The file is created the first
time the server starts. Change it with TextEdit when the server is off.

| Setting            | What it does |
|--------------------|--------------|
| `server_name`      | The server's name (asked the first time, change it with `/changeservername`) |
| `language`         | The language in the Terminal window: `English` or `Swedish` (asked the first time, change it with `/language`) |
| `listen_ip`        | `0.0.0.0` = listen on all networks. Rarely needs to be changed |
| `port`             | Port for both HTTP and the game. Among Us uses `22023` |
| `public_ip`        | `auto` = the Mac's address on the home network. Can be set to your own address |
| `https_tunnel`     | `true` = start an HTTPS tunnel (ngrok, otherwise cloudflared) |
| `ngrok`            | `true` = use ngrok, so that the HTTPS address is the same every time |
| `ngrok_path`       | `auto` = look for ngrok by itself (the `ngrok/` folder first) and download it if it's missing |
| `cloudflared_path` | `auto` = look for cloudflared by itself (the project folder first) |
| `playit`           | `true` = make the game reachable from home with playit.gg |
| `playit_path`      | `auto` = look for playitd by itself (the `playit/` folder first) |
| `plugins`          | `true` = load plugins from the `plugins/` folder |
| `page_shows_games` | `true` = show the games and their codes on the join page |
| `terminal_qr`      | `true` = show the HTTPS address as a QR code in the Terminal window |
| `colors`           | `true` = colors in the Terminal window |
| `color_theme`      | `auto` = follow the Mac's dark/light mode, `dark` = for a black background, `light` = for a white background |
| `debug`            | `true` = show every packet in the log, good for troubleshooting |

## How the code is organized

```
server/
  __main__.py    starts everything
  config.py      reads and saves config.json
  terminal.py    colors, boxes, the language menu, the server name and the commands (/help)
  i18n.py        translations for the Terminal window
  locales/       the translations (sv.json = Swedish)
  matchmaker.py  the HTTP part: the game asks where the server is
  ngrok.py       starts ngrok: an HTTPS address that is the same every time
  tunnel.py      starts cloudflared (backup): an HTTPS address that changes every time
  playit.py      starts playitd and keeps an eye on the playit.gg tunnel
  webpage.py     the join page: adding the server, game codes, invitation
  qrcode.py      QR codes (for the terminal and the join page)
  region.py      builds regionInfo.json and the amongus:// link
  hazel.py       the network layer: acks, pings and resending packets
  handshake.py   reads the game's first packet (name, version, platform)
  game.py        the game logic: hosting, joining, passing on game data
  lobby.py       a lobby: game code, players, host and player info
  options.py     reads the game settings and shows what changed
  plugins.py     loads plugins and calls them when something happens
  bots.py        bots: pretend players that the server controls
  navigation.py  finds paths around the walls for bots
  mapdata/       the maps: walls, tasks, rooms and start places
  blackbox.py    "black box": saves what happened if someone is disconnected
  gamecode.py    game codes ("ABCDEF") and the numbers the game sends
  messages.py    reading and writing bytes
  protocol.py    all numbers and names Among Us uses
plugins/         plugins that the server loads (see plugins/README.md)
playit/          playitd, playit.gg's tunnel program (see playit/README.md)
tools/
  testclient.py         two pretend Among Us games that test the server (host,
                        join, change color, change settings, chat, leave)
  check_translations.py finds text in the Terminal window that has no translation
start.command               starts the server
test.command                runs the test client
get-cloudflared.command     downloads cloudflared
build-playit.command        builds playitd on the Mac (rarely needed)
.github/workflows/          GitHub builds playitd for Mac
```

This is how a connection works:

```
Among Us --HTTPS--> ngrok -------tunnel--> ngrok -------HTTP---> the server (TCP 22023)
Among Us --UDP----> playit.gg ---tunnel--> playitd -----UDP----> the server (UDP 22023)
```

If ngrok doesn't work, HTTPS goes through Cloudflare instead (the program
cloudflared). Without playit.gg (or if the game asks the server directly,
without HTTPS) UDP goes directly from the game to the Mac on your wifi.

1. The game asks the server over **HTTPS**: "Can I have a token?" and "Where
   should I host the game?". The server answers with the playit.gg address
   (or the Mac's address on the home network if playit.gg isn't used).
2. The game sends a **Hello** packet directly to the Mac over **UDP** with its
   name and version.
3. The game sends **HostGame** with the settings. The server creates a lobby
   and answers with the game code.
4. The game sends **JoinGame** with the code. The server answers
   **JoinedGame**, and the first one to join becomes the host.
5. The game loads the lobby. The server creates a **player info** object for
   the player (where the game saves name, color and hat).
6. After that the host sends **GameData** all the time (movements, color
   changes, chat...). The server passes it all on to the others in the lobby.

So most of the game logic runs at the host. The server is mostly a mail
carrier that keeps track of who is in which game.

## Troubleshooting

- **Black screen and nothing happens in the server window**: the game doesn't
  reach the server. Check that you use the HTTPS address from the *latest*
  start of the server. With ngrok the address is the same every time, but if
  the box **HTTPS IS READY!** shows a `trycloudflare.com` address, the server
  has used Cloudflare instead.
- **NGROK DOESN'T RECOGNIZE THE KEY**: paste a new key from
  <https://dashboard.ngrok.com/get-started/your-authtoken> in the Terminal window.
- **NGROK IS ALREADY IN USE**: the ngrok account is used by another computer
  or program. Close it and restart the server.
- **"tried to connect with HTTPS directly to port 22023"** in the log: the game
  is set to the Mac's IP address instead of the HTTPS address. Add the server
  again through the HTTPS address.
- **"reached the server over HTTPS but never connected to the game over UDP"**
  in the log: the device reaches the server over the internet but not the game
  itself. Check that the box **PLAYIT IS READY!** has been shown. Without
  playit.gg the device must be on the same wifi, and on an iPhone: Settings →
  Privacy & Security → Local Network → turn on Among Us.
- **A token is fetched but nothing more happens**: the game reaches the HTTPS
  part but not UDP. Check that the device is on the same wifi and that the
  firewall allows Python (System Preferences → Security & Privacy → Firewall).
- **The game gets stuck after Create Game** or the lobby looks strange: set
  `"debug": true` in `config.json`, try again and save the log. It shows
  exactly what the game and the server send to each other.
- **"Address already in use"**: the server is already running in another
  window. Close it.
- **The game says wrong version**: write down which version the game has
  (it's at the top left in the main menu) and what the log shows.
- **Someone is disconnected unexpectedly**: every time a player in a game is
  disconnected, a report is saved in the `logs/` folder with the latest
  messages between the game and the server. Send that file, and it's
  possible to see what happened just before.
- Set `"debug": true` in `config.json` to see everything that is sent.

## Thanks

The protocol was mapped with the help of the open project
[Impostor](https://github.com/Impostor/Impostor), which we use as a
reference. No code is copied from there.

The map data in `server/mapdata/` comes from other open projects, see
[server/mapdata/README.md](server/mapdata/README.md). Those projects have
the GPL-3.0 license, and the map data has the same license.
