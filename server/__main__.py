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

from . import __version__  # noqa: E402
from .config import CONFIG_FILE, PROJECT_DIR, load_config  # noqa: E402
from .game import Game  # noqa: E402
from .hazel import HazelServer  # noqa: E402
from .matchmaker import ServerInfo, start_matchmaker  # noqa: E402
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


def announce_tunnel(info: ServerInfo, url: str) -> None:
    """Körs när HTTPS-adressen fungerar."""
    info.tunnel_url = url
    region_file = PROJECT_DIR / "regionInfo.json"
    region_file.write_text(region_info_json(info.config.server_name, url, 443), encoding="utf-8")

    print(LINE, flush=True)
    print("  HTTPS ÄR KLART!")
    print()
    print("  Öppna den här adressen på enheten som ska spela:")
    print(f"      {url}")
    print()
    print("  Där finns en knapp som lägger till servern i Among Us.")
    print(f"  (En färdig {region_file.name} har också sparats i projektmappen.)")
    print()
    print("  Obs: adressen byts varje gång servern startas om.")
    print(LINE, flush=True)


async def run() -> None:
    config = load_config()
    setup_logging(config.debug)
    info = ServerInfo(config, config.resolved_public_ip())

    try:
        httpd = start_matchmaker(info)
    except OSError as error:
        log.error("Kunde inte starta HTTP-servern på port %s: %s", config.port, error)
        log.error("Kör servern redan i ett annat fönster? Stäng det först.")
        return

    game = Game(config)
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

    tunnel = None
    if config.https_tunnel:
        binary = find_cloudflared(config.cloudflared_path)
        if binary:
            tunnel = Tunnel(binary, config.port, lambda url: announce_tunnel(info, url))
            try:
                tunnel.start()
            except OSError as error:
                log.error("Kunde inte starta cloudflared: %s", error)
                tunnel = None
        else:
            log.warning("cloudflared saknas, så det blir ingen HTTPS-adress.")
            log.warning("Among Us på andra enheter kan inte ansluta utan HTTPS.")
            log.warning("Fixa det: dubbelklicka på hamta-cloudflared.command och starta om servern.")

    try:
        await hazel.maintenance_loop()
    finally:
        if tunnel:
            tunnel.stop()
        transport.close()
        httpd.shutdown()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nServern är avstängd. Hej då!")


if __name__ == "__main__":
    main()
