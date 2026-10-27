"""
Svart låda: kommer ihåg de senaste meddelandena för varje spelare.

Om någon kopplas från oväntat sparas en rapport i mappen loggar/ med det
sista som spelet och servern skickade till varandra. Då kan man se vad
som hände precis innan, ungefär som en flygplans svarta låda.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional

from . import protocol
from .config import PROJECT_DIR
from .messages import MessageReader

REPORT_DIR = PROJECT_DIR / "loggar"

GAME_DATA_NAMES = {1: "Data", 2: "RPC", 4: "Spawn", 5: "Despawn", 6: "SceneChange", 7: "Ready", 8: "Settings"}
RPC_NAMES = {
    0: "PlayAnimation", 1: "CompleteTask", 2: "SyncSettings", 3: "SetInfected", 4: "Exiled",
    5: "CheckName", 6: "SetName", 7: "CheckColor", 8: "SetColor", 11: "ReportDeadBody",
    12: "MurderPlayer", 13: "SendChat", 14: "StartMeeting", 15: "SetScanner", 18: "SetStartCounter",
    19: "EnterVent", 20: "ExitVent", 21: "SnapTo", 22: "CloseMeeting", 23: "VotingComplete",
    24: "CastVote", 25: "ClearVote", 26: "AddVote", 27: "CloseDoorsOfType", 29: "SetTasks",
    33: "SendQuickChat", 35: "UpdateSystem", 38: "SetLevel", 39: "SetHat", 40: "SetSkin",
    41: "SetPet", 42: "SetVisor", 43: "SetNamePlate", 44: "SetRole", 47: "CheckMurder",
    49: "Pet", 50: "CancelPet", 60: "LobbyTimeExpiring", 61: "ExtendLobbyTimer",
}


def describe(payload: bytes) -> str:
    """Gör om bytes till en kort text, t.ex. 'GameDataTo→3 [RPC:CheckName, RPC:CheckColor]'."""
    parts: List[str] = []
    try:
        for message in MessageReader(payload).messages():
            tag = message.tag if message.tag is not None else -1
            name = protocol.MESSAGE_NAMES.get(tag, f"tagg {tag}").split(" (")[0]
            if tag in (protocol.GAME_DATA, protocol.GAME_DATA_TO):
                reader = MessageReader(message.data)
                reader.read_int32()
                if tag == protocol.GAME_DATA_TO:
                    name += f"→{reader.read_packed_int32()}"
                inner = []
                for part in reader.messages():
                    text = GAME_DATA_NAMES.get(part.tag or 0, f"del {part.tag}")
                    if part.tag == protocol.GameDataTag.RPC:
                        net_id = part.read_packed_uint32()
                        call = part.read_byte()
                        text = f"RPC:{RPC_NAMES.get(call, call)}@{net_id}"
                    elif part.tag == protocol.GameDataTag.SPAWN:
                        text = f"Spawn:{part.read_packed_uint32()}"
                    elif part.tag in (protocol.GameDataTag.DATA, protocol.GameDataTag.DESPAWN):
                        text += f"@{part.read_packed_uint32()}"
                    inner.append(text)
                name += " [" + ", ".join(inner) + "]"
            parts.append(f"{name} ({len(message.data)} B)")
    except ValueError:
        parts.append(f"kunde inte tolkas ({len(payload)} B)")
    return " + ".join(parts) or f"tomt ({len(payload)} B)"


class FlightRecorder:
    def __init__(self, size: int = 120):
        self.events: Deque[str] = deque(maxlen=size)
        self.started = time.monotonic()

    def note(self, direction: str, payload: bytes) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.events.append(f"{stamp}  {direction}  {describe(payload)}")

    def note_text(self, direction: str, text: str) -> None:
        self.events.append(f"{time.strftime('%H:%M:%S')}  {direction}  {text}")

    def save(self, name: str, why: str, lobby: Optional[str]) -> Optional[Path]:
        try:
            REPORT_DIR.mkdir(exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in name) or "spelare"
            path = REPORT_DIR / f"frankoppling-{time.strftime('%Y%m%d-%H%M%S')}-{safe}.txt"
            lines = [
                f"Spelare: {name}",
                f"Lobby: {lobby or '-'}",
                f"Anledning: {why}",
                f"Ansluten i {int(time.monotonic() - self.started)} sekunder",
                "",
                "Senaste meddelandena (in = från spelet, ut = från servern):",
                "",
                *self.events,
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            # Spara bara de 15 senaste rapporterna.
            old = sorted(REPORT_DIR.glob("frankoppling-*.txt"))[:-15]
            for file in old:
                file.unlink()
            return path
        except OSError:
            return None
