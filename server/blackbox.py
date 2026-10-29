"""
Black box: remembers the latest messages for each player.

If someone is disconnected unexpectedly, a report is saved in the logs/
folder with the last things the game and the server sent each other. Then
you can see what happened just before, a bit like an airplane's black box.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional

from . import protocol
from .config import PROJECT_DIR
from .messages import MessageReader

REPORT_DIR = PROJECT_DIR / "logs"

GAME_DATA_NAMES = {1: "Data", 2: "RPC", 4: "Spawn", 5: "Despawn", 6: "SceneChange", 7: "Ready", 8: "Settings"}
RPC_NAMES = {
    0: "PlayAnimation", 1: "CompleteTask", 2: "SyncSettings", 3: "SetInfected", 4: "Exiled",
    5: "CheckName", 6: "SetName", 7: "CheckColor", 8: "SetColor", 11: "ReportDeadBody",
    12: "MurderPlayer", 13: "SendChat", 14: "StartMeeting", 15: "SetScanner", 18: "SetStartCounter",
    19: "EnterVent", 20: "ExitVent", 21: "SnapTo", 22: "CloseMeeting", 23: "VotingComplete",
    24: "CastVote", 25: "ClearVote", 26: "AddVote", 27: "CloseDoorsOfType", 29: "SetTasks",
    33: "SendQuickChat", 35: "UpdateSystem", 38: "SetLevel", 39: "SetHat", 40: "SetSkin",
    41: "SetPet", 42: "SetVisor", 43: "SetNamePlate", 44: "SetRole", 45: "ProtectPlayer",
    46: "Shapeshift", 47: "CheckMurder", 48: "CheckProtect", 16: "SendChatNote",
    49: "Pet", 50: "CancelPet", 55: "CheckShapeshift", 60: "LobbyTimeExpiring", 61: "ExtendLobbyTimer",
    62: "CheckVanish", 63: "StartVanish", 64: "CheckAppear", 65: "StartAppear",
}


def describe(payload: bytes) -> str:
    """Turns bytes into a short text, for example 'GameDataTo→3 [RPC:CheckName, RPC:CheckColor]'."""
    parts: List[str] = []
    try:
        for message in MessageReader(payload).messages():
            tag = message.tag if message.tag is not None else -1
            name = protocol.MESSAGE_NAMES.get(tag, f"tag {tag}").split(" (")[0]
            if tag in (protocol.GAME_DATA, protocol.GAME_DATA_TO):
                reader = MessageReader(message.data)
                reader.read_int32()
                if tag == protocol.GAME_DATA_TO:
                    name += f"→{reader.read_packed_int32()}"
                inner = []
                for part in reader.messages():
                    text = GAME_DATA_NAMES.get(part.tag or 0, f"part {part.tag}")
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
        parts.append(f"could not be understood ({len(payload)} B)")
    return " + ".join(parts) or f"empty ({len(payload)} B)"


class FlightRecorder:
    def __init__(self, size: int = 500):
        self.events: Deque[str] = deque(maxlen=size)
        self.started = time.monotonic()
        self.unreliable_in = 0
        self.unreliable_out = 0
        self.last_in = time.monotonic()
        self.last_ack_out = time.monotonic()

    @staticmethod
    def _stamp() -> str:
        now = time.time()
        return time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now * 10) % 10}"

    def _flush_counts(self) -> None:
        if self.unreliable_in or self.unreliable_out:
            self.events.append(
                f"{self._stamp()}  ..  unreliable packets (for example movement): {self.unreliable_in} in, {self.unreliable_out} out"
            )
            self.unreliable_in = self.unreliable_out = 0

    def note(self, direction: str, payload: bytes, packet_id: Optional[int] = None) -> None:
        self._flush_counts()
        number = f"#{packet_id} " if packet_id is not None else ""
        self.events.append(f"{self._stamp()}  {direction}  {number}{describe(payload)}")

    def note_text(self, direction: str, text: str) -> None:
        self._flush_counts()
        self.events.append(f"{self._stamp()}  {direction}  {text}")

    def save(self, name: str, why: str, lobby: Optional[str]) -> Optional[Path]:
        try:
            REPORT_DIR.mkdir(exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in name) or "player"
            path = REPORT_DIR / f"disconnect-{time.strftime('%Y%m%d-%H%M%S')}-{safe}.txt"
            lines = [
                f"Player: {name}",
                f"Lobby: {lobby or '-'}",
                f"Reason: {why}",
                f"Connected for {int(time.monotonic() - self.started)} seconds",
                f"Last packet from the game: {time.monotonic() - self.last_in:.1f} s before the disconnect",
                f"Last receipt from the server: {time.monotonic() - self.last_ack_out:.1f} s before the disconnect",
                "",
                "The latest messages (in = from the game, out = from the server):",
                "",
                *self.events,
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            # Only keep the 15 latest reports.
            old = sorted(REPORT_DIR.glob("disconnect-*.txt"))[:-15]
            for file in old:
                file.unlink()
            return path
        except OSError:
            return None
