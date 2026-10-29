"""
Help for adding the server to Among Us.

The game can find out about a custom server in two ways:

  - PC: a file called regionInfo.json is put in the game's folder
  - Phone/tablet (and PC): a link that starts with amongus://
    that opens the game and adds the server automatically

Both point to the server's HTTP address, for example
    https://kingston-inside-best-graphic.trycloudflare.com  (port 443)
"""

from __future__ import annotations

import json
from urllib.parse import quote, urlencode


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
        },
        quote_via=quote,  # spaces become %20, not + (otherwise the server is called "Emergency+Meeting")
    )
    return f"amongus://init?{params}"
