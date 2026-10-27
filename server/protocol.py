"""
Siffror och namn som Among Us använder.

Det här är en "ordbok" så att koden kan skriva t.ex. HOST_GAME
i stället för den svårbegripliga siffran 0.
"""

from __future__ import annotations

# --- Hazel: nätverkslagret under Among Us -------------------------------
# Första byten i varje UDP-paket säger vad det är för sorts paket.

UNRELIABLE = 0x00  # vanlig data, inget kvitto behövs
RELIABLE = 0x01  # viktig data, mottagaren måste svara med ett kvitto (ack)
HELLO = 0x08  # "hej, jag vill ansluta"
DISCONNECT = 0x09  # "hej då"
ACK = 0x0A  # kvitto: "jag har fått paket nummer X"
PING = 0x0C  # "lever du fortfarande?"

PACKET_NAMES = {
    UNRELIABLE: "Unreliable",
    RELIABLE: "Reliable",
    HELLO: "Hello",
    DISCONNECT: "Disconnect",
    ACK: "Ack",
    PING: "Ping",
}

# --- Among Us: meddelanden inne i paketen -------------------------------

HOST_GAME = 0
JOIN_GAME = 1
START_GAME = 2
REMOVE_GAME = 3
REMOVE_PLAYER = 4
GAME_DATA = 5
GAME_DATA_TO = 6
JOINED_GAME = 7
END_GAME = 8
ALTER_GAME = 10
KICK_PLAYER = 11
WAIT_FOR_HOST = 12
REDIRECT = 13
RESELECT_SERVER = 14
GET_GAME_LIST_V2 = 16
REPORT_PLAYER = 17
QUICK_MATCH = 18
QUICK_MATCH_HOST = 19
SET_GAME_SESSION = 20
SET_ACTIVE_POD_TYPE = 21
QUERY_PLATFORM_IDS = 22
QUERY_LOBBY_INFO = 23
END_GAME_HOST_MIGRATION = 24
HOST_MODDED_GAME = 25
PACKED_GAME_DATA_TO = 26

MESSAGE_NAMES = {
    HOST_GAME: "HostGame (skapa spel)",
    JOIN_GAME: "JoinGame (gå med i spel)",
    START_GAME: "StartGame",
    REMOVE_GAME: "RemoveGame",
    REMOVE_PLAYER: "RemovePlayer",
    GAME_DATA: "GameData",
    GAME_DATA_TO: "GameDataTo",
    JOINED_GAME: "JoinedGame",
    END_GAME: "EndGame",
    ALTER_GAME: "AlterGame",
    KICK_PLAYER: "KickPlayer",
    WAIT_FOR_HOST: "WaitForHost",
    REDIRECT: "Redirect",
    RESELECT_SERVER: "ReselectServer",
    GET_GAME_LIST_V2: "GetGameListV2",
    REPORT_PLAYER: "ReportPlayer",
    QUICK_MATCH: "QuickMatch",
    QUICK_MATCH_HOST: "QuickMatchHost",
    SET_GAME_SESSION: "SetGameSession",
    SET_ACTIVE_POD_TYPE: "SetActivePodType",
    QUERY_PLATFORM_IDS: "QueryPlatformIds",
    QUERY_LOBBY_INFO: "QueryLobbyInfo",
    END_GAME_HOST_MIGRATION: "EndGameHostMigration",
    HOST_MODDED_GAME: "HostModdedGame",
    PACKED_GAME_DATA_TO: "PackedGameDataTo",
}


def message_name(tag: int) -> str:
    return MESSAGE_NAMES.get(tag, f"Okänt meddelande {tag}")


# --- Varför någon kopplas bort -----------------------------------------

class DisconnectReason:
    EXIT_GAME = 0
    GAME_FULL = 1
    GAME_STARTED = 2
    GAME_NOT_FOUND = 3
    INCORRECT_VERSION = 5
    BANNED = 6
    KICKED = 7
    CUSTOM = 8  # visar vår egen text i spelet!
    INVALID_NAME = 9
    SERVER_ERROR = 113


# --- Plattformar --------------------------------------------------------

PLATFORMS = {
    0: "Okänd",
    1: "Epic (PC)",
    2: "Steam (PC)",
    3: "Mac",
    4: "Microsoft Store (PC)",
    5: "Itch (PC)",
    6: "iPhone/iPad",
    7: "Android",
    8: "Switch",
    9: "Xbox",
    10: "Playstation",
}

XBOX = 9
PLAYSTATION = 10


# --- Spelversioner ------------------------------------------------------

def decode_game_version(value: int) -> str:
    """
    Among Us gömmer versionen i ett enda tal:
        år * 25000 + månad * 1800 + dag * 50 + revision
    Spelets "17.4" är t.ex. internt 2026.3.18.
    """
    year, rest = divmod(value, 25000)
    month, rest = divmod(rest, 1800)
    day, revision = divmod(rest, 50)
    text = f"{year}.{month}.{day}"
    if revision:
        text += f".{revision}"
    return text


def encode_game_version(year: int, month: int, day: int, revision: int = 0) -> int:
    return year * 25000 + month * 1800 + day * 50 + revision
