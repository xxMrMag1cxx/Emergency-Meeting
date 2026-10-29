"""
Numbers and names that Among Us uses.

This is a "dictionary" so that the code can write for example HOST_GAME
instead of the hard-to-understand number 0.
"""

from __future__ import annotations

# --- Hazel: the network layer under Among Us -----------------------------
# The first byte of every UDP packet says what kind of packet it is.

UNRELIABLE = 0x00  # ordinary data, no receipt needed
RELIABLE = 0x01  # important data, the receiver has to answer with a receipt (ack)
HELLO = 0x08  # "hi, I want to connect"
DISCONNECT = 0x09  # "bye"
ACK = 0x0A  # receipt: "I got packet number X"
PING = 0x0C  # "are you still alive?"

PACKET_NAMES = {
    UNRELIABLE: "Unreliable",
    RELIABLE: "Reliable",
    HELLO: "Hello",
    DISCONNECT: "Disconnect",
    ACK: "Ack",
    PING: "Ping",
}

# --- Among Us: messages inside the packets -------------------------------

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
    HOST_GAME: "HostGame",
    JOIN_GAME: "JoinGame",
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
    return MESSAGE_NAMES.get(tag, f"unknown message {tag}")


# --- Why someone gets disconnected ---------------------------------------

class DisconnectReason:
    EXIT_GAME = 0
    GAME_FULL = 1
    GAME_STARTED = 2
    GAME_NOT_FOUND = 3
    INCORRECT_VERSION = 5
    BANNED = 6
    KICKED = 7
    CUSTOM = 8  # shows our own text in the game!
    INVALID_NAME = 9
    HACKING = 10
    NOT_AUTHORIZED = 11
    ERROR = 17
    CLIENT_TIMEOUT = 215
    SERVER_ERROR = 113


DISCONNECT_REASON_NAMES = {
    0: "left the game",
    1: "the game was full",
    2: "the game had already started",
    3: "the game didn't exist",
    5: "wrong game version",
    6: "banned",
    7: "kicked",
    8: "custom message",
    9: "invalid name",
    10: "cheating (hacking)",
    11: "not authorized",
    12: "too many connections",
    16: "the game was closed",
    17: "error in the game",
    18: "wrong game",
    19: "the server asked for it",
    20: "the server is full",
    21: "different game versions",
    100: "the player is missing",
    101: "nonce error",
    102: "connection token error",
    113: "server error",
    207: "the app went to the background",
    208: "left on purpose",
    209: "the app lost focus",
    210: "new connection",
    214: "the server wasn't found",
    215: "no contact (timeout)",
    216: "auth error",
    255: "unknown reason",
}


# --- Platforms ------------------------------------------------------------

PLATFORMS = {
    0: "Unknown",
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


# --- Game versions ------------------------------------------------------

def decode_game_version(value: int) -> str:
    """
    Among Us hides the version in a single number:
        year * 25000 + month * 1800 + day * 50 + revision
    The game's "17.4" is for example 2026.3.18 inside.
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


# --- Inside GameData: the game itself ------------------------------------
# GameData messages in turn contain their own small messages.

class GameDataTag:
    DATA = 1  # new state for an object (for example a player's color)
    RPC = 2  # "do something" (for example kill, report, vote)
    SPAWN = 4  # create a new object (for example a player character)
    DESPAWN = 5  # remove an object
    SCENE_CHANGE = 6  # "I have loaded the lobby"
    READY = 7
    CHANGE_SETTINGS = 8


# Objects that the server creates itself get numbers from 100000 and up, so
# that they don't collide with the host's objects.
FIRST_SERVER_NET_ID = 100000

# The owner -4 means "the server owns this object".
SERVER_OWNED = -4

# Type numbers for objects that can be created (spawned).
SPAWN_MEETING_HUD = 1  # the voting screen during a meeting
SPAWN_PLAYER_CONTROL = 4  # a player character
SPAWN_HIDE_AND_SEEK_MANAGER = 9
SPAWN_NORMAL_GAME_MANAGER = 10  # holds the game settings, among other things
SPAWN_PLAYER_INFO = 11

# Some "do something" messages (RPC) that the server looks at.
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
# Cosmetics: hat, skin, pet, visor, nameplate
RPC_COSMETICS = {39: "hat", 40: "skin", 41: "pet", 42: "visor", 43: "nameplate"}
COSMETIC_RPCS = {name: call for call, name in RPC_COSMETICS.items()}

# "No cosmetics" in the game (like a new player without anything chosen).
EMPTY_COSMETICS = {
    "hat": "hat_EmptyHat",
    "skin": "skin_EmptySkin",
    "pet": "pet_EmptyPet",
    "visor": "visor_EmptyVisor",
    "nameplate": "nameplate_NoPlate",
}
RPC_SET_ROLE = 44
RPC_SNAP_TO = 21  # move a character straight to a place
RPC_CLOSE_MEETING = 22
RPC_PROTECT_PLAYER = 45  # a Guardian Angel protects someone
RPC_CHECK_MURDER = 47  # "may I kill this one?" (to the server)
RPC_CHECK_VANISH = 62  # a Phantom wants to vanish
RPC_START_VANISH = 63
RPC_CHECK_APPEAR = 64  # a Phantom wants to appear again
RPC_START_APPEAR = 65

MURDER_SUCCEEDED = 1
MURDER_FAILED_PROTECTED = 4  # the victim was protected by a Guardian Angel

# Roles that may kill (not impostor ghosts).
KILLER_ROLES = {1, 5, 9, 18}
PHANTOM = 9

# In the game version, revision 25 or more means that the host has a mod and
# decides about killing by itself ("host authority"). Then we just pass things on.
HOST_AUTHORITY_REVISION = 25

# Special values in the voting
VOTE_SKIP = 253
NO_PLAYER = 255  # for example "the emergency button" instead of a dead body

ROLES = {
    0: "Crewmate", 1: "Impostor", 2: "Scientist", 3: "Engineer",
    4: "Guardian Angel", 5: "Shapeshifter", 6: "Crewmate (ghost)",
    7: "Impostor (ghost)", 8: "Noisemaker", 9: "Phantom", 10: "Tracker",
    12: "Detective", 18: "Viper", 19: "Judge", 21: "Spirit Guide",
}
IMPOSTOR_ROLES = {1, 5, 7, 9, 18}

GAME_OVER_REASONS = {
    0: "The crew won by voting out the impostors",
    1: "The crew won by doing all tasks",
    2: "The impostors won by voting",
    3: "The impostors won by killing",
    4: "The impostors won by sabotage",
    5: "The crew won (an impostor left)",
    6: "The impostors won (a crewmate left)",
    7: "Hide n Seek: the crew survived until time ran out",
    8: "Hide n Seek: the impostor caught everyone",
}

COLORS = {
    0: "Red", 1: "Blue", 2: "Green", 3: "Pink", 4: "Orange", 5: "Yellow",
    6: "Black", 7: "White", 8: "Purple", 9: "Brown", 10: "Cyan", 11: "Lime",
    12: "Maroon", 13: "Rose", 14: "Banana", 15: "Gray", 16: "Tan", 17: "Coral",
}


# --- Maps and game modes -----------------------------------------------

MAPS = {
    0: "The Skeld",
    1: "MIRA HQ",
    2: "Polus",
    3: "dlekS ehT",
    4: "The Airship",
    5: "The Fungle",
}

GAME_MODES = {
    1: "Normal",
    2: "Hide n Seek",
    3: "Normal (April Fools)",
    4: "Hide n Seek (April Fools)",
}
