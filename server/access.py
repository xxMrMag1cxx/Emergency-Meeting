"""
Who may join the server: the ban list and the list of allowed names.

  bans.json          players who are banned. When the host bans someone in
                     Among Us, the server saves it here, so that the player
                     can't come back (not even after a restart). /ban, /unban
                     and /bans in the Terminal window.
  allowed-names.txt  one name per line. With "only_allowed_names": true in
                     config.json, only these names can join. /allow,
                     /disallow and /allowed in the Terminal window.

A player is recognized by the name and, when the game has sent it, the
account id ("Puid") the game sends when it fetches its token. With the
account id a banned player can't get in by changing the name.

Names are compared without caring about upper/lower case or extra spaces.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, Optional

from .config import PROJECT_DIR

log = logging.getLogger("server")

BANS_FILE = PROJECT_DIR / "bans.json"
ALLOWED_FILE = PROJECT_DIR / "allowed-names.txt"


def same_name(name: str) -> str:
    """The name as it is compared: "  Blobi " and "blobi" are the same."""
    return " ".join(name.split()).casefold()


@dataclass
class Ban:
    name: str
    puid: str = ""
    banned_at: str = ""
    by: str = ""  # "host:<name>" or "terminal"


class Access:
    def __init__(self) -> None:
        self.bans: List[Ban] = []
        self.allowed: List[str] = []
        self.load()

    # --- Files -------------------------------------------------------------

    def load(self) -> None:
        self.bans = []
        try:
            data = json.loads(BANS_FILE.read_text(encoding="utf-8"))
            for entry in data if isinstance(data, list) else []:
                if isinstance(entry, dict) and entry.get("name"):
                    self.bans.append(Ban(**{k: str(v) for k, v in entry.items() if k in Ban.__dataclass_fields__}))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as error:
            log.error("bans.json can't be read: %s", error)
        try:
            lines = ALLOWED_FILE.read_text(encoding="utf-8").splitlines()
            self.allowed = [" ".join(line.split()) for line in lines if line.strip() and not line.startswith("#")]
        except FileNotFoundError:
            self.allowed = []
        except OSError as error:
            log.error("allowed-names.txt can't be read: %s", error)

    def _save_bans(self) -> bool:
        try:
            BANS_FILE.write_text(json.dumps([asdict(b) for b in self.bans], indent=4, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
            return True
        except OSError as error:
            log.error("Could not save bans.json: %s", error)
            return False

    def _save_allowed(self) -> bool:
        text = "# Names that may join when \"only_allowed_names\" is true in config.json. One per line.\n"
        try:
            ALLOWED_FILE.write_text(text + "".join(name + "\n" for name in self.allowed), encoding="utf-8")
            return True
        except OSError as error:
            log.error("Could not save allowed-names.txt: %s", error)
            return False

    # --- Bans ----------------------------------------------------------------

    def find_ban(self, name: str, puid: str = "") -> Optional[Ban]:
        for ban in self.bans:
            if (puid and ban.puid and puid == ban.puid) or same_name(name) == same_name(ban.name):
                return ban
        return None

    def ban(self, name: str, puid: str, by: str) -> Ban:
        """Adds a ban (or updates the one that is already there) and saves the file."""
        existing = self.find_ban(name, puid)
        if existing is not None:
            existing.puid = existing.puid or puid
            self._save_bans()
            return existing
        ban = Ban(name=" ".join(name.split()), puid=puid,
                  banned_at=datetime.now().strftime("%Y-%m-%d %H:%M"), by=by)
        self.bans.append(ban)
        self._save_bans()
        return ban

    def unban(self, which: str) -> Optional[Ban]:
        """Removes a ban by name or by its number in /bans. Returns it, or None if there was none."""
        which = which.strip()
        target = None
        if which.isdigit() and 1 <= int(which) <= len(self.bans):
            target = self.bans[int(which) - 1]
        else:
            target = next((b for b in self.bans if same_name(b.name) == same_name(which)), None)
        if target is None:
            return None
        self.bans.remove(target)
        self._save_bans()
        return target

    # --- Allowed names -------------------------------------------------------

    def is_allowed(self, name: str) -> bool:
        return any(same_name(name) == same_name(allowed) for allowed in self.allowed)

    def allow(self, name: str) -> bool:
        """Adds the name. False if it was already on the list."""
        name = " ".join(name.split())
        if self.is_allowed(name):
            return False
        self.allowed.append(name)
        self._save_allowed()
        return True

    def disallow(self, name: str) -> bool:
        """Removes the name. False if it wasn't on the list."""
        before = len(self.allowed)
        self.allowed = [a for a in self.allowed if same_name(a) != same_name(name)]
        if len(self.allowed) == before:
            return False
        self._save_allowed()
        return True


# --- Commands in the Terminal window --------------------------------------------

def add_access_commands(server) -> None:
    """/ban, /unban, /bans, /allow, /disallow and /allowed."""
    from .i18n import tr
    from .protocol import DisconnectReason
    from .terminal import ERROR, LIGHT_BLUE, PURPLE, paint, print_box, say, success

    console, access, loop = server.console, server.access, server.loop

    def usage(text: str) -> None:
        say(tr("Usage: {command}", command=paint(text, LIGHT_BLUE, bold=True)))

    def online(name: str):
        for connection in list(server.hazel.connections.values()):
            hs = connection.handshake
            if hs is not None and same_name(hs.name) == same_name(name):
                return connection
        return None

    def ban(argument: str) -> None:
        if not argument.strip():
            usage(tr("/ban <name>"))
            return
        connection = online(argument)
        name = connection.handshake.name if connection is not None else argument
        saved = access.ban(name, connection.puid if connection else "", "terminal")
        success(tr("{name} is banned and can't join the server again.", name=paint(saved.name, PURPLE, bold=True)))
        if connection is not None:
            loop.call_soon_threadsafe(connection.disconnect, DisconnectReason.CUSTOM, "You are banned from this server.")
            say(tr("{name} was playing and has been disconnected.", name=saved.name))
        log.info("%s was banned from the Terminal window", saved.name)

    def unban(argument: str) -> None:
        if not argument.strip():
            usage(tr("/unban <name or number>"))
            return
        removed = access.unban(argument)
        if removed is None:
            say(paint(tr("{name} isn't banned.", name=argument.strip()), ERROR) + " "
                + tr("Use {bans} to see the list.", bans=paint("/bans", LIGHT_BLUE, bold=True)))
            return
        success(tr("{name} can join again.", name=paint(removed.name, PURPLE, bold=True)))
        log.info("%s was unbanned", removed.name)

    def who(b: Ban) -> str:
        if b.by.startswith("host:"):
            return tr("the host {name}", name=b.by[5:])
        return tr("the Terminal window")

    def bans(_argument: str) -> None:
        if not access.bans:
            print_box(tr("BANNED PLAYERS"), [tr("Nobody is banned.")])
            return
        lines = [tr("{number}. {name}  (banned {date} by {who})", number=index,
                    name=paint(b.name, PURPLE, bold=True), date=b.banned_at, who=who(b))
                 for index, b in enumerate(access.bans, start=1)]
        lines += ["", tr("Let someone in again with {command}.",
                         command=paint(tr("/unban <name or number>"), LIGHT_BLUE, bold=True))]
        print_box(tr("BANNED PLAYERS"), lines)

    def allow(argument: str) -> None:
        if not argument.strip():
            usage(tr("/allow <name>"))
            return
        name = " ".join(argument.split())
        if access.allow(name):
            success(tr("{name} is on the list of allowed names.", name=paint(name, PURPLE, bold=True)))
        else:
            say(tr("{name} is already on the list.", name=name))
        if not server.config.only_allowed_names:
            say(tr("The list is only used with {setting}.",
                   setting=paint("/setting only_allowed_names = true", LIGHT_BLUE, bold=True)))

    def disallow(argument: str) -> None:
        if not argument.strip():
            usage(tr("/disallow <name>"))
            return
        if access.disallow(argument):
            success(tr("{name} is no longer on the list of allowed names.", name=paint(argument.strip(), PURPLE, bold=True)))
        else:
            say(paint(tr("{name} isn't on the list.", name=argument.strip()), ERROR))

    def allowed(_argument: str) -> None:
        lines = [f"- {paint(name, PURPLE, bold=True)}" for name in access.allowed] or [tr("The list is empty.")]
        lines.append("")
        if server.config.only_allowed_names:
            lines.append(tr("Only these names can join (only_allowed_names is true)."))
        else:
            lines.append(tr("Everyone can join right now. Turn the list on with {setting} and {reboot}.",
                            setting=paint("/setting only_allowed_names = true", LIGHT_BLUE, bold=True),
                            reboot=paint("/reboot", LIGHT_BLUE, bold=True)))
        print_box(tr("ALLOWED NAMES"), lines)

    console.add("ban", "/ban <name>", "Ban a player from the server", ban)
    console.add("unban", "/unban <name or number>", "Let a banned player in again", unban)
    console.add("bans", "/bans", "List the banned players", bans)
    console.add("allow", "/allow <name>", "Add a name to the allowed names", allow)
    console.add("disallow", "/disallow <name>", "Remove a name from the allowed names", disallow)
    console.add("allowed", "/allowed", "List the allowed names", allowed)
