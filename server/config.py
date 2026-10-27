"""
Inställningar för servern.

Inställningarna läses från filen config.json i projektmappen.
Om filen saknas används standardvärdena nedan.
"""

from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("config")

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_DIR / "config.json"


@dataclass
class Config:
    # Namnet som visas i loggen och på startsidan.
    server_name: str = "Emergency Meeting"

    # Vilken nätverksadress servern lyssnar på. "0.0.0.0" betyder
    # "alla nätverk på den här datorn" och brukar vara rätt.
    listen_ip: str = "0.0.0.0"

    # Porten som spelet ansluter till. Among Us använder 22023 för
    # både HTTP (TCP) och själva spelet (UDP).
    port: int = 22023

    # Adressen som andra enheter ska använda för att nå servern.
    # "auto" betyder att servern själv tar reda på Macens adress
    # i hemnätverket (t.ex. 192.168.1.23).
    public_ip: str = "auto"

    # Texten som visas i spelet när någon försöker skapa eller gå med
    # i ett spel. {namn} byts ut mot spelarens namn.
    welcome_message: str = (
        "Hej {namn}! Emergency Meeting-servern fungerar. "
        "Att skapa spel kommer i nästa steg."
    )

    # Starta en HTTPS-tunnel med cloudflared (krävs för att Among Us
    # ska kunna ansluta från en annan enhet än Macen).
    https_tunnel: bool = True

    # Var cloudflared finns. "auto" = leta själv (projektmappen först).
    cloudflared_path: str = "auto"

    # Sätt till true för att se varenda paket i loggen (bra för felsökning).
    debug: bool = False

    def resolved_public_ip(self) -> str:
        if self.public_ip and self.public_ip != "auto":
            return self.public_ip
        return detect_local_ip()


def detect_local_ip() -> str:
    """
    Tar reda på datorns adress i hemnätverket.

    Knepet: vi "låtsasansluter" ett UDP-uttag mot en adress på internet.
    Inget skickas, men datorn väljer då vilket nätverkskort den skulle
    ha använt, och vi kan läsa av dess adress.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def load_config() -> Config:
    config = Config()

    if not CONFIG_FILE.exists():
        log.info("Hittade ingen config.json, använder standardinställningar.")
        return config

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        log.error("config.json går inte att läsa: %s", error)
        log.error("Kolla att alla citattecken och komman stämmer. Använder standardvärden.")
        return config

    for key, value in data.items():
        if hasattr(config, key):
            setattr(config, key, value)
        else:
            log.warning("Okänd inställning i config.json: %s (ignoreras)", key)

    return config
