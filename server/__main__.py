"""
The starting point of the server. Run it with:

    python3 -m server
"""

import sys

if sys.version_info < (3, 8):
    print("Emergency Meeting needs Python 3.8 or newer.")
    print("You have Python %d.%d. Download a newer one from https://www.python.org/downloads/macos/" % sys.version_info[:2])
    sys.exit(1)

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402
from typing import List, Optional  # noqa: E402

from . import __version__, i18n  # noqa: E402
from .config import CONFIG_FILE, PROJECT_DIR, config_exists, load_config, rename_old_files, save_config  # noqa: E402
from .game import Game  # noqa: E402
from .hazel import HazelServer  # noqa: E402
from .i18n import tr  # noqa: E402
from .lobby import LobbyManager  # noqa: E402
from .matchmaker import ServerInfo, start_matchmaker  # noqa: E402
from .ngrok import Ngrok  # noqa: E402
from .playit import Playit, find_playitd  # noqa: E402
from .plugins import PluginManager  # noqa: E402
from .qrcode import QrCode  # noqa: E402
from .region import region_info_json  # noqa: E402
from .terminal import (  # noqa: E402
    ERROR, GREEN, LIGHT_BLUE, PLAYING, PURPLE, Console, ask_server_name, choose_language, clean_name,
    output_lock, paint, print_banner, print_box, restore_terminal, say, setup_logging, success,
)
from .tunnel import Tunnel, find_cloudflared  # noqa: E402

log = logging.getLogger("server")


class StartupAnnouncer:
    """
    Writes the boxes LOADING PLUGINS and SERVER IS ONLINE! once, when HTTPS
    and playit.gg are ready (or waiting for the host), or after two minutes.
    """

    TIMEOUT_SECONDS = 120

    def __init__(self, info: ServerInfo, plugins: PluginManager, want_https: bool, want_playit: bool):
        self.info = info
        self.plugins = plugins
        self.https_done = not want_https
        self.playit = "pending" if want_playit else "off"  # pending, waiting, ready, off
        self._done = False
        self._lock = threading.Lock()

    def https_ready(self) -> None:
        self.https_done = True
        self._check()

    def playit_ready(self) -> None:
        self.playit = "ready"
        self._check()

    def playit_waiting(self) -> None:
        if self.playit == "pending":
            self.playit = "waiting"
        self._check()

    def playit_off(self) -> None:
        self.playit = "off"
        self._check()

    def timeout(self) -> None:
        self._announce()

    def _check(self) -> None:
        if self.https_done and self.playit != "pending":
            self._announce()

    def _announce(self) -> None:
        with self._lock:
            if self._done:
                return
            self._done = True
        print_box(tr("LOADING PLUGINS"), self.plugins.summary())
        self.plugins.log_failures()
        print_box(tr("SERVER IS ONLINE!"), online_lines(self.info, self.playit))


def online_lines(info: ServerInfo, playit: str) -> List[str]:
    name = paint(info.config.server_name, PURPLE, bold=True)
    lines = [
        tr("{name} is up and running. Go ahead and join on your phone,", name=name),
        tr("tablet or computer!"),
        "",
    ]
    if info.tunnel_url:
        lines.append(tr("Join page: {url}", url=paint(info.tunnel_url, LIGHT_BLUE)))
    else:
        lines.append(tr("Join page: {url} (HTTPS isn't ready yet)", url=f"http://localhost:{info.config.port}"))
    if playit == "ready":
        lines.append(tr("Friends can join from anywhere, on wifi or mobile data."))
    elif playit == "waiting":
        lines.append(tr("Friends at home can join once playit.gg is set up (see the box above)."))
    elif playit == "pending":
        lines.append(tr("playit.gg isn't ready yet, so only devices on your wifi can join for now."))
    else:
        lines.append(tr("Only devices on your wifi can join (playit.gg is off)."))
    lines += ["", tr("Use {help} to get a list of useful commands.", help=paint("/help", LIGHT_BLUE, bold=True))]
    return lines


def write_region_file(info: ServerInfo) -> None:
    """regionInfo.json in the project folder, for PC (the same file the join page gives)."""
    if not info.tunnel_url:
        return
    region_file = PROJECT_DIR / "regionInfo.json"
    try:
        region_file.write_text(region_info_json(info.config.server_name, info.tunnel_url, 443), encoding="utf-8")
    except OSError as error:
        log.warning("Could not save %s: %s", region_file.name, error)


def show_qr(url: str) -> None:
    try:
        qr = QrCode.create(url, "M").terminal(border=3)
    except ValueError:
        return
    with output_lock():
        print(f"  {tr('Scan with your phone camera to open the page:')}", flush=True)
        print(qr, flush=True)


def announce_tunnel(info: ServerInfo, url: str, fixed: bool, changed: bool = False) -> None:
    """
    Runs when an HTTPS address works. fixed = the address is the same every
    time (ngrok), otherwise it changes every start (Cloudflare).
    """
    if not fixed and info.fixed_url:
        log.info("The Cloudflare address %s works too, but use the ngrok address.", url)
        return
    info.tunnel_url = url
    if fixed:
        info.fixed_url = url
    write_region_file(info)

    lines = [
        tr("Open this address on the device that's going to play:"),
        f"    {paint(url, LIGHT_BLUE, bold=True)}",
        "",
        tr("It has everything you need: how to add the server, the game codes"),
        tr("and a ready-made message to send to friends."),
        tr("Or open {url} here on the Mac.", url=f"http://localhost:{info.config.port}"),
        "",
    ]
    if not fixed:
        lines.append(tr("Note: the address changes every time the server restarts."))
    elif changed:
        lines += [
            tr("NOTE: the address is new! Everyone needs to add the server again,"),
            tr("then it stays the same every time."),
        ]
    else:
        lines += [
            tr("The address is the same every time the server starts, so anyone"),
            tr("who already added the server doesn't need to do it again."),
            tr("(ngrok shows a warning page in the browser: press Visit Site.)"),
        ]
    with output_lock():
        print_box(tr("HTTPS IS READY!"), lines)
        if info.config.terminal_qr:
            show_qr(url)


def add_commands(console: Console, info: ServerInfo, loop: asyncio.AbstractEventLoop) -> None:
    """The commands you can type in the Terminal window (see /help)."""
    config = info.config

    def usage(text: str) -> None:
        say(tr("Usage: {command}", command=paint(text, LIGHT_BLUE, bold=True)))

    def change_name(argument: str) -> None:
        if not argument:
            usage(tr("/changeservername <new name>"))
            return
        name, problem = clean_name(argument)
        if problem:
            say(paint(problem, ERROR))
            return
        if name == config.server_name:
            say(tr("The server is already called {name}.", name=paint(name, PURPLE, bold=True)))
            return
        old = config.server_name
        config.server_name = name
        save_config(config)
        write_region_file(info)
        success(tr("Name updated!"))
        say(tr("The server is now called {name}.", name=paint(name, PURPLE, bold=True)))
        say(tr("Friends who already added the server see the old name until they add it"))
        say(tr("again from the join page. Joining still works either way."))
        log.info("The server is now called %s (was %s)", name, old)

    def change_language(argument: str) -> None:
        names = " / ".join(i18n.LANGUAGES)
        if not argument:
            usage(f"/language <{names}>")
            return
        if argument.strip().lower() not in ("en", "sv", "english", "swedish", "engelska", "svenska", "se"):
            say(paint(tr("Unknown language {language}.", language=argument), ERROR) + f" ({names})")
            return
        code = i18n.set_language(argument)
        config.language = i18n.language_name(code)
        save_config(config)
        success(tr("Language updated!"))

    def games(_argument: str) -> None:
        def show() -> None:
            lobbies = [lobby for lobby in info.lobbies.all() if lobby.host is not None]
            if not lobbies:
                print_box(tr("GAMES"), [tr("No games right now. Press Create Game in Among Us to start one.")])
                return
            lines = []
            for lobby in lobbies:
                state = paint(tr("playing"), PLAYING) if lobby.is_started else paint(tr("in the lobby"), GREEN)
                lines.append(tr(
                    "{code}  {players}/{max} players  {map}  host {host}  ({state})",
                    code=paint(lobby.code, LIGHT_BLUE, bold=True), players=len(lobby.players),
                    max=lobby.options.max_players, map=lobby.map_name, host=lobby.host_name, state=state,
                ))
            print_box(tr("GAMES"), lines)
        loop.call_soon_threadsafe(show)

    def address(_argument: str) -> None:
        lines = []
        if info.tunnel_url:
            lines.append(tr("Join page:   {url}", url=paint(info.tunnel_url, LIGHT_BLUE, bold=True)))
        else:
            lines.append(tr("Join page:   HTTPS isn't ready yet"))
        lines.append(tr("On this Mac: {url}", url=f"http://localhost:{config.port}"))
        if info.playit_address:
            lines.append(tr("playit.gg:   {address}", address=info.playit_address))
        with output_lock():
            print_box(tr("ADDRESSES"), lines)
            if info.tunnel_url:
                show_qr(info.tunnel_url)

    def say_to_all(argument: str) -> None:
        if not argument:
            usage(tr("/say <message>"))
            return

        def send() -> None:
            sent = sum(1 for lobby in info.lobbies.all() if lobby.send_chat(f"[Server] {argument}"))
            if sent == 1:
                success(tr("Sent to 1 game."))
            elif sent:
                success(tr("Sent to {count} games.", count=sent))
            else:
                say(tr("There are no games to send to right now."))
        loop.call_soon_threadsafe(send)

    def stop(_argument: str) -> None:
        say(tr("Stopping the server..."))
        os.kill(os.getpid(), signal.SIGINT)

    console.add("changeservername", "/changeservername <name>", "Give the server a new name", change_name)
    console.add("language", "/language <English|Swedish>", "Change the language in this window", change_language)
    console.add("games", "/games", "List the games on the server and their codes", games)
    console.add("address", "/address", "Show the join page address and QR code again", address)
    console.add("say", "/say <message>", "Send a chat message to everyone in every game", say_to_all)
    console.add("stop", "/stop", "Stop the server (same as Ctrl+C)", stop)


async def run() -> None:
    rename_old_files()
    first_start = not config_exists()
    config = load_config()
    i18n.set_language(config.language)
    setup_logging(config.debug, config.colors, config.color_theme)
    interactive = sys.stdin is not None and sys.stdin.isatty()

    if first_start:
        # The first time: ask for the language and a name, and create config.json
        if interactive:
            code = choose_language(i18n.normalize(config.language))
            i18n.set_language(code)
            config.language = i18n.language_name(code)
            config.server_name = ask_server_name(config.server_name)
        save_config(config)

    lobbies = LobbyManager()
    info = ServerInfo(config, config.resolved_public_ip(), lobbies)

    try:
        httpd = start_matchmaker(info)
    except OSError as error:
        log.error("Could not start the HTTP server on port %s: %s", config.port, error)
        log.error("Is the server already running in another window? Close it first.")
        return

    # Plugins are loaded right away, but what was loaded is shown when everything is ready.
    plugins = PluginManager()
    plugins.enabled = config.plugins
    if config.plugins:
        plugins.load_all()

    game = Game(config, lobbies, plugins)
    hazel = HazelServer(game.on_connect, game.on_message, game.on_disconnect, debug=config.debug)

    loop = asyncio.get_running_loop()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: hazel, local_addr=(config.listen_ip, config.port)
        )
    except OSError as error:
        log.error("Could not start the UDP server on port %s: %s", config.port, error)
        httpd.shutdown()
        return

    print_banner(config.server_name, __version__, [
        tr("The server is running on port {port} (TCP + UDP)", port=config.port),
        tr("The Mac's address on the network: {ip}", ip=info.public_ip),
        tr("Settings: {file}", file=CONFIG_FILE.name),
        tr("Stop the server with Ctrl+C"),
    ])

    announcer = StartupAnnouncer(info, plugins, config.https_tunnel, config.playit)

    console: Optional[Console] = None
    if interactive:
        console = Console()
        add_commands(console, info, loop)
        console.start()

    # HTTPS: ngrok (the same address every time) if possible, otherwise Cloudflare.
    tunnel: Optional[Tunnel] = None
    tunnel_lock = threading.Lock()
    cloudflare_tried = False

    def start_cloudflare() -> None:
        nonlocal tunnel, cloudflare_tried
        with tunnel_lock:
            if cloudflare_tried:
                return
            cloudflare_tried = True
            binary = find_cloudflared(config.cloudflared_path)
            if not binary:
                log.warning("cloudflared is missing, so there is no HTTPS address from Cloudflare.")
                log.warning("Fix it: double-click get-cloudflared.command and restart the server.")
                announcer.https_ready()
                return

            def tunnel_ready(url: str) -> None:
                announce_tunnel(info, url, fixed=False)
                announcer.https_ready()

            new_tunnel = Tunnel(binary, config.port, tunnel_ready)
            try:
                new_tunnel.start()
            except OSError as error:
                log.error("Could not start cloudflared: %s", error)
                announcer.https_ready()
                return
            tunnel = new_tunnel

    def ngrok_ready(url: str, changed: bool) -> None:
        announce_tunnel(info, url, fixed=True, changed=changed)
        announcer.https_ready()

    ngrok = None
    if config.https_tunnel:
        if config.ngrok:
            ngrok = Ngrok(
                config.ngrok_path, config.port, ngrok_ready, start_cloudflare, print_box,
                ask=console.ask if console else None,
            )
            if not ngrok.has_key():
                start_cloudflare()  # the first time: Cloudflare works while the host sets up ngrok
            ngrok.start()
        else:
            start_cloudflare()

    playit = None
    if config.playit:
        binary = find_playitd(config.playit_path)
        if binary:
            def playit_ready(address: str, ip: str, port: int) -> None:
                info.set_playit(address, ip, port)
                announcer.playit_ready()

            playit = Playit(binary, config.port, playit_ready, print_box, on_waiting=announcer.playit_waiting)
            playit.start()
        else:
            log.info("playit.gg isn't here, so the game can only be reached from your wifi.")
            log.info("See \"Play with friends from home\" in README.md for how to fix that.")
            announcer.playit_off()

    announcer._check()  # if neither HTTPS nor playit is turned on
    loop.call_later(StartupAnnouncer.TIMEOUT_SECONDS, announcer.timeout)

    plugins.fire("on_server_started")
    cleanup = asyncio.ensure_future(game.cleanup_loop())
    try:
        await hazel.maintenance_loop()
    finally:
        cleanup.cancel()
        if ngrok:
            ngrok.stop()
        if tunnel:
            tunnel.stop()
        if playit:
            playit.stop()
        transport.close()
        httpd.shutdown()
        restore_terminal()


def _stop_on_signal(signum, frame) -> None:
    raise KeyboardInterrupt  # stop nicely, so that playitd, ngrok and cloudflared stop too


def main() -> None:
    for name in ("SIGTERM", "SIGHUP"):  # for example when the Terminal window is closed
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop_on_signal)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        restore_terminal()
        print("\n" + tr("The server is off. Bye!"))


if __name__ == "__main__":
    main()
