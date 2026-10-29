"""
Startpunkten för servern. Kör med:

    python3 -m server
"""

import sys

if sys.version_info < (3, 8):
    print("Emergency Meeting behöver Python 3.8 eller nyare.")
    print("Du har Python %d.%d. Ladda ner en nyare från https://www.python.org/downloads/macos/" % sys.version_info[:2])
    sys.exit(1)

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402
from typing import List, Optional  # noqa: E402

from . import __version__  # noqa: E402
from .config import CONFIG_FILE, PROJECT_DIR, config_exists, load_config, save_config  # noqa: E402
from .game import Game  # noqa: E402
from .hazel import HazelServer  # noqa: E402
from .lobby import LobbyManager  # noqa: E402
from .matchmaker import ServerInfo, start_matchmaker  # noqa: E402
from .ngrok import Ngrok  # noqa: E402
from .playit import Playit, find_playitd  # noqa: E402
from .plugins import PluginManager  # noqa: E402
from .qrkod import QrKod  # noqa: E402
from .region import region_info_json  # noqa: E402
from .terminal import (  # noqa: E402
    ERROR, GREEN, LIGHT_BLUE, PLAYING, PURPLE, Console, ask_server_name, clean_name, paint,
    output_lock, print_banner, print_box, restore_terminal, say, setup_logging, success,
)
from .tunnel import Tunnel, find_cloudflared  # noqa: E402

log = logging.getLogger("server")


class StartupAnnouncer:
    """
    Skriver rutorna LADDAR PLUGINS och SERVER IS ONLINE! en gång, när HTTPS
    och playit.gg är klara (eller väntar på värden), eller efter två minuter.
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
        print_box("LADDAR PLUGINS", self.plugins.summary())
        self.plugins.log_failures()
        print_box("SERVER IS ONLINE!", online_lines(self.info, self.playit))


def online_lines(info: ServerInfo, playit: str) -> List[str]:
    name = paint(info.config.server_name, PURPLE, bold=True)
    lines = [
        f"{name} is up and running. Go ahead and join on your phone,",
        "tablet or computer!",
        "",
    ]
    if info.tunnel_url:
        lines.append(f"Join page: {paint(info.tunnel_url, LIGHT_BLUE)}")
    else:
        lines.append(f"Join page: http://localhost:{info.config.port} (HTTPS isn't ready yet)")
    if playit == "ready":
        lines.append("Friends can join from anywhere, on wifi or mobile data.")
    elif playit == "waiting":
        lines.append("Friends at home can join once playit.gg is set up (see the box above).")
    elif playit == "pending":
        lines.append("playit.gg isn't ready yet, so only devices on your wifi can join for now.")
    else:
        lines.append("Only devices on your wifi can join (playit.gg is off).")
    lines += ["", f"Use {paint('/help', LIGHT_BLUE, bold=True)} to get a list of useful commands."]
    return lines


def write_region_file(info: ServerInfo) -> None:
    """regionInfo.json i projektmappen, för PC (samma som startsidan ger)."""
    if not info.tunnel_url:
        return
    region_file = PROJECT_DIR / "regionInfo.json"
    try:
        region_file.write_text(region_info_json(info.config.server_name, info.tunnel_url, 443), encoding="utf-8")
    except OSError as error:
        log.warning("Kunde inte spara %s: %s", region_file.name, error)


def show_qr(url: str) -> None:
    try:
        qr = QrKod.skapa(url, "M").terminal(kant=3)
    except ValueError:
        return
    with output_lock():
        print("  Skanna med mobilkameran för att öppna sidan:", flush=True)
        print(qr, flush=True)


def announce_tunnel(info: ServerInfo, url: str, fixed: bool, changed: bool = False) -> None:
    """
    Körs när en HTTPS-adress fungerar. fixed = adressen är samma varje gång
    (ngrok), annars byts den vid varje start (Cloudflare).
    """
    if not fixed and info.fixed_url:
        log.info("Cloudflare-adressen %s fungerar också, men använd ngrok-adressen.", url)
        return
    info.tunnel_url = url
    if fixed:
        info.fixed_url = url
    write_region_file(info)

    lines = [
        "Öppna den här adressen på enheten som ska spela:",
        f"    {paint(url, LIGHT_BLUE, bold=True)}",
        "",
        "Där finns allt som behövs: hur man lägger till servern, spelkoderna",
        "och ett färdigt meddelande att skicka till kompisar.",
        f"Eller öppna http://localhost:{info.config.port} här på Macen.",
        "",
    ]
    if not fixed:
        lines.append("Obs: adressen byts varje gång servern startas om.")
    elif changed:
        lines += [
            "OBS: adressen är ny! Alla behöver lägga till servern igen,",
            "sedan är den samma varje gång.",
        ]
    else:
        lines += [
            "Adressen är samma varje gång servern startar, så den som",
            "redan har lagt till servern behöver inte göra det igen.",
            "(ngrok visar en varningssida i webbläsaren: tryck Visit Site.)",
        ]
    with output_lock():
        print_box("HTTPS ÄR KLART!", lines)
        if info.config.terminal_qr:
            show_qr(url)


def add_commands(console: Console, info: ServerInfo, loop: asyncio.AbstractEventLoop) -> None:
    """Kommandona man kan skriva i Terminal-fönstret (se /help)."""
    config = info.config

    def change_name(argument: str) -> None:
        if not argument:
            say(f"Usage: {paint('/changeservername <new name>', LIGHT_BLUE, bold=True)}")
            return
        name, problem = clean_name(argument)
        if problem:
            say(paint(problem, ERROR))
            return
        if name == config.server_name:
            say(f"The server is already called {paint(name, PURPLE, bold=True)}.")
            return
        old = config.server_name
        config.server_name = name
        save_config(config)
        write_region_file(info)
        success("Name updated!")
        say(f"The server is now called {paint(name, PURPLE, bold=True)}.")
        say("Friends who already added the server see the old name until they add it")
        say("again from the join page. Joining still works either way.")
        log.info("Servern heter nu %s (hette %s)", name, old)

    def games(_argument: str) -> None:
        def show() -> None:
            lobbies = [lobby for lobby in info.lobbies.all() if lobby.host is not None]
            if not lobbies:
                print_box("GAMES", ["No games right now. Press Create Game in Among Us to start one."])
                return
            lines = []
            for lobby in lobbies:
                state = paint("playing", PLAYING) if lobby.is_started else paint("in the lobby", GREEN)
                lines.append(
                    f"{paint(lobby.code, LIGHT_BLUE, bold=True)}  {len(lobby.players)}/{lobby.options.max_players} players"
                    f"  {lobby.map_name}  host {lobby.host_name}  ({state})"
                )
            print_box("GAMES", lines)
        loop.call_soon_threadsafe(show)

    def address(_argument: str) -> None:
        lines = []
        if info.tunnel_url:
            lines.append(f"Join page:  {paint(info.tunnel_url, LIGHT_BLUE, bold=True)}")
        else:
            lines.append("Join page:  HTTPS isn't ready yet")
        lines.append(f"On this Mac: http://localhost:{config.port}")
        if info.playit_address:
            lines.append(f"playit.gg:  {info.playit_address}")
        with output_lock():
            print_box("ADDRESSES", lines)
            if info.tunnel_url:
                show_qr(info.tunnel_url)

    def say_to_all(argument: str) -> None:
        if not argument:
            say(f"Usage: {paint('/say <message>', LIGHT_BLUE, bold=True)}")
            return

        def send() -> None:
            sent = sum(1 for lobby in info.lobbies.all() if lobby.send_chat(f"[Server] {argument}"))
            if sent:
                success(f"Sent to {sent} game{'s' if sent != 1 else ''}.")
            else:
                say("There are no games to send to right now.")
        loop.call_soon_threadsafe(send)

    def stop(_argument: str) -> None:
        say("Stopping the server...")
        os.kill(os.getpid(), signal.SIGINT)

    console.add("changeservername", "/changeservername <name>", "Give the server a new name", change_name)
    console.add("games", "/games", "List the games on the server and their codes", games)
    console.add("address", "/address", "Show the join page address and QR code again", address)
    console.add("say", "/say <message>", "Send a chat message to everyone in every game", say_to_all)
    console.add("stop", "/stop", "Stop the server (same as Ctrl+C)", stop)


async def run() -> None:
    first_start = not config_exists()
    config = load_config()
    setup_logging(config.debug, config.colors, config.color_theme)
    interactive = sys.stdin is not None and sys.stdin.isatty()

    if first_start:
        # Första gången: fråga efter ett namn och skapa config.json
        if interactive:
            config.server_name = ask_server_name(config.server_name)
        save_config(config)

    lobbies = LobbyManager()
    info = ServerInfo(config, config.resolved_public_ip(), lobbies)

    try:
        httpd = start_matchmaker(info)
    except OSError as error:
        log.error("Kunde inte starta HTTP-servern på port %s: %s", config.port, error)
        log.error("Kör servern redan i ett annat fönster? Stäng det först.")
        return

    # Plugins laddas direkt, men vad som laddades visas först när allt är klart.
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
        log.error("Kunde inte starta UDP-servern på port %s: %s", config.port, error)
        httpd.shutdown()
        return

    print_banner(config.server_name, __version__, [
        f"Servern körs på port {config.port} (TCP + UDP)",
        f"Macens adress i nätverket: {info.public_ip}",
        f"Inställningar: {CONFIG_FILE.name}",
        "Stäng av servern med Ctrl+C",
    ])

    announcer = StartupAnnouncer(info, plugins, config.https_tunnel, config.playit)

    console: Optional[Console] = None
    if interactive:
        console = Console()
        add_commands(console, info, loop)
        console.start()

    # HTTPS: ngrok (samma adress varje gång) om det går, annars Cloudflare.
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
                log.warning("cloudflared saknas, så det blir ingen HTTPS-adress från Cloudflare.")
                log.warning("Fixa det: dubbelklicka på hamta-cloudflared.command och starta om servern.")
                announcer.https_ready()
                return

            def tunnel_ready(url: str) -> None:
                announce_tunnel(info, url, fixed=False)
                announcer.https_ready()

            new_tunnel = Tunnel(binary, config.port, tunnel_ready)
            try:
                new_tunnel.start()
            except OSError as error:
                log.error("Kunde inte starta cloudflared: %s", error)
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
                start_cloudflare()  # första gången: Cloudflare fungerar medan värden fixar ngrok
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
            log.info("playit.gg finns inte här, så spelet nås bara från ert wifi.")
            log.info("Se \"Spela med kompisar hemifrån\" i README.md för hur man fixar det.")
            announcer.playit_off()

    announcer._check()  # om varken HTTPS eller playit är påslaget
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
    raise KeyboardInterrupt  # stäng av snyggt, så att playitd, ngrok och cloudflared också stängs


def main() -> None:
    for name in ("SIGTERM", "SIGHUP"):  # t.ex. när Terminal-fönstret stängs
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop_on_signal)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        restore_terminal()
        print("\nServern är avstängd. Hej då!")


if __name__ == "__main__":
    main()
