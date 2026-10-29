"""
The join page that is shown when you open the server's address in a browser.

The page is always in English and has three steps:
  1. Add the server to Among Us (only the first time). The page notices if
     you have an iPhone/iPad, Android, PC or Mac and shows the right steps.
  2. Play: a list of the games on the server with their codes. The list is
     fetched from /games.json and updates by itself.
  3. Invite friends: a QR code and a ready-made message to send.

If you open the page on the Mac (http://localhost:22023) it shows the QR
code and the address the friends should use instead.
"""

from __future__ import annotations

import json
from functools import lru_cache
from html import escape
from string import Template

from .qrcode import QrCode
from .terminal import full_name
from .region import app_link

PC_FOLDER = r"%USERPROFILE%\AppData\LocalLow\Innersloth\Among Us"


@lru_cache(maxsize=8)
def qr_svg(url: str) -> str:
    return QrCode.create(url, "M").svg()


PAGE = Template(
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>$heading</title>
<style>
  :root {
    --space: #141c33;
    --hull: #1f2a4a;
    --hull-edge: #34436f;
    --rivet: #9aa7cf;
    --text: #f2f4ff;
    --visor: #8fd8ee;
    --task: #f5d547;
    --round: ui-rounded, "SF Pro Rounded", "Arial Rounded MT Bold", "Nunito", system-ui, sans-serif;
    --body: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  html { -webkit-text-size-adjust: 100%; }
  body { margin: 0; background: var(--space); color: var(--text); font: 16px/1.5 var(--body); }
  main { max-width: 34rem; margin: 0 auto; padding: 28px 16px 40px; }
  a { color: var(--visor); }
  :focus-visible { outline: 3px solid var(--visor); outline-offset: 2px; }

  header { margin-bottom: 22px; }
  h1 { font: 800 clamp(1.6rem, 7vw, 2.1rem)/1.1 var(--round); margin: 0 0 8px; letter-spacing: -.01em; }
  h1 .server-name { color: #c4adff; }
  .status { display: flex; align-items: center; gap: 8px; margin: 0; color: var(--rivet); }
  .status::before { content: ""; width: 10px; height: 10px; border-radius: 50%;
                    background: #5fd77a; box-shadow: 0 0 0 4px rgba(95, 215, 122, .18); }

  section { background: var(--hull); border: 2px solid var(--hull-edge); border-radius: 18px;
            padding: 18px 18px 20px; margin-bottom: 16px; }
  h2 { font: 700 1.25rem/1.2 var(--round); margin: 0 0 12px; display: flex; align-items: baseline; gap: 10px; }
  h2 .num { flex: none; width: 1.7em; height: 1.7em; border-radius: 50%; display: inline-grid;
            place-items: center; background: var(--space); border: 2px solid var(--hull-edge);
            font-size: .85em; transform: translateY(-1px); }
  .sub { margin: -6px 0 14px; color: var(--rivet); font-size: .93rem; }
  p { margin: 0 0 12px; }
  .muted { color: var(--rivet); font-size: .93rem; }
  code { font: .9em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: nowrap;
         background: var(--space); border-radius: 6px; padding: 1px 6px; }
  kbd { font: 600 .85em var(--body); background: var(--space); border-radius: 6px; padding: 1px 7px;
        border: 1px solid var(--hull-edge); border-bottom-width: 3px; white-space: nowrap; }

  .tabs { display: flex; gap: 4px; padding: 4px; background: var(--space); border-radius: 12px;
          margin-bottom: 16px; overflow-x: auto; }
  .tabs button { flex: 1 0 auto; border: 0; border-radius: 9px; padding: 8px 10px; cursor: pointer;
                 background: transparent; color: var(--rivet); font: 600 .95rem var(--body); }
  .tabs button[aria-selected="true"] { background: var(--hull-edge); color: var(--text); }

  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; cursor: pointer;
         border: 2px solid var(--hull-edge); background: var(--space); color: var(--text); text-decoration: none;
         border-radius: 12px; padding: 10px 14px; font: 600 1rem var(--body); }
  .btn.wide { width: 100%; }
  .btn.add { margin: 2px 0 14px; padding: 12px 14px; }
  .btn.done { border-color: #5fd77a; }
  ol.steps { margin: 0 0 12px; padding-left: 1.4em; }
  ol.steps li { margin-bottom: 10px; padding-left: 4px; }
  ol.steps li::marker { font-weight: 700; color: var(--rivet); }
  .then { border-top: 2px dashed var(--hull-edge); padding-top: 14px; margin: 4px 0 0; }

  #games { list-style: none; margin: 0 0 12px; padding: 0; }
  .game { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; align-items: center;
          padding: 12px 14px; background: var(--space); border-radius: 14px; margin-bottom: 8px; }
  .code { font: 800 1.9rem/1 var(--round); letter-spacing: .12em; }
  .who { grid-column: 1; color: var(--rivet); font-size: .92rem; }
  .side { grid-column: 2; grid-row: 1 / span 2; display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
  .count { font: 700 1rem var(--round); }
  .state { font-size: .8rem; padding: 2px 8px; border-radius: 999px; background: var(--hull-edge); }
  .state.on { background: var(--task); color: #2b2400; }
  .game .actions { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
  .game .actions .btn { padding: 6px 10px; font-size: .9rem; white-space: nowrap; }
  .empty { color: var(--rivet); }

  .invite { display: grid; grid-template-columns: 132px 1fr; gap: 14px; align-items: center; margin-bottom: 12px; }
  .qr { background: #fff; border-radius: 12px; padding: 6px; line-height: 0; }
  .qr svg { width: 100%; height: auto; }
  textarea { width: 100%; min-height: 9.5em; resize: vertical; border-radius: 12px; border: 2px solid var(--hull-edge);
             background: var(--space); color: var(--text); font: .95rem/1.45 var(--body); padding: 10px 12px; margin-bottom: 10px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  .row .btn { flex: 1 1 auto; }
  .host-link { font: 700 1.05rem var(--round); word-break: break-all; }
  .host-qr { max-width: 260px; margin: 6px 0 14px; }
  .warn { border-color: var(--task); }
  footer { color: var(--rivet); font-size: .88rem; padding: 0 4px; }
  footer code { white-space: normal; word-break: break-all; }
  footer p { margin-bottom: 6px; }
  @media (max-width: 380px) {
    .invite { grid-template-columns: 1fr; } .qr { max-width: 200px; }
    .tabs button { padding: 8px 5px; font-size: .86rem; }
    .code { font-size: 1.6rem; }
  }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<main>
  <header>
    <h1>$heading_html</h1>
    <p class="status">The server is online$status_extra</p>
  </header>
$content
  <footer>
    $footer
  </footer>
</main>
<script>
$script
</script>
</body>
</html>
"""
)

ADD_SECTION = Template(
    """
  <section aria-labelledby="add-title">
    <h2 id="add-title"><span class="num">1</span> Add the server</h2>
    <p class="sub">Only needed the first time.</p>
    <div class="tabs" role="tablist" aria-label="Which device do you play on?" hidden>
      <button role="tab" data-dev="ios">iPhone / iPad</button>
      <button role="tab" data-dev="android">Android</button>
      <button role="tab" data-dev="pc">PC</button>
      <button role="tab" data-dev="mac">Mac</button>
    </div>

    <div class="dev" data-dev="ios">
      <p class="js-only-title"><b>iPhone and iPad</b></p>
      <a class="btn wide add" href="$app_link">Add to Among Us</a>
      <ol class="steps">
        <li>Tap <b>Add to Among Us</b>. If the phone asks, choose <b>Open</b>.</li>
        <li>Among Us opens and the server <b>$name</b> is added.</li>
      </ol>
      <p class="muted">Nothing happens? Check that Among Us is installed and tap again.</p>
    </div>

    <div class="dev" data-dev="android">
      <p class="js-only-title"><b>Android</b></p>
      <a class="btn wide add" href="$app_link">Add to Among Us</a>
      <ol class="steps">
        <li>Tap <b>Add to Among Us</b>. If the phone asks which app, choose <b>Among Us</b>.</li>
        <li>Among Us opens and the server <b>$name</b> is added.</li>
      </ol>
      <p class="muted">Nothing happens? Check that Among Us is installed and tap again.</p>
    </div>

    <div class="dev" data-dev="pc">
      <p class="js-only-title"><b>PC (Steam, Epic, Microsoft Store)</b></p>
      <ol class="steps">
        <li><a class="btn wide" href="/regionInfo.json" download="regionInfo.json">Download regionInfo.json</a></li>
        <li><button class="btn wide" type="button" data-copy="$pc_folder">Copy the folder address</button></li>
        <li>Press <kbd>Windows</kbd> + <kbd>R</kbd>, paste with <kbd>Ctrl</kbd> + <kbd>V</kbd> and press <kbd>Enter</kbd>. The game's folder opens.</li>
        <li>Move <code>regionInfo.json</code> from the <b>Downloads</b> folder to the game's folder. Choose <b>Replace</b> if Windows asks.</li>
      </ol>
      <p class="muted">Is the file called <code>regionInfo (1).json</code>? Rename it to <code>regionInfo.json</code> before you move it.</p>
    </div>

    <div class="dev" data-dev="mac">
      <p class="js-only-title"><b>Mac</b></p>
      <p>Among Us on a Mac with Apple silicon (M1 or newer) works like on an iPhone:</p>
      <a class="btn wide add" href="$app_link">Add to Among Us</a>
      <p class="muted">Among Us isn't available on Macs with an Intel processor, but they can run the server.</p>
    </div>

    <p class="then">Then restart Among Us completely. The server is under the globe in the game's menu.</p>
  </section>
"""
)

PLAY_SECTION = Template(
    """
  <section aria-labelledby="play-title">
    <h2 id="play-title">$num Play</h2>
    <p>Choose <b>$name</b> under the globe in Among Us. Tap <b>Create Game</b> to be the host, or <b>Enter Code</b> and type in a code from here.</p>
    <ul id="games" aria-live="polite"></ul>
    <p class="empty" id="no-games">$empty_text</p>
  </section>
"""
)

INVITE_SECTION = Template(
    """
  <section aria-labelledby="invite-title">
    <h2 id="invite-title">$num Invite friends</h2>
    $qr_block
    <label for="msg" class="muted">Message to send</label>
    <textarea id="msg" spellcheck="false"></textarea>
    <div class="row">
      <button class="btn" type="button" data-copy-from="msg">Copy the message</button>
      <button class="btn" type="button" id="share" hidden>Share</button>
    </div>
  </section>
"""
)

HOST_SECTION = Template(
    """
  <section aria-labelledby="host-title">
    <h2 id="host-title">This is the Mac's own page</h2>
    <p>Among Us requires HTTPS, so phones and computers should use this address:</p>
    <p class="host-link"><a href="$tunnel_url">$tunnel_url</a></p>
    <div class="qr host-qr">$qr</div>
    <p class="muted">Scan the QR code with the phone camera, or send the address to your friends.</p>
  </section>
"""
)

NO_TUNNEL_SECTION = """
  <section class="warn">
    <h2>HTTPS isn't running yet</h2>
    <p>Among Us requires HTTPS when the game and the server don't run on the same computer.
       Wait until the server writes <b>HTTPS IS READY!</b> in the Terminal window and reload the page.</p>
    <p class="muted">Never happens? Double-click <code>get-cloudflared.command</code> once and restart the server.</p>
  </section>
"""

SCRIPT = """
(function () {
  "use strict";
  var config = __CONFIG__;
  document.documentElement.className += " js";

  // --- Which device? -----------------------------------------------------
  function guessDevice() {
    var ua = navigator.userAgent || "";
    if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "ios";
    if (/Android/.test(ua)) return "android";
    if (/Macintosh|Mac OS X/.test(ua)) return "mac";
    return "pc";
  }
  var tabs = document.querySelector(".tabs");
  function showDevice(dev) {
    document.querySelectorAll(".dev").forEach(function (el) { el.hidden = el.dataset.dev !== dev; });
    document.querySelectorAll(".tabs button").forEach(function (b) {
      b.setAttribute("aria-selected", b.dataset.dev === dev ? "true" : "false");
    });
  }
  if (tabs) {
    tabs.hidden = false;
    document.querySelectorAll(".js-only-title").forEach(function (el) { el.hidden = true; });
    tabs.addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (b) showDevice(b.dataset.dev);
    });
    showDevice(guessDevice());
  }

  // --- Copy -------------------------------------------------------------
  function copyText(text, button) {
    function done() {
      var old = button.textContent;
      button.textContent = "Copied!";
      button.classList.add("done");
      setTimeout(function () { button.textContent = old; button.classList.remove("done"); }, 1800);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(text); done(); });
    } else {
      fallback(text);
      done();
    }
  }
  function fallback(text) {
    var t = document.createElement("textarea");
    t.value = text;
    t.setAttribute("readonly", "");
    t.style.position = "fixed";
    t.style.opacity = "0";
    document.body.appendChild(t);
    t.select();
    try { document.execCommand("copy"); } catch (err) {}
    document.body.removeChild(t);
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy], [data-copy-from]");
    if (!b) return;
    var text = b.dataset.copy;
    if (b.dataset.copyFrom) text = document.getElementById(b.dataset.copyFrom).value;
    copyText(text, b);
  });

  // --- The message to friends -------------------------------------------
  var msg = document.getElementById("msg");
  var chosenCode = "";
  function writeMessage() {
    if (!msg) return;
    var lines = [
      "Come and play Among Us with us on our own server, " + config.name + "!",
      "",
      "1. Open " + config.url + " and follow the steps for your phone or computer. It's only needed the first time." +
        (config.ngrok ? " If you get a warning page, tap Visit Site." : ""),
      "2. Choose " + config.name + " under the globe in Among Us.",
      chosenCode ? "3. Tap Enter Code and type " + chosenCode + "."
                 : "3. Tap Enter Code and type in the game code we send you."
    ];
    msg.value = lines.join("\\n");
    msg.style.height = "auto";
    msg.style.height = (msg.scrollHeight + 4) + "px";
  }
  writeMessage();
  var share = document.getElementById("share");
  if (share && navigator.share) {
    share.hidden = false;
    share.addEventListener("click", function () {
      navigator.share({ title: config.name, text: msg.value }).catch(function () {});
    });
  }

  // --- The games on the server -------------------------------------------
  var list = document.getElementById("games");
  var none = document.getElementById("no-games");
  function render(games) {
    list.textContent = "";
    none.hidden = games.length > 0;
    games.forEach(function (g) {
      var li = document.createElement("li");
      li.className = "game";
      var code = document.createElement("div");
      code.className = "code";
      code.textContent = g.code;
      var who = document.createElement("div");
      who.className = "who";
      who.textContent = g.host + " is hosting, " + g.map + (g.public ? ", public" : "");
      var side = document.createElement("div");
      side.className = "side";
      var count = document.createElement("span");
      count.className = "count";
      count.textContent = g.players + "/" + g.max;
      count.title = g.players + " of " + g.max + " players";
      var state = document.createElement("span");
      state.className = "state" + (g.started ? " on" : "");
      state.textContent = g.started ? "Playing" : "In the lobby";
      side.appendChild(count);
      side.appendChild(state);
      var actions = document.createElement("div");
      actions.className = "actions";
      var copy = document.createElement("button");
      copy.className = "btn";
      copy.type = "button";
      copy.textContent = "Copy code";
      copy.dataset.copy = g.code;
      actions.appendChild(copy);
      if (msg) {
        var invite = document.createElement("button");
        invite.className = "btn";
        invite.type = "button";
        invite.textContent = chosenCode === g.code ? "In the message" : "Invite to this game";
        invite.addEventListener("click", function () {
          chosenCode = g.code;
          writeMessage();
          render(games);
          msg.scrollIntoView({ behavior: "smooth", block: "center" });
        });
        actions.appendChild(invite);
      }
      li.appendChild(code);
      li.appendChild(who);
      li.appendChild(side);
      li.appendChild(actions);
      list.appendChild(li);
    });
  }
  function refresh() {
    if (!list || !config.showGames) return;
    fetch("/games.json", { cache: "no-store", headers: { "ngrok-skip-browser-warning": "1" } })
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () {});
  }
  refresh();
  setInterval(refresh, 5000);
})();
"""


def _script(name: str, url: str, show_games: bool) -> str:
    config = {"name": name, "url": url, "ngrok": "ngrok" in url, "showGames": show_games}
    # </ in the text must not end the script tag
    return SCRIPT.replace("__CONFIG__", json.dumps(config).replace("</", "<\\/"))


def render(
    name: str,
    url: str,
    port: int,
    is_https: bool,
    tunnel_url: str = "",
    show_games: bool = True,
    playable_from_home: bool = False,
) -> str:
    """
    url = the address the viewer used. On the Mac itself (http://...)
    tunnel_url is the HTTPS address the friends should use.
    """
    invite_url = url if is_https else tunnel_url
    empty_text = (
        "No games right now. The host taps Create Game, then the code shows up here."
        if show_games else "Ask the host for the game code."
    )
    sections = []
    if is_https:
        sections.append(ADD_SECTION.substitute(
            app_link=escape(app_link(name, url, port)),
            name=escape(name),
            pc_folder=escape(PC_FOLDER),
        ))
        num = 2
    elif tunnel_url:
        sections.append(HOST_SECTION.substitute(tunnel_url=escape(tunnel_url), qr=qr_svg(tunnel_url)))
        num = 1
    else:
        sections.append(NO_TUNNEL_SECTION)
        num = 1
    def badge(n: int) -> str:
        return f'<span class="num">{n}</span>' if is_https else ""

    sections.append(PLAY_SECTION.substitute(num=badge(num), name=escape(name), empty_text=escape(empty_text)))
    if invite_url:
        qr_block = ""
        if is_https:  # on the Mac's own page the QR code is already at the top
            qr_block = (
                f'<div class="invite"><div class="qr">{qr_svg(invite_url)}</div>'
                "<p>Friends can scan the code with the phone camera, or you send the message below.</p></div>"
            )
        sections.append(INVITE_SECTION.substitute(num=badge(num + 1), qr_block=qr_block))

    footer = ""
    if is_https:
        footer = f"<p>Address: <code>{escape(url)}</code></p>"
        if "ngrok" in url:
            footer += "<p>Did ngrok show a warning page before you got here? That's only the first time, and the game isn't affected.</p>"

    heading = full_name(name, colored=False)
    heading_html = "Emergency Meeting"
    if heading != heading_html:
        heading_html += f' - <span class="server-name">{escape(name)}</span>'
    return PAGE.substitute(
        heading=escape(heading),
        heading_html=heading_html,
        status_extra=", also for friends at home" if playable_from_home else "",
        content="".join(sections),
        footer=footer,
        script=_script(name, invite_url or url, show_games),
    )


def games_json(lobbies, show_games: bool) -> list:
    """The games on the server, for the list on the page."""
    if not show_games:
        return []
    games = []
    for lobby in lobbies:
        if lobby.host is None:
            continue
        games.append({
            "code": lobby.code,
            "host": lobby.host_name,
            "map": lobby.map_name,
            "players": len(lobby.players),
            "max": lobby.options.max_players,
            "started": lobby.is_started,
            "public": lobby.is_public,
        })
    games.sort(key=lambda g: (g["started"], g["code"]))
    return games
