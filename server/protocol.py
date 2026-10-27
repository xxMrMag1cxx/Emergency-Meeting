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
    HACKING = 10
    NOT_AUTHORIZED = 11
    ERROR = 17
    CLIENT_TIMEOUT = 215
    SERVER_ERROR = 113


DISCONNECT_REASON_NAMES = {
    0: "lämnade spelet",
    1: "spelet var fullt",
    2: "spelet hade redan startat",
    3: "spelet fanns inte",
    5: "fel spelversion",
    6: "bannad",
    7: "utsparkad",
    8: "eget meddelande",
    9: "ogiltigt namn",
    10: "fusk (hacking)",
    11: "inte behörig",
    12: "för många anslutningar",
    16: "spelet stängdes",
    17: "fel i spelet (Error)",
    18: "fel spel",
    19: "servern bad om det",
    20: "servern full",
    21: "olika spelversioner",
    100: "spelaren saknas",
    101: "nonce-fel",
    102: "anslutningstoken-fel",
    113: "serverfel",
    207: "appen hamnade i bakgrunden",
    208: "lämnade med flit",
    209: "appen tappade fokus",
    210: "ny anslutning",
    214: "servern hittades inte",
    215: "ingen kontakt (timeout)",
    216: "auth-fel",
    255: "okänd anledning",
}


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

STEAM = 2
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


# --- Inne i GameData: själva spelet ------------------------------------
# GameData-meddelanden innehåller i sin tur egna små meddelanden.

class GameDataTag:
    DATA = 1  # nytt tillstånd för ett objekt (t.ex. en spelares färg)
    RPC = 2  # "gör något" (t.ex. döda, rapportera, rösta)
    SPAWN = 4  # skapa ett nytt objekt (t.ex. en spelargubbe)
    DESPAWN = 5  # ta bort ett objekt
    SCENE_CHANGE = 6  # "jag har laddat lobbyn"
    READY = 7
    CHANGE_SETTINGS = 8


# Objekt som servern själv skapar får nummer från 100000 och uppåt, så att
# de inte krockar med värdens objekt.
FIRST_SERVER_NET_ID = 100000

# Ägaren -4 betyder "servern äger det här objektet".
SERVER_OWNED = -4

# Typnummer för objekt som kan skapas (spawnas).
SPAWN_MEETING_HUD = 1  # röstningsskärmen under ett möte
SPAWN_PLAYER_CONTROL = 4  # en spelargubbe
SPAWN_HIDE_AND_SEEK_MANAGER = 9
SPAWN_NORMAL_GAME_MANAGER = 10  # håller bl.a. spelinställningarna
SPAWN_PLAYER_INFO = 11

# Några "gör något"-meddelanden (RPC) som servern tittar på.
RPC_COMPLETE_TASK = 1
RPC_EXILED = 4
RPC_CHECK_NAME = 5
RPC_CHECK_COLOR = 7
RPC_SET_NAME = 6
RPC_SET_COLOR = 8
RPC_MURDER_PLAYER = 12
RPC_SEND_CHAT = 13
RPC_START_MEETING = 14
RPC_VOTING_COMPLETE = 23
RPC_CAST_VOTE = 24
RPC_SET_TASKS = 29
RPC_SET_LEVEL = 38
# Kläder: hatt, dräkt, husdjur, visir, namnskylt
RPC_COSMETICS = {39: "hat", 40: "skin", 41: "pet", 42: "visor", 43: "nameplate"}
COSMETIC_RPCS = {name: call for call, name in RPC_COSMETICS.items()}

# "Inga kläder" i spelet (som en ny spelare utan något valt).
EMPTY_COSMETICS = {
    "hat": "hat_EmptyHat",
    "skin": "skin_EmptySkin",
    "pet": "pet_EmptyPet",
    "visor": "visor_EmptyVisor",
    "nameplate": "nameplate_NoPlate",
}
RPC_SET_ROLE = 44

MURDER_SUCCEEDED = 1

# Specialvärden i röstningen
VOTE_SKIP = 253
NO_PLAYER = 255  # t.ex. "nödknappen" i stället för en död kropp

ROLES = {
    0: "Crewmate", 1: "Impostor", 2: "Scientist", 3: "Engineer",
    4: "Guardian Angel", 5: "Shapeshifter", 6: "Crewmate (spöke)",
    7: "Impostor (spöke)", 8: "Noisemaker", 9: "Phantom", 10: "Tracker",
    12: "Detective", 18: "Viper", 19: "Judge", 21: "Spirit Guide",
}
IMPOSTOR_ROLES = {1, 5, 7, 9, 18}

GAME_OVER_REASONS = {
    0: "Besättningen vann genom att rösta ut impostorerna",
    1: "Besättningen vann genom att göra alla uppdrag",
    2: "Impostorerna vann genom röstning",
    3: "Impostorerna vann genom att döda",
    4: "Impostorerna vann genom sabotage",
    5: "Besättningen vann (en impostor lämnade)",
    6: "Impostorerna vann (en crewmate lämnade)",
    7: "Hide n Seek: besättningen överlevde tiden ut",
    8: "Hide n Seek: impostorn fångade alla",
}

COLORS = {
    0: "Red", 1: "Blue", 2: "Green", 3: "Pink", 4: "Orange", 5: "Yellow",
    6: "Black", 7: "White", 8: "Purple", 9: "Brown", 10: "Cyan", 11: "Lime",
    12: "Maroon", 13: "Rose", 14: "Banana", 15: "Gray", 16: "Tan", 17: "Coral",
}


# --- Kartor och spellägen -----------------------------------------------

MAPS = {
    0: "The Skeld",
    1: "MIRA HQ",
    2: "Polus",
    3: "dlekS ehT",
    4: "The Airship",
    5: "The Fungle",
}

GAME_MODES = {
    1: "Vanligt",
    2: "Hide n Seek",
    3: "Vanligt (aprilskämt)",
    4: "Hide n Seek (aprilskämt)",
}
