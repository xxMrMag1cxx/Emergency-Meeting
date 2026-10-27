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
from .config import CONFIG_FILE, load_config  # noqa: E402
from .game import Game  # noqa: E402
from .hazel import HazelServer  # noqa: E402
from .matchmaker import start_matchmaker  # noqa: E402

log = logging.getLogger("server")


def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s  %(name)-6s  %(message)s",
        datefmt="%H:%M:%S",
    )


async def run() -> None:
    config = load_config()
    setup_logging(config.debug)
    public_ip = config.resolved_public_ip()

    try:
        httpd = start_matchmaker(config, public_ip)
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

    line = "=" * 60
    print(line)
    print(f"  {config.server_name}  (version {__version__})")
    print(line)
    print(f"  Servern körs på port {config.port} (TCP + UDP)")
    print(f"  Macens adress i nätverket: {public_ip}")
    print()
    print("  Testa i webbläsaren:")
    print(f"      http://{public_ip}:{config.port}")
    print()
    print("  Lägg till servern i Among Us (PC):")
    print(f"      Adress: http://{public_ip}   Port: {config.port}")
    print()
    print(f"  Inställningar: {CONFIG_FILE.name}")
    print("  Stäng av servern med Ctrl+C")
    print(line)

    try:
        await hazel.maintenance_loop()
    finally:
        transport.close()
        httpd.shutdown()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nServern är avstängd. Hej då!")


if __name__ == "__main__":
    main()
