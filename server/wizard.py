"""
The guide the first time the server starts (when config.json doesn't exist).

One thing at a time, so that nothing else happens on the screen meanwhile:

  1. the language of the Terminal window
  2. the server's name
  3. ngrok: a fixed HTTPS address (paste a key, or press Enter to skip)
  4. playit.gg: friends can play from their own homes (approve the server,
     get a tunnel and wait until its address works, or press Enter to skip)

After that the server starts everything, one part at a time (startup.py),
the same way as /reload does for playit.gg and the HTTPS address.
"""

from __future__ import annotations

import logging
from typing import Set

from . import i18n
from .config import Config, save_config
from .i18n import tr
from .ngrok import Ngrok
from .playit import Playit, find_playitd, playitd_name
from .terminal import (
    LIGHT_BLUE, PURPLE, ask_server_name, choose_language, paint, print_box, print_setup_step, say, success,
    wait_for_enter,
)

log = logging.getLogger("server")

SETUP_STEPS = 4


def first_start(config: Config) -> Set[str]:
    """
    Asks everything that is needed the first time. Returns what the host
    skipped ("ngrok", "playit"), so that the start doesn't ask again right away.
    """
    skipped: Set[str] = set()

    print_setup_step(1, SETUP_STEPS)
    code = choose_language(i18n.normalize(config.language))
    i18n.set_language(code)
    config.language = i18n.language_name(code)
    save_config(config)

    print_setup_step(2, SETUP_STEPS)
    config.server_name = ask_server_name(config.server_name)
    save_config(config)

    print_setup_step(3, SETUP_STEPS, box_follows=config.https_tunnel and config.ngrok and not Ngrok.has_key())
    if not (config.https_tunnel and config.ngrok):
        say(tr("ngrok is turned off in config.json, skipping it."))
    elif Ngrok.has_key():
        success(tr("ngrok already has a key."))
    else:
        ngrok = Ngrok(config.ngrok_path, config.port, lambda url, changed: None, lambda: None, print_box)
        if ngrok._ask_for_key():
            success(tr("ngrok is set up!"))
        else:
            skipped.add("ngrok")
            say(tr("Skipping ngrok. The server uses Cloudflare instead (the address changes every start)."))

    binary = find_playitd(config.playit_path) if config.playit else None
    # (A log line can come before playit.gg's box, for example without internet, so a new line here.)
    print_setup_step(4, SETUP_STEPS, box_follows=False)
    if not config.playit:
        say(tr("playit.gg is turned off in config.json, skipping it."))
    elif not binary:
        skipped.add("playit")
        say(tr("playit.gg isn't here (playit/{name} is missing), skipping it.", name=playitd_name()))
    else:
        playit = Playit(binary, config.port, print_box)
        try:
            ready = playit.setup(wait_for_enter)
        except Exception:  # the guide must never stop the server
            log.exception("Something went wrong with playit.gg. The server still works on your wifi.")
            ready = False
        if ready:
            success(tr("playit.gg is set up! The game's address: {address}", address=playit.address))
        else:
            skipped.add("playit")
            say(tr("Skipping playit.gg for now, so only devices on your wifi can play."))
            say(tr("Restart the server (/reboot) when you want to set it up."))

    print()
    success(tr("The setup is done!"))
    say(tr("Now {name} starts, one part at a time (like {reload}).",
           name=paint(config.server_name, PURPLE, bold=True), reload=paint("/reload", LIGHT_BLUE, bold=True)))
    print()
    return skipped
