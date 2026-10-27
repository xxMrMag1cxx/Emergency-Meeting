"""
Spelinställningarna: allt man kan ställa in i lobbyn.

Spelet skickar inställningarna som en lång rad bytes. Här läser vi ut
varje inställning och ger den samma namn som i spelets meny, så att
loggen kan visa vad som ändras, t.ex.

    Kill Cooldown: 30 s -> 25 s

Om en framtida version av spelet lägger till nya inställningar som vi inte
känner till sparar vi resten som "Övriga inställningar", så att vi ändå
märker att något ändrades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from . import protocol
from .messages import MessageReader

RULES_PRESETS = {0: "Standard", 1: "Standard Roles", 2: "Flashlight", 100: "Custom"}
KILL_DISTANCES = {0: "Short", 1: "Medium", 2: "Long"}
TASK_BAR_UPDATES = {0: "Always", 1: "Meetings", 2: "Never"}
LOBBY_TAGS = {0: "None", 1: "Beginner", 2: "Intermediate", 3: "Expert"}
LANGUAGES = {
    1: "Other", 2: "Spanish (LA)", 4: "Korean", 8: "Russian", 16: "Portuguese",
    32: "Arabic", 64: "Filipino", 128: "Polish", 256: "English", 512: "Japanese",
    1024: "Spanish (EU)", 2048: "Brazilian", 4096: "Dutch", 8192: "French",
    16384: "German", 32768: "Italian", 65536: "Chinese (S)", 131072: "Chinese (T)",
    262144: "Irish",
}
ROLE_NAMES = {
    2: "Scientist", 3: "Engineer", 4: "Guardian Angel", 5: "Shapeshifter",
    8: "Noisemaker", 9: "Phantom", 10: "Tracker", 12: "Detective",
    18: "Viper", 19: "Judge", 21: "Spirit Guide",
}


@dataclass
class GameOptions:
    raw: bytes = b""  # inställningarna precis som spelet skickade dem
    version: int = 0
    mode: int = 1
    max_players: int = 15
    keywords: int = 0  # språk
    map_id: int = 0
    num_impostors: int = 1
    # Alla inställningar med spelets namn, t.ex. {"Kill Cooldown": "25 s"}
    settings: Dict[str, str] = field(default_factory=dict)

    @property
    def map_name(self) -> str:
        return protocol.MAPS.get(self.map_id, f"karta {self.map_id}")

    @property
    def mode_name(self) -> str:
        return protocol.GAME_MODES.get(self.mode, f"läge {self.mode}")


# --- Hur värden ska visas ------------------------------------------------

def _number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _seconds(value: float) -> str:
    return f"{_number(value)} s"


def _times(value: float) -> str:
    return f"{_number(value)}x"


def _on_off(value: bool) -> str:
    return "On" if value else "Off"


def _languages(mask: int) -> str:
    if mask == 0:
        return "All"
    names = [name for bit, name in LANGUAGES.items() if mask & bit]
    return ", ".join(names) or str(mask)


# --- Läsa inställningarna ------------------------------------------------

def read_options(reader: MessageReader) -> GameOptions:
    """Läser inställningar i spelets format: [längd][version][meddelande]."""
    reader.read_packed_uint32()  # en längd som spelet inte använder
    start = reader.pos
    version = reader.read_byte()
    inner = reader.read_message()
    options = GameOptions(raw=reader.data[start : reader.pos], version=version)

    try:
        _read_all(inner, options)
    except ValueError:
        pass  # okänt format: resten hamnar i "Övriga inställningar" nedan
    if inner.remaining:
        options.settings["Övriga inställningar"] = inner.read_rest().hex(" ")
    return options


def _read_all(r: MessageReader, o: GameOptions) -> None:
    s = o.settings
    o.mode = r.read_byte()
    s["Game Mode"] = "Hide and Seek" if o.mode in (2, 4) else "Classic"
    if o.version >= 8:
        if r.read_byte() == 1:
            s["Game Mode"] += " (April Fools)"
        preset = r.read_byte()
        s["Rules Preset"] = RULES_PRESETS.get(preset, str(preset))

    o.max_players = r.read_byte()
    s["Max Players"] = str(o.max_players)
    o.keywords = r.read_uint32()
    s["Language"] = _languages(o.keywords)
    o.map_id = r.read_byte()
    s["Map"] = o.map_name
    s["Player Speed"] = _times(r.read_float())
    s["Crewmate Vision"] = _times(r.read_float())
    s["Impostor Vision"] = _times(r.read_float())

    if o.mode in (2, 4):
        _read_hide_and_seek(r, o)
    else:
        _read_classic(r, o)


def _read_classic(r: MessageReader, o: GameOptions) -> None:
    s = o.settings
    s["Kill Cooldown"] = _seconds(r.read_float())
    s["Common Tasks"] = str(r.read_byte())
    s["Long Tasks"] = str(r.read_byte())
    s["Short Tasks"] = str(r.read_byte())
    s["Emergency Meetings"] = str(r.read_int32())
    o.num_impostors = r.read_byte()
    s["Impostors"] = str(o.num_impostors)
    distance = r.read_byte()
    s["Kill Distance"] = KILL_DISTANCES.get(distance, str(distance))
    s["Discussion Time"] = _seconds(r.read_int32())
    s["Voting Time"] = _seconds(r.read_int32())
    r.read_bool()  # "är standardvärden", visas inte i spelet
    s["Emergency Cooldown"] = _seconds(r.read_byte())
    s["Confirm Ejects"] = _on_off(r.read_bool())
    s["Visual Tasks"] = _on_off(r.read_bool())
    s["Anonymous Votes"] = _on_off(r.read_bool())
    bar = r.read_byte()
    s["Task Bar Updates"] = TASK_BAR_UPDATES.get(bar, str(bar))
    if o.version >= 9:
        tag = r.read_byte()
        s["Lobby Level"] = LOBBY_TAGS.get(tag, str(tag))
    _read_roles(r, o)


def _read_hide_and_seek(r: MessageReader, o: GameOptions) -> None:
    s = o.settings
    o.num_impostors = 1
    s["Common Tasks"] = str(r.read_byte())
    s["Long Tasks"] = str(r.read_byte())
    s["Short Tasks"] = str(r.read_byte())
    r.read_bool()  # "är standardvärden"
    s["Crewmate Vent Uses"] = str(r.read_int32())
    s["Hiding Time"] = _seconds(r.read_float())
    s["Crewmate Flashlight Size"] = _number(r.read_float())
    s["Impostor Flashlight Size"] = _number(r.read_float())
    s["Use Flashlight"] = _on_off(r.read_bool())
    s["Final Hide Seek Map"] = _on_off(r.read_bool())
    s["Final Hide Time"] = _seconds(r.read_float())
    s["Final Seeker Speed"] = _times(r.read_float())
    s["Final Hide Pings"] = _on_off(r.read_bool())
    s["Show Names"] = _on_off(r.read_bool())
    seeker = r.read_uint32()
    s["Impostor (seeker)"] = "Random" if seeker >= 255 else f"spelare nr {seeker}"
    s["Max Ping Time"] = _seconds(r.read_float())
    s["Crewmate Time in Vent"] = _seconds(r.read_float())
    if o.version >= 9:
        tag = r.read_byte()
        s["Lobby Level"] = LOBBY_TAGS.get(tag, str(tag))


def _read_roles(r: MessageReader, o: GameOptions) -> None:
    s = o.settings
    for _ in range(r.read_packed_uint32()):
        role = r.read_int16()
        if role not in ROLE_NAMES and not 0 <= role <= 64:
            # Ser inte ut som en roll: formatet är nog nytt. Sluta här.
            raise ValueError(f"okänd roll {role}")
        name = ROLE_NAMES.get(role, f"Roll {role}")
        s[f"{name} Max"] = str(r.read_byte())
        s[f"{name} Chance"] = f"{r.read_byte()}%"
        _read_role_settings(r.read_message(), role, name, s)


def _read_role_settings(r: MessageReader, role: int, name: str, s: Dict[str, str]) -> None:
    if role == 2:  # Scientist
        s[f"{name}: Vitals Display Cooldown"] = _seconds(r.read_byte())
        s[f"{name}: Battery Duration"] = _seconds(r.read_byte())
    elif role == 3:  # Engineer
        s[f"{name}: Vent Use Cooldown"] = _seconds(r.read_byte())
        s[f"{name}: Max Time in Vents"] = _seconds(r.read_byte())
    elif role == 4:  # Guardian Angel
        s[f"{name}: Protect Cooldown"] = _seconds(r.read_byte())
        s[f"{name}: Protection Duration"] = _seconds(r.read_byte())
        s[f"{name}: Protect Visible to Impostors"] = _on_off(r.read_bool())
    elif role == 5:  # Shapeshifter
        s[f"{name}: Leave Shapeshifting Evidence"] = _on_off(r.read_bool())
        s[f"{name}: Shapeshift Cooldown"] = _seconds(r.read_byte())
        s[f"{name}: Shapeshift Duration"] = _seconds(r.read_byte())
    elif role == 8:  # Noisemaker
        s[f"{name}: Alert Duration"] = _seconds(r.read_byte())
        s[f"{name}: Impostors Get Alert"] = _on_off(r.read_bool())
    elif role == 9:  # Phantom
        s[f"{name}: Vanish Cooldown"] = _seconds(r.read_byte())
        s[f"{name}: Vanish Duration"] = _seconds(r.read_byte())
    elif role == 10:  # Tracker
        s[f"{name}: Tracking Cooldown"] = _seconds(r.read_byte())
        s[f"{name}: Tracking Duration"] = _seconds(r.read_byte())
        s[f"{name}: Tracking Delay"] = _seconds(r.read_byte())
    elif role == 12:  # Detective
        s[f"{name}: Suspect Limit"] = str(r.read_byte())
    elif role == 18:  # Viper
        s[f"{name}: Dissolve Time"] = _seconds(r.read_byte())
    elif role == 19:  # Judge
        s[f"{name}: Task Requirement"] = f"{r.read_byte()}%"
    elif role == 21:  # Spirit Guide
        s[f"{name}: Cooldown"] = _seconds(r.read_byte())

    if r.remaining:  # inställningar vi inte känner till för den här rollen
        s[f"{name}: övrigt"] = r.read_rest().hex(" ")


# --- Jämföra -------------------------------------------------------------

def differences(old: GameOptions, new: GameOptions) -> List[str]:
    """Returnerar en rad per ändrad inställning, t.ex. 'Kill Cooldown: 30 s -> 25 s'."""
    lines = []
    for key, value in new.settings.items():
        before = old.settings.get(key)
        if before is not None and before != value and "övrig" in key.lower():
            lines.append(f"{key} (okända inställningar, kan inte visa vad)")
        elif before is None and old.settings:
            lines.append(f"{key}: {value} (ny)")
        elif before is not None and before != value:
            lines.append(f"{key}: {before} -> {value}")
    for key in old.settings:
        if key not in new.settings and new.settings:
            lines.append(f"{key}: borttagen")
    return lines
