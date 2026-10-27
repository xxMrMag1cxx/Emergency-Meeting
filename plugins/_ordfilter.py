"""
Ordfilter: stoppar chattmeddelanden som innehåller vissa ord.

AVSTÄNGT: filnamnet börjar med _ . Byt namn till ordfilter.py för att slå på det.

Lägg till egna ord i listan nedan (med små bokstäver).
"""

import logging

NAME = "Ordfilter"
DESCRIPTION = "stoppar fula ord i chatten"

BLOCKED_WORDS = ["dumhuvud", "fuskare"]

log = logging.getLogger("plugin.ordfilter")


def on_chat(lobby, player, text):
    lowered = text.lower()
    for word in BLOCKED_WORDS:
        if word in lowered:
            player.send_chat("Ditt meddelande stoppades av ordfiltret.")
            log.info("Stoppade ett meddelande från %s", player.name)
            return False  # False = skicka inte vidare till de andra
    return True
