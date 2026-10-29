"""
Starts the server one part at a time, and runs /reload and /reboot.

The order goes from the inside out: what the other parts need starts first,
and the front door (the HTTPS address the game and the join page use) opens
last, so that nobody gets in before everything behind it works:

  1. Plugins        loaded before any player can connect
  2. Game server    UDP port 22023. Checked with a test packet to itself
  3. Join page      HTTP on port 22023. Checked by fetching its own page.
                    ngrok and Cloudflare send their traffic here
  4. playit.gg      sends the game (UDP) from the internet to the game server,
                    so the game server must already run. Checked with a test
                    packet through the playit.gg address
  5. HTTPS          ngrok (otherwise Cloudflare). Last, because the join page
                    hands out the playit.gg address: if HTTPS opened before
                    playit.gg, a friend could get the wrong address. Checked by
                    fetching the page through HTTPS

Each step waits until the one before is completely done. SERVER IS ONLINE!
comes only when all of them are done.

If a step goes wrong the first time, the server restarts itself (/reboot).
If it goes wrong again after that, the server starts the rest as well as it
can (Cloudflare instead of ngrok, or only wifi without playit.gg) and shows
what is wrong, so that the host can fix it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set

from . import __copyright__, __version__, i18n
from .config import CONFIG_FILE, PROJECT_DIR, Config, forget_pending, save_config
from .game import Game
from .hazel import HazelServer
from .i18n import tr
from .lobby import LobbyManager
from .matchmaker import ServerInfo, start_matchmaker
from .ngrok import Ngrok
from .playit import Playit, find_playitd
from .plugins import PluginManager
from .protocol import DisconnectReason
from .qrcode import QrCode
from .region import region_info_json
from .settings import add_settings_commands
from .terminal import (
    ERROR, GREEN, LIGHT_BLUE, PLAYING, PURPLE, Console, clean_name, output_lock, paint, print_banner, print_box,
    print_step, print_step_detail, print_step_result, restore_terminal, say, success, wait_for_enter,
)
from .tunnel import Tunnel, find_cloudflared

log = logging.getLogger("server")

# Set in the environment when the server restarts itself after a failed start
AFTER_FAILED_START = "EM_AFTER_FAILED_START"

PLAYIT_TIMEOUT = 75  # seconds for playit.gg to give a working address
NGROK_TIMEOUT = 100  # seconds for ngrok (40 to start, 30 to check, and some margin)
CLOUDFLARE_TIMEOUT = 110  # cloudflared checks for up to 90 seconds itself
PROBE_SECONDS = 15  # how long to try the test packet through playit.gg
PROBE_AFTER_RESTART = 25  # the same after playitd has been restarted once
LOOPBACK = ("127.0.0.1", "::1")  # where playitd sends the packets of friends who play from home


@dataclass
class Problem:
    """Something that went wrong while starting."""

    part: str
    text: str
    retry_helps: bool = True  # False = a restart doesn't fix it, the host has to do something
    tips: List[str] = field(default_factory=list)


class Server:
    def __init__(self, config: Config, first_start: bool = False, skipped: Optional[Set[str]] = None):
        self.config = config
        self.first_start = first_start
        self.skipped = set(skipped or ())
        self.after_failed_start = os.environ.pop(AFTER_FAILED_START, "") == "1"
        self.interactive = sys.stdin is not None and sys.stdin.isatty()

        self.lobbies = LobbyManager()
        self.info = ServerInfo(config, config.resolved_public_ip(), self.lobbies)
        self.plugins = PluginManager()
        self.game = Game(config, self.lobbies, self.plugins)
        self.hazel = HazelServer(self.game.on_connect, self.game.on_message, self.game.on_disconnect,
                                 debug=config.debug)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.transport: Optional[asyncio.BaseTransport] = None
        self.httpd = None
        self.console: Optional[Console] = None

        self.ngrok: Optional[Ngrok] = None
        self.tunnel: Optional[Tunnel] = None
        self.playit: Optional[Playit] = None
        self.playit_state = "off"  # ready, waiting, failed or off
        self.https_kind = ""  # "ngrok" or "cloudflare"
        self.https_changed = False  # ngrok gave a new address this time
        self.problems: List[Problem] = []

        self._starting_network = False
        self._reloading = False
        self._stopping = threading.Event()
        self._tunnel_lock = threading.Lock()

    # --- The whole start ---------------------------------------------------------

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        try:
            await self._run()
        finally:
            # Also when Ctrl+C is pressed in the middle of the start: stop playitd,
            # ngrok and cloudflared, and let the steps that are waiting give up.
            self.stop_everything()

    async def _run(self) -> None:
        config = self.config
        print_banner(config.server_name, __version__, [
            tr("Port: {port} (TCP + UDP)", port=config.port),
            tr("The Mac's address on the network: {ip}", ip=self.info.public_ip),
            tr("Settings: {file}", file=CONFIG_FILE.name),
            tr("Stop the server with Ctrl+C"),
        ], copyright_line=__copyright__)
        print()
        say(paint(tr("Starting the server, one part at a time:"), LIGHT_BLUE, bold=True))
        if self.after_failed_start:
            say(tr("(This is the second try after a problem, see above.)"))

        steps = [
            (tr("Plugins"), self.step_plugins),
            (tr("Game server"), self.step_game_server),
            (tr("Join page"), self.step_join_page),
            ("playit.gg", self.step_playit),
            (tr("HTTPS address"), self.step_https),
        ]
        local_ok = True
        for number, (title, step) in enumerate(steps, 1):
            print_step(number, len(steps), title)
            self._starting_network = number >= 4
            try:
                ok = await step()
            finally:
                self._starting_network = False
            if self._stopping.is_set():
                return
            if number <= 3 and not ok:
                local_ok = False
            if self.problems and self._should_reboot():
                await self._reboot_after_problem()
                return
            if not local_ok:
                break  # without the game server and the join page nothing else works

        if self.problems:
            self.show_problems(server_works=local_ok)
        if local_ok:
            self.show_online()
            self.plugins.fire("on_server_started")

        self.start_console()
        cleanup = asyncio.ensure_future(self.game.cleanup_loop())
        try:
            if local_ok:
                await self.hazel.maintenance_loop()
            else:
                await self.loop.create_future()  # wait for /reboot or /stop
        finally:
            cleanup.cancel()

    def _should_reboot(self) -> bool:
        return not self.after_failed_start and any(p.retry_helps for p in self.problems)

    async def _reboot_after_problem(self) -> None:
        lines = []
        for problem in self.problems:
            lines.append(f"{paint(problem.part, LIGHT_BLUE, bold=True)}: {problem.text}")
        lines += ["", tr("Restarting the server automatically ({reboot})...",
                         reboot=paint("/reboot", LIGHT_BLUE, bold=True))]
        print_box(tr("SOMETHING WENT WRONG WHILE STARTING"), lines)
        await asyncio.sleep(2)
        self.reboot(after_failure=True)

    # --- Step 1: plugins ---------------------------------------------------------

    async def step_plugins(self) -> bool:
        self.plugins.enabled = self.config.plugins
        if not self.config.plugins:
            print_step_result("off", tr("Plugins are turned off in config.json."))
            return True
        self.plugins.load_all()
        summary = self.plugins.summary()
        print_step_result("warn" if self.plugins.failed else "ok", summary[0].rstrip("."))
        for line in summary[1:]:
            if line:
                print_step_detail(line[2:] if line.startswith("  ") else line)
        self.plugins.log_failures()
        return True  # a broken plugin is shown, but the server starts anyway

    # --- Step 2: the game server (UDP) -------------------------------------------

    async def step_game_server(self) -> bool:
        config = self.config
        try:
            self.transport, _ = await self.loop.create_datagram_endpoint(
                lambda: self.hazel, local_addr=(config.listen_ip, config.port)
            )
        except OSError as error:
            return self._failed(tr("Game server"), tr("Could not start the UDP server on port {port}: {error}",
                                                     port=config.port, error=error),
                                tips=[tr("Is the server already running in another window? Close it first.")])
        target = (self._local_ip(), config.port)
        arrived = await self.loop.run_in_executor(None, self.hazel.probe, target, 3.0, 0.5)
        if not arrived:
            return self._failed(tr("Game server"), tr("The game server didn't answer a test packet."))
        print_step_result("ok", tr("Ready on UDP port {port}", port=config.port))
        return True

    def _local_ip(self) -> str:
        ip = self.config.listen_ip
        return "127.0.0.1" if ip in ("", "0.0.0.0", "::") else ip

    # --- Step 3: the join page (HTTP) --------------------------------------------

    async def step_join_page(self) -> bool:
        config = self.config
        try:
            self.httpd = start_matchmaker(self.info)
        except OSError as error:
            return self._failed(tr("Join page"), tr("Could not start the HTTP server on port {port}: {error}",
                                                   port=config.port, error=error),
                                tips=[tr("Is the server already running in another window? Close it first.")])
        url = f"http://{self._local_ip()}:{config.port}/ping"
        answer = await self.loop.run_in_executor(None, _fetch, url, 5.0)
        if answer != "pong":
            return self._failed(tr("Join page"), tr("The join page didn't answer on this Mac."))
        print_step_result("ok", tr("Ready at {url}", url=f"http://localhost:{config.port}"))
        return True

    # --- Step 4: playit.gg ---------------------------------------------------------

    async def step_playit(self, keep: bool = False) -> bool:
        config = self.config
        if keep and self.playit is not None:
            print_step_result("ok", tr("{address} (works, kept running so that nobody is disconnected)",
                                       address=self.playit.address))
            return True
        self.playit_state = "off"
        if not config.playit:
            print_step_result("off", tr("Turned off in config.json, only your wifi can play."))
            return True
        binary = find_playitd(config.playit_path)
        if not binary:
            print_step_result("warn", tr("playit/playitd-macos is missing, only your wifi can play."))
            print_step_detail(tr("See \"Play with friends from home\" in README.md for how to fix that."))
            return True
        if "playit" in self.skipped:
            print_step_result("off", tr("Skipped for now, only your wifi can play."))
            return True

        playit = Playit(binary, config.port, print_box, on_change=self._playit_changed)
        self.playit = playit
        # The first time playit.gg shows a link and waits for the host. That only
        # works while the start is going on (later the commands read the keyboard).
        wait_for_host = self._wait_for_host if self.interactive and self.console is None else None
        try:
            ok = await self.loop.run_in_executor(None, playit.start, PLAYIT_TIMEOUT, wait_for_host)
        except Exception as error:  # playit must never crash the server
            log.exception("Something went wrong with playit.gg. The server still works on your wifi.")
            ok = False
            playit.problem = str(error)
        if self._stopping.is_set():
            return False
        if not ok:
            self.playit_state = "waiting" if playit.needs_you else "failed"
            tips = []
            if not Playit.has_key():
                tips.append(tr("Type {reboot} to connect the server to playit.gg.",
                               reboot=paint("/reboot", LIGHT_BLUE, bold=True)))
            elif playit.key_broken:
                tips.append(tr("Delete playit-key.txt and restart the server to approve it again."))
            elif playit.needs_you:
                tips.append(tr("Do what the playit.gg box above says. The server notices by itself when it's done."))
            else:
                tips.append(tr("Check the internet connection, then try {reload}.",
                               reload=paint("/reload", LIGHT_BLUE, bold=True)))
            return self._failed("playit.gg", playit.problem or tr("playit.gg didn't start."),
                                retry_helps=not playit.needs_you, tips=tips, wifi_still_works=True)

        ip, port = playit.endpoint
        self.info.set_playit(playit.address, ip, port)
        self.playit_state = "ready"
        arrived = await self.loop.run_in_executor(None, self.hazel.probe, (ip, port), PROBE_SECONDS, 1.5)
        if not arrived and not self._stopping.is_set():
            # Usually playitd just hasn't finished signing in to playit.gg (for
            # example right after a restart). Starting it once more often helps.
            print_step_detail(tr("The test packet didn't come through. Restarting playit.gg's program once..."))
            if await self.loop.run_in_executor(None, playit.restart_agent):
                arrived = await self.loop.run_in_executor(None, self.hazel.probe, (ip, port), PROBE_AFTER_RESTART, 1.5)
        if self._stopping.is_set():
            return False
        if arrived:
            print_step_result("ok", tr("{address} (a test packet came through)", address=playit.address))
        else:
            print_step_result("warn", tr("{address} (a test packet didn't come through, but it may still work)",
                                         address=playit.address))
        return True

    def _playit_changed(self, address: str, ip: str, port: int) -> None:
        """playit.gg became ready later, or got a new address."""
        self.info.set_playit(address, ip, port)
        was_ready = self.playit_state == "ready"
        self.playit_state = "ready"
        if was_ready:
            log.info("The playit address is now %s (%s:%d)", address, ip, port)
        elif not self._starting_network:
            print_box(tr("PLAYIT IS READY!"), [
                tr("Friends can now play with you from their own homes,"),
                tr("on wifi or mobile data."),
                "",
                tr("The game's address through playit.gg: {address}", address=address),
                tr("That address is the same every time the server starts."),
            ])

    # --- Step 5: HTTPS (ngrok, otherwise Cloudflare) -------------------------------

    async def step_https(self) -> bool:
        config = self.config
        self.https_kind = ""
        if not config.https_tunnel:
            print_step_result("off", tr("Turned off in config.json (Among Us needs HTTPS to connect from other devices)."))
            return True
        if config.ngrok and "ngrok" not in self.skipped:
            url, problem = await self._start_ngrok()
            if url:
                self.https_kind = "ngrok"
                self._https_ready(url)
                print_step_result("ok", tr("{url} (ngrok)", url=paint(url, LIGHT_BLUE)))
                return True
            if problem is not None:
                ok = self._failed(tr("HTTPS address"), problem,
                                  tips=[tr("Check the internet connection, then try {reload}.",
                                           reload=paint("/reload", LIGHT_BLUE, bold=True))])
                if self._should_reboot():
                    return ok
                print_step_detail(tr("Trying Cloudflare instead..."))

        url, problem = await self._start_cloudflare()
        if url:
            self.https_kind = "cloudflare"
            self._https_ready(url)
            note = tr("the address changes every start")
            print_step_result("ok", tr("{url} (Cloudflare, {note})", url=paint(url, LIGHT_BLUE), note=note))
            return True
        missing = find_cloudflared(config.cloudflared_path) is None
        tips = [tr("Double-click get-cloudflared.command once, then try {reload}.",
                   reload=paint("/reload", LIGHT_BLUE, bold=True))] if missing else [
            tr("Check the internet connection, then try {reload}.", reload=paint("/reload", LIGHT_BLUE, bold=True))]
        return self._failed(tr("HTTPS address"), problem or tr("There is no HTTPS address."),
                            retry_helps=not missing, tips=tips, wifi_still_works=True)

    async def _start_ngrok(self):
        """Returns (url, None), (None, problem) or (None, None) if the host skipped ngrok."""
        ready = threading.Event()
        failed = threading.Event()
        result = {}

        def on_ready(url: str, changed: bool) -> None:
            if self._starting_network:
                result["url"], result["changed"] = url, changed
                ready.set()
            else:
                self._announce_https(url, fixed=True, changed=changed)

        def on_failed() -> None:
            if self._starting_network:
                failed.set()
            else:
                self._start_cloudflare_backup()  # ngrok stopped working while the server runs

        ngrok = Ngrok(self.config.ngrok_path, self.config.port, on_ready, on_failed, print_box,
                      ask=self.console.ask if self.console else None)
        self.ngrok = ngrok
        ngrok.start()

        def wait() -> None:
            deadline = time.monotonic() + NGROK_TIMEOUT
            while not ready.is_set() and not failed.is_set() and not self._stopping.is_set():
                if ngrok.waiting_for_user:
                    deadline = time.monotonic() + NGROK_TIMEOUT  # the clock starts when the key is pasted
                if time.monotonic() > deadline:
                    return
                ready.wait(0.3)

        await self.loop.run_in_executor(None, wait)
        if ready.is_set():
            self.https_changed = bool(result.get("changed"))
            return result["url"], None
        if ngrok.skipped:
            self.skipped.add("ngrok")
            return None, None
        if not failed.is_set() and not self._stopping.is_set():
            log.warning("ngrok didn't get going in %d seconds.", NGROK_TIMEOUT)
        return None, tr("ngrok didn't work (see the messages above).")

    async def _start_cloudflare(self):
        """Returns (url, None) or (None, problem)."""
        binary = find_cloudflared(self.config.cloudflared_path)
        if not binary:
            return None, tr("cloudflared is missing, so there is no HTTPS address from Cloudflare.")
        ready = threading.Event()
        failed = threading.Event()
        result = {}

        def on_ready(url: str) -> None:
            if self._starting_network:
                result["url"] = url
                ready.set()
            else:
                self._announce_https(url, fixed=False)

        def on_failed(reason: str) -> None:
            result["problem"] = reason
            failed.set()

        tunnel = Tunnel(binary, self.config.port, on_ready, on_failed)
        try:
            tunnel.start()
        except OSError as error:
            return None, tr("Could not start cloudflared: {error}", error=error)
        self.tunnel = tunnel

        def wait() -> None:
            deadline = time.monotonic() + CLOUDFLARE_TIMEOUT
            while not ready.is_set() and not failed.is_set() and not self._stopping.is_set():
                if time.monotonic() > deadline:
                    return
                ready.wait(0.3)

        await self.loop.run_in_executor(None, wait)
        if ready.is_set():
            return result["url"], None
        return None, result.get("problem") or tr("Cloudflare didn't give an address in time.")

    def _start_cloudflare_backup(self) -> None:
        """While the server runs: ngrok stopped working, so Cloudflare takes over."""
        with self._tunnel_lock:
            if self.tunnel is not None:
                return
            binary = find_cloudflared(self.config.cloudflared_path)
            if not binary:
                log.warning("cloudflared is missing, so there is no HTTPS address from Cloudflare.")
                return
            tunnel = Tunnel(binary, self.config.port, lambda url: self._announce_https(url, fixed=False))
            try:
                tunnel.start()
            except OSError as error:
                log.error("Could not start cloudflared: %s", error)
                return
            self.tunnel = tunnel

    def _https_ready(self, url: str) -> None:
        self.info.tunnel_url = url
        if self.https_kind == "ngrok":
            self.info.fixed_url = url
        write_region_file(self.info)

    def _announce_https(self, url: str, fixed: bool, changed: bool = False) -> None:
        """An HTTPS address that works after the start (ngrok came back, or Cloudflare took over)."""
        if not fixed and self.info.fixed_url and self.ngrok is not None and self.ngrok.url:
            log.info("The Cloudflare address %s works too, but use the ngrok address.", url)
            return
        self.https_kind = "ngrok" if fixed else "cloudflare"
        self.info.tunnel_url = url
        if fixed:
            self.info.fixed_url = url
        write_region_file(self.info)
        lines = [
            tr("Open this address on the device that's going to play:"),
            f"    {paint(url, LIGHT_BLUE, bold=True)}",
            "",
        ]
        if not fixed:
            lines.append(tr("Note: the address changes every time the server restarts."))
        elif changed:
            lines += [
                tr("NOTE: the address is new! Everyone needs to add the server again,"),
                tr("then it stays the same every time."),
            ]
        else:
            lines += [
                tr("The address is the same every time the server starts, so anyone"),
                tr("who already added the server doesn't need to do it again."),
            ]
        with output_lock():
            print_box(tr("HTTPS IS READY!"), lines)
            if self.config.terminal_qr:
                show_qr(url)

    # --- Helpers for the steps ---------------------------------------------------

    def _failed(self, part: str, text: str, retry_helps: bool = True, tips: Optional[List[str]] = None,
                wifi_still_works: bool = False) -> bool:
        print_step_result("failed", text)
        self.problems.append(Problem(part, text, retry_helps, tips or []))
        return wifi_still_works

    def _wait_for_host(self, seconds: float) -> bool:
        """For playit.gg's first-time link: waits, True if the host pressed Enter to skip."""
        if self._stopping.is_set():
            return True
        return wait_for_enter(seconds)

    # --- The boxes at the end ------------------------------------------------------

    def show_problems(self, after_command: bool = False, server_works: bool = True) -> None:
        lines = []
        for problem in self.problems:
            lines.append(f"{paint(problem.part, LIGHT_BLUE, bold=True)}: {paint(problem.text, ERROR)}")
            for tip in problem.tips:
                lines.append(f"    {tip}")
        lines.append("")
        if server_works:
            lines += [
                tr("The rest of the server works as well as it can."),
                tr("When you have fixed it, type {reload} (playit.gg and HTTPS)",
                   reload=paint("/reload", LIGHT_BLUE, bold=True)),
                tr("or {reboot} (the whole server) to try again.", reboot=paint("/reboot", LIGHT_BLUE, bold=True)),
            ]
        else:
            lines += [
                tr("The server can't work without this part."),
                tr("When you have fixed it, type {reboot} to try again (or {stop} to stop).",
                   reboot=paint("/reboot", LIGHT_BLUE, bold=True), stop=paint("/stop", LIGHT_BLUE, bold=True)),
            ]
        if not after_command:
            lines += [tr("More help: \"Troubleshooting\" in README.md.")]
        print_box(tr("SOMETHING ISN'T WORKING"), lines)

    def show_online(self) -> None:
        info, config = self.info, self.config
        name = paint(config.server_name, PURPLE, bold=True)
        lines = [
            tr("{name} is up and running. Go ahead and join on your phone,", name=name),
            tr("tablet or computer!"),
            "",
        ]
        if info.tunnel_url:
            lines.append(tr("Join page: {url}", url=paint(info.tunnel_url, LIGHT_BLUE, bold=True)))
            lines.append(tr("Open it on the device that's going to play, or scan the QR code below."))
            if self.https_kind == "ngrok":
                if self.https_changed:
                    lines.append(tr("NOTE: the address is new! Everyone needs to add the server again,"))
                    lines.append(tr("then it stays the same every time."))
                lines.append(tr("(ngrok shows a warning page in the browser: press Visit Site.)"))
            else:
                lines.append(tr("Note: the address changes every time the server restarts."))
        else:
            lines.append(tr("Join page: {url} (HTTPS isn't ready yet)", url=f"http://localhost:{config.port}"))
        lines.append("")
        if self.playit_state == "ready":
            lines.append(tr("Friends can join from anywhere, on wifi or mobile data."))
        elif self.playit_state == "waiting":
            lines.append(tr("Friends at home can join once playit.gg is set up (see the box above)."))
        elif self.playit_state == "failed":
            lines.append(tr("playit.gg isn't ready yet, so only devices on your wifi can join for now."))
        else:
            lines.append(tr("Only devices on your wifi can join (playit.gg is off)."))
        lines += ["", tr("Use {help} to get a list of useful commands.", help=paint("/help", LIGHT_BLUE, bold=True))]
        with output_lock():
            print_box(tr("SERVER IS ONLINE!"), lines)
            if info.tunnel_url and config.terminal_qr:
                show_qr(info.tunnel_url)

    # --- playit.gg and HTTPS again: /reload ------------------------------------------

    async def start_network(self, keep_playit: bool = False) -> None:
        """Steps 4 and 5 (playit.gg and HTTPS), for /reload."""
        self._starting_network = True
        try:
            print_step(1, 2, "playit.gg")
            await self.step_playit(keep=keep_playit)
            if self._stopping.is_set():
                return
            print_step(2, 2, tr("HTTPS address"))
            await self.step_https()
        finally:
            self._starting_network = False

    def stop_network(self, keep_playit: bool = False) -> None:
        """Stops playit.gg and the HTTPS address. keep_playit: only the HTTPS address."""
        parts = [self.ngrok, self.tunnel] + ([] if keep_playit else [self.playit])
        for part in parts:
            if part is not None:
                part.stop()
        self.ngrok = self.tunnel = None
        self.info.tunnel_url = ""
        self.info.fixed_url = ""
        self.https_kind = ""
        if not keep_playit:
            self.playit = None
            self.info.playit_endpoint = None
            self.info.playit_address = ""
            self.playit_state = "off"

    def playit_works(self) -> bool:
        """True if playitd runs and a test packet comes through its address. Blocks a few seconds at most."""
        playit = self.playit
        if playit is None or not playit.is_running() or playit.endpoint is None or self.playit_state != "ready":
            return False
        return self.hazel.probe(playit.endpoint, 5, 0.5)

    async def reload(self, keep_playit: bool = False) -> None:
        """
        /reload: starts the HTTPS address again, and playit.gg too unless
        keep_playit (then friends who play from home stay connected).
        """
        if self._reloading:
            say(tr("A reload is already going on."))
            return
        self._reloading = True
        try:
            say(paint(tr("Reloading playit.gg and the HTTPS address, one at a time..."), LIGHT_BLUE, bold=True))
            self.stop_network(keep_playit)
            await asyncio.sleep(2)  # ngrok's free account allows one connection: let the old one close
            self.problems = []
            await self.start_network(keep_playit)
            if self._stopping.is_set():
                return
            if self.problems:
                self.show_problems(after_command=True)
            self.show_online()
        finally:
            self._reloading = False

    # --- The whole server again: /reboot ---------------------------------------------

    def reboot(self, after_failure: bool = False) -> None:
        """Stops everything and starts the server again in the same window."""
        say(tr("Restarting the server..."))
        for connection in list(self.hazel.connections.values()):
            try:
                connection.disconnect(DisconnectReason.CUSTOM, "The server is restarting. Join again in a moment.")
            except Exception:
                pass
        self.stop_everything()
        restore_terminal()
        sys.stdout.flush()
        env = dict(os.environ)
        if after_failure:
            env[AFTER_FAILED_START] = "1"
        else:
            env.pop(AFTER_FAILED_START, None)
        try:
            os.chdir(PROJECT_DIR)
            os.execve(sys.executable, [sys.executable, "-m", "server"], env)
        except OSError as error:
            log.error("Could not restart the server: %s. Start it again with start.command.", error)
            os.kill(os.getpid(), signal.SIGINT)

    def stop_everything(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self.stop_network()
        if self.transport is not None:
            self.transport.close()
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        restore_terminal()

    # --- Commands -----------------------------------------------------------------

    def start_console(self) -> None:
        if not self.interactive or self.console is not None:
            return
        self.console = Console(input_line=self.config.input_line)
        add_commands(self)
        if self.ngrok is not None:
            self.ngrok.ask = self.console.ask
        self.console.start()


def _fetch(url: str, timeout: float) -> str:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except OSError as error:
        log.debug("Could not fetch %s: %s", url, error)
        return ""


def write_region_file(info: ServerInfo) -> None:
    """regionInfo.json in the project folder, for PC (the same file the join page gives)."""
    if not info.tunnel_url:
        return
    region_file = PROJECT_DIR / "regionInfo.json"
    try:
        region_file.write_text(region_info_json(info.config.server_name, info.tunnel_url, 443), encoding="utf-8")
    except OSError as error:
        log.warning("Could not save %s: %s", region_file.name, error)


def show_qr(url: str) -> None:
    try:
        qr = QrCode.create(url, "M").terminal(border=3)
    except ValueError:
        return
    with output_lock():
        print(f"  {tr('Scan with your phone camera to open the page:')}", flush=True)
        print(qr, flush=True)


def add_commands(server: Server) -> None:
    """The commands you can type in the Terminal window (see /help)."""
    console, info, config, loop = server.console, server.info, server.config, server.loop
    assert console is not None and loop is not None

    def usage(text: str) -> None:
        say(tr("Usage: {command}", command=paint(text, LIGHT_BLUE, bold=True)))

    def change_name(argument: str) -> None:
        if not argument:
            usage(tr("/changeservername <new name>"))
            return
        name, problem = clean_name(argument)
        if problem:
            say(paint(problem, ERROR))
            return
        if name == config.server_name:
            say(tr("The server is already called {name}.", name=paint(name, PURPLE, bold=True)))
            return
        old = config.server_name
        config.server_name = name
        forget_pending("server_name")
        save_config(config)
        write_region_file(info)
        success(tr("Name updated!"))
        say(tr("The server is now called {name}.", name=paint(name, PURPLE, bold=True)))
        say(tr("Friends who already added the server see the old name until they add it"))
        say(tr("again from the join page. Joining still works either way."))
        log.info("The server is now called %s (was %s)", name, old)

    def change_language(argument: str) -> None:
        names = " / ".join(i18n.LANGUAGES)
        if not argument:
            usage(f"/language <{names}>")
            return
        if argument.strip().lower() not in ("en", "sv", "english", "swedish", "engelska", "svenska", "se"):
            say(paint(tr("Unknown language {language}.", language=argument), ERROR) + f" ({names})")
            return
        code = i18n.set_language(argument)
        config.language = i18n.language_name(code)
        forget_pending("language")
        save_config(config)
        success(tr("Language updated!"))

    def games(_argument: str) -> None:
        def show() -> None:
            lobbies = [lobby for lobby in info.lobbies.all() if lobby.host is not None]
            if not lobbies:
                print_box(tr("GAMES"), [tr("No games right now. Press Create Game in Among Us to start one.")])
                return
            lines = []
            for lobby in lobbies:
                state = paint(tr("playing"), PLAYING) if lobby.is_started else paint(tr("in the lobby"), GREEN)
                lines.append(tr(
                    "{code}  {players}/{max} players  {map}  host {host}  ({state})",
                    code=paint(lobby.code, LIGHT_BLUE, bold=True), players=len(lobby.players),
                    max=lobby.options.max_players, map=lobby.map_name, host=lobby.host_name, state=state,
                ))
            print_box(tr("GAMES"), lines)
        loop.call_soon_threadsafe(show)

    def address(_argument: str) -> None:
        lines = []
        if info.tunnel_url:
            lines.append(tr("Join page:   {url}", url=paint(info.tunnel_url, LIGHT_BLUE, bold=True)))
        else:
            lines.append(tr("Join page:   HTTPS isn't ready yet"))
        lines.append(tr("On this Mac: {url}", url=f"http://localhost:{config.port}"))
        if info.playit_address:
            lines.append(tr("playit.gg:   {address}", address=info.playit_address))
        with output_lock():
            print_box(tr("ADDRESSES"), lines)
            if info.tunnel_url:
                show_qr(info.tunnel_url)

    def say_to_all(argument: str) -> None:
        if not argument:
            usage(tr("/say <message>"))
            return

        def send() -> None:
            sent = sum(1 for lobby in info.lobbies.all() if lobby.send_chat(f"[Server] {argument}"))
            if sent == 1:
                success(tr("Sent to 1 game."))
            elif sent:
                success(tr("Sent to {count} games.", count=sent))
            else:
                say(tr("There are no games to send to right now."))
        loop.call_soon_threadsafe(send)

    def plays_from_home(lobby) -> bool:
        """Someone in the room plays through playit.gg (playitd sends their packets from this Mac)."""
        return any(getattr(player.connection, "address", ("",))[0] in LOOPBACK for player in lobby.players.values())

    def online_rooms(from_home: bool = False) -> List[str]:
        return [lobby.code for lobby in info.lobbies.all()
                if lobby.players and (not from_home or plays_from_home(lobby))]

    def warn_first(rebooting: bool, codes: List[str], action: Callable[[], None]) -> None:
        """Asks "Do you wish to proceed?" first, but only if a room would be disconnected."""
        if not codes:
            action()
            return
        console.confirm(action)
        rooms = ", ".join(paint(code, LIGHT_BLUE, bold=True) for code in codes)
        if rebooting:
            consequence = tr("Rebooting will disconnect all online rooms.")
        else:
            consequence = tr("Reloading restarts playit.gg, which disconnects everyone who plays from home.")
        print_box(tr("WARNING"), [
            tr("One or more online rooms are playing right now: {rooms}", rooms=rooms),
            consequence,
            "",
            tr("Do you wish to proceed? Type {yes} or {no}.",
               yes=paint("yes", LIGHT_BLUE, bold=True), no=paint("no", LIGHT_BLUE, bold=True)),
        ])

    def reload(_argument: str) -> None:
        async def check_first() -> None:
            # If playit.gg works it keeps running, and then nobody is disconnected.
            # (If playitd isn't running, nobody plays through it either.)
            keep = await loop.run_in_executor(None, server.playit_works)
            running = server.playit is not None and server.playit.is_running()
            codes = online_rooms(from_home=True) if running and not keep else []
            warn_first(False, codes, lambda: asyncio.run_coroutine_threadsafe(server.reload(keep_playit=keep), loop))
        asyncio.run_coroutine_threadsafe(check_first(), loop)

    def reboot(_argument: str) -> None:
        warn_first(True, online_rooms(), lambda: loop.call_soon_threadsafe(server.reboot))

    def stop(_argument: str) -> None:
        say(tr("Stopping the server..."))
        os.kill(os.getpid(), signal.SIGINT)

    console.add("changeservername", "/changeservername <name>", "Give the server a new name", change_name)
    console.add("language", "/language <English|Swedish>", "Change the language in this window", change_language)
    console.add("games", "/games", "List the games on the server and their codes", games)
    console.add("address", "/address", "Show the join page address and QR code again", address)
    console.add("say", "/say <message>", "Send a chat message to everyone in every game", say_to_all)
    add_settings_commands(console, config)
    console.add("reload", "/reload", "Start the HTTPS address again, and playit.gg if it doesn't work", reload)
    console.add("reboot", "/reboot", "Restart the whole server (everyone is disconnected)", reboot)
    console.add("stop", "/stop", "Stop the server (same as Ctrl+C)", stop)
