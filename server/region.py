"""
Hjälp för att lägga till servern i Among Us.

Spelet kan få veta om en egen server på två sätt:

  - PC: en fil som heter regionInfo.json läggs i spelets mapp
  - Telefon/surfplatta (och PC): en länk som börjar med amongus://
    som öppnar spelet och lägger till servern automatiskt

Båda pekar på serverns HTTP-adress, t.ex.
    https://kingston-inside-best-graphic.trycloudflare.com  (port 443)
"""

from __future__ import annotations

import json
from urllib.parse import urlencode


def region_info_json(server_name: str, url: str, port: int) -> str:
    host = url.split("://", 1)[-1]
    data = {
        "CurrentRegionIdx": 3,
        "Regions": [
            {
                "$type": "StaticHttpRegionInfo, Assembly-CSharp",
                "Name": server_name,
                "PingServer": host,
                "Servers": [
                    {
                        "Name": "http-1",
                        "Ip": url,
                        "Port": port,
                        "UseDtls": False,
                    }
                ],
                "TranslateName": 1003,
            }
        ],
    }
    return json.dumps(data, indent=4, ensure_ascii=False)


def app_link(server_name: str, url: str, port: int) -> str:
    params = urlencode(
        {
            "servername": server_name,
            "serverport": str(port),
            "serverip": url,
            "usedtls": "false",
        }
    )
    return f"amongus://init?{params}"
