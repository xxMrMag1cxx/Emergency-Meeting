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
import signal  # noqa: E402
import threading  # noqa: E402
from typing import Optional  # noqa: E402

from . import __version__  # noqa: E402
from .config import CONFIG_FILE, PROJECT_DIR, load_config  # noqa: E402
from .game import Game  # noqa: E402
from .hazel import HazelServer  # noqa: E402
from .lobby import LobbyManager  # noqa: E402
from .matchmaker import ServerInfo, start_matchmaker  # noqa: E402
from .ngrok import Ngrok  # noqa: E402
from .playit import Playit, find_playitd  # noqa: E402
from .plugins import PluginManager  # noqa: E402
from .region import region_info_json  # noqa: E402
from .tunnel import Tunnel, find_cloudflared  # noqa: E402

log = logging.getLogger("server")

LINE = "=" * 64


def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s  %(name)-6s  %(message)s",
        datefmt="%H:%M:%S",
    )


def print_box(title: str, lines) -> None:
    print()
    print(LINE)
    print(f"  {title}")
    print()
    for line in lines:
        print(f"  {line}" if line else "")
    print(LINE, flush=True)


class PluginAnnouncer:
    """
    Skriver rutan LADDAR PLUGINS en gång, när HTTPS-adressen är klar
    (eller direkt om det inte blir någon tunnel).
    """

    # Om tunneln aldrig blir klar visas rutan ändå efter så här många sekunder.
    FALLBACK_SECONDS = 120

    def __init__(self, plugins: PluginManager):
        self.plugins = plugins
        self._done = False
        self._lock = threading.Lock()

    def announce(self) -> None:
        with self._lock:
            if self._done:
                return
            self._done = True
        print_box("LADDAR PLUGINS", self.plugins.summary())
        self.plugins.log_failures()


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
    region_file = PROJECT_DIR / "regionInfo.json"
    region_file.write_text(region_info_json(info.config.server_name, url, 443), encoding="utf-8")

    lines = [
        "Öppna den här adressen på enheten som ska spela:",
        f"    {url}",
        "",
        "Där finns en knapp som lägger till servern i Among Us.",
        f"(En färdig {region_file.name} har också sparats i projektmappen.)",
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
    print_box("HTTPS ÄR KLART!", lines)


async def run() -> None:
    config = load_config()
    setup_logging(config.debug)
    lobbies = LobbyManager()
    info = ServerInfo(config, config.resolved_public_ip(), lobbies)

    try:
        httpd = start_matchmaker(info)
    except OSError as error:
        log.error("Kunde inte starta HTTP-servern på port %s: %s", config.port, error)
        log.error("Kör servern redan i ett annat fönster? Stäng det först.")
        return

    # Plugins laddas direkt, men vad som laddades visas först efter HTTPS-rutan.
    plugins = PluginManager()
    plugins.enabled = config.plugins
    if config.plugins:
        plugins.load_all()
    announcer = PluginAnnouncer(plugins)

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

    print(LINE)
    print(f"  {config.server_name}  (version {__version__})")
    print(LINE)
    print(f"  Servern körs på port {config.port} (TCP + UDP)")
    print(f"  Macens adress i nätverket: {info.public_ip}")
    print(f"  Inställningar: {CONFIG_FILE.name}")
    print("  Stäng av servern med Ctrl+C")
    print(LINE, flush=True)

    # HTTPS: ngrok (samma adress varje gång) om det går, annars Cloudflare.
    tunnel: Optional[Tunnel] = None
    tunnel_lock = threading.Lock()

    def start_cloudflare() -> None:
        nonlocal tunnel
        with tunnel_lock:
            if tunnel is not None:
                return
            binary = find_cloudflared(config.cloudflared_path)
            if not binary:
                log.warning("cloudflared saknas, så det blir ingen HTTPS-adress från Cloudflare.")
                log.warning("Fixa det: dubbelklicka på hamta-cloudflared.command och starta om servern.")
                announcer.announce()
                return

            def tunnel_ready(url: str) -> None:
                announce_tunnel(info, url, fixed=False)
                announcer.announce()

            new_tunnel = Tunnel(binary, config.port, tunnel_ready)
            try:
                new_tunnel.start()
            except OSError as error:
                log.error("Kunde inte starta cloudflared: %s", error)
                announcer.announce()
                return
            tunnel = new_tunnel

    def ngrok_ready(url: str, changed: bool) -> None:
        announce_tunnel(info, url, fixed=True, changed=changed)
        announcer.announce()

    ngrok = None
    if config.https_tunnel:
        if config.ngrok:
            ngrok = Ngrok(config.ngrok_path, config.port, ngrok_ready, start_cloudflare, print_box)
            if not ngrok.has_key():
                start_cloudflare()  # första gången: Cloudflare fungerar medan värden fixar ngrok
            ngrok.start()
        else:
            start_cloudflare()

    playit = None
    if config.playit:
        binary = find_playitd(config.playit_path)
        if binary:
            playit = Playit(binary, config.port, info.set_playit, print_box)
            playit.start()
        else:
            log.info("playit.gg finns inte här, så spelet nås bara från ert wifi.")
            log.info("Se \"Spela med kompisar hemifrån\" i README.md för hur man fixar det.")

    if not config.https_tunnel:
        announcer.announce()
    else:
        loop.call_later(PluginAnnouncer.FALLBACK_SECONDS, announcer.announce)

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


def _stop_on_signal(signum, frame) -> None:
    raise KeyboardInterrupt  # stäng av snyggt, så att playitd, ngrok och cloudflared också stängs


def main() -> None:
    for name in ("SIGTERM", "SIGHUP"):  # t.ex. när Terminal-fönstret stängs
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop_on_signal)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nServern är avstängd. Hej då!")


if __name__ == "__main__":
    main()
