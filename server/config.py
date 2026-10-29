"""
Inställningar för servern.

Inställningarna läses från filen config.json i projektmappen. Filen skapas
första gången servern startar (då frågar servern också efter ett namn),
med standardvärdena nedan. Ändra i den med en texteditor.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

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

    # Starta en HTTPS-tunnel (krävs för att Among Us ska kunna ansluta
    # från en annan enhet än Macen). Med ngrok om det går, annars cloudflared.
    https_tunnel: bool = True

    # Använd ngrok för HTTPS, så att adressen är samma varje gång.
    # false = använd bara Cloudflare (adressen byts vid varje start).
    ngrok: bool = True

    # Var ngrok finns. "auto" = leta själv (mappen ngrok/ först) och hämta
    # programmet om det saknas.
    ngrok_path: str = "auto"

    # Var cloudflared finns. "auto" = leta själv (projektmappen först).
    cloudflared_path: str = "auto"

    # Gör spelet nåbart från internet med playit.gg, så att kompisar kan
    # spela från sina egna hem utan att något ändras i routern.
    playit: bool = True

    # Var programmet playitd finns. "auto" = leta själv (mappen playit/ först).
    playit_path: str = "auto"

    # Ladda plugins från mappen plugins/.
    plugins: bool = True

    # Visa spelen på servern och deras koder på startsidan.
    page_shows_games: bool = True

    # Visa HTTPS-adressen som QR-kod i Terminal-fönstret.
    terminal_qr: bool = True

    # Färger i Terminal-fönstret.
    colors: bool = True

    # Vilka färger: "auto" (följer Macens mörka/ljusa läge), "dark" (för svart
    # bakgrund) eller "light" (för vit bakgrund).
    color_theme: str = "auto"

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


def config_exists() -> bool:
    return CONFIG_FILE.exists()


# Inställningar i filen som servern inte känner till (sparas tillbaka orörda).
_unknown: Dict[str, object] = {}


def load_config() -> Config:
    config = Config()
    _unknown.clear()

    if not CONFIG_FILE.exists():
        return config

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        log.error("config.json går inte att läsa: %s", error)
        log.error("Kolla att alla citattecken och komman stämmer. Använder standardvärden.")
        config._broken = True  # type: ignore[attr-defined]  # skriv inte över filen
        return config

    for key, value in data.items():
        if hasattr(config, key) and not key.startswith("_"):
            setattr(config, key, value)
        else:
            _unknown[key] = value
            log.warning("Okänd inställning i config.json: %s (ignoreras)", key)

    # Nya inställningar från en nyare version läggs till i filen, så att de syns där.
    known = {f.name for f in dataclasses.fields(Config)}
    if not known.issubset(data):
        save_config(config)
    return config


def save_config(config: Config) -> bool:
    """Sparar inställningarna i config.json. Returnerar False om det inte gick."""
    if getattr(config, "_broken", False):
        log.warning("config.json har ett fel, så ändringen sparades inte i filen.")
        return False
    data = dataclasses.asdict(config)
    data.update(_unknown)
    try:
        CONFIG_FILE.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as error:
        log.error("Kunde inte spara config.json: %s", error)
        return False
    return True
