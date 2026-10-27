"""
Tärning: chattkommandon som /tärning och /hjälp.

AVSTÄNGT: filnamnet börjar med _ . Byt namn till tarning.py för att slå på det.

Visar hur man gör egna chattkommandon. Om on_chat returnerar False
skickas meddelandet inte vidare, så de andra ser bara svaret och inte
själva kommandot.
"""

import random

NAME = "Tärning"
DESCRIPTION = "chattkommandon: /tärning, /hjälp, /inställning"


def on_chat(lobby, player, text):
    command = text.strip().lower()

    if command in ("/tärning", "/tarning", "/dice"):
        roll = random.randint(1, 6)
        lobby.send_chat(f"{player.name} slog en tärning och fick {roll}!")
        return False

    if command in ("/hjälp", "/hjalp", "/help"):
        player.send_chat("Kommandon: /tärning, /inställning <namn>")
        return False

    if command.startswith("/inställning") or command.startswith("/installning"):
        # T.ex. "/inställning kill cooldown"
        wanted = text.split(" ", 1)[1].strip().lower() if " " in text else ""
        for name, value in lobby.settings.items():
            if wanted and wanted in name.lower():
                player.send_chat(f"{name}: {value}")
                return False
        player.send_chat("Hittade ingen sådan inställning. Prova t.ex. /inställning kill cooldown")
        return False

    return True  # vanliga meddelanden skickas vidare som vanligt
