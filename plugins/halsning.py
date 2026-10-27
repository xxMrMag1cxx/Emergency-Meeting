"""
Hälsning: skriver ett välkomstmeddelande i chatten när någon kommer in i lobbyn.

Det här är det enklaste möjliga pluginet. Kopiera det när ni gör ett eget!
"""

import logging

# Namn och beskrivning visas när servern startar.
NAME = "Hälsning"
DESCRIPTION = "välkomnar nya spelare i chatten"

log = logging.getLogger("plugin.halsning")


def on_player_spawned(lobby, player):
    """Körs när en spelares gubbe har dykt upp i lobbyn."""
    player.send_chat(f"Välkommen till {lobby.code}, {player.name}! Ha det kul!")
    log.info("Hälsade på %s", player.name)
