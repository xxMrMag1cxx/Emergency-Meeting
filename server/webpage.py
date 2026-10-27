"""
Startsidan som visas när man öppnar serverns adress i en webbläsare.

Därifrån kan man lägga till servern i Among Us med ett klick
(telefon/surfplatta) eller ladda ner regionInfo.json (PC).
"""

from __future__ import annotations

from html import escape
from string import Template

from .region import app_link

PAGE = Template(
    """<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$name</title>
<style>
  :root { --bg: #14161f; --card: #1f2230; --text: #f2f2f2; --muted: #a7abbd;
          --red: #d7263d; --blue: #3a7bd5; --warn: #f4c542; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font-family: -apple-system, "Segoe UI", Roboto, sans-serif; line-height: 1.5; }
  main { max-width: 560px; margin: 0 auto; padding: 32px 16px 48px; }
  h1 { font-size: 2rem; margin: 0 0 4px; letter-spacing: .02em; }
  h1 span { color: var(--red); }
  .sub { color: var(--muted); margin: 0 0 24px; }
  .card { background: var(--card); border-radius: 14px; padding: 18px 18px 20px; margin-bottom: 16px; }
  h2 { font-size: 1.1rem; margin: 0 0 8px; }
  p { margin: 0 0 12px; }
  .btn { display: block; text-align: center; padding: 14px; border-radius: 10px;
         color: #fff; text-decoration: none; font-weight: 700; font-size: 1.05rem; }
  .btn.red { background: var(--red); }
  .btn.blue { background: var(--blue); }
  code { background: #0e1016; padding: 2px 6px; border-radius: 6px; font-size: .9em; word-break: break-all; }
  .warn { border-left: 4px solid var(--warn); }
  ol { margin: 0; padding-left: 20px; }
  .small { color: var(--muted); font-size: .9rem; }
</style>
</head>
<body>
<main>
  <h1>$name<span>.</span></h1>
  <p class="sub">Servern är igång. Lägg till den i Among Us här nedanför.</p>
  $content
  <p class="small">Adress: <code>$url</code> &middot; port <code>$port</code></p>
</main>
</body>
</html>
"""
)

HTTPS_CONTENT = Template(
    """
  <div class="card">
    <h2>Telefon, surfplatta eller dator med spelet</h2>
    <p>Tryck på knappen. Among Us öppnas och servern läggs till.</p>
    <a class="btn red" href="$app_link">Lägg till i Among Us</a>
  </div>
  <div class="card">
    <h2>PC: ladda ner fil i stället</h2>
    <p>Om knappen inte fungerar på PC:n, ladda ner filen och lägg den här
       (ersätt den gamla om det redan finns en):</p>
    <p><code>%USERPROFILE%\\AppData\\LocalLow\\Innersloth\\Among Us\\regionInfo.json</code></p>
    <a class="btn blue" href="/regionInfo.json" download="regionInfo.json">Ladda ner regionInfo.json</a>
  </div>
  <div class="card">
    <h2>Sedan</h2>
    <ol>
      <li>Starta om Among Us helt.</li>
      <li>Välj servern <b>$name</b> (jordgloben i menyn).</li>
      <li>Tryck <b>Create Game</b>.</li>
    </ol>
  </div>
"""
)

HTTP_CONTENT = Template(
    """
  <div class="card warn">
    <h2>Den här adressen är inte HTTPS</h2>
    <p>Among Us kräver HTTPS när spelet och servern inte körs på samma dator.
       Använd HTTPS-adressen som servern skriver ut i Terminal-fönstret.</p>
    $tunnel_hint
  </div>
"""
)


def render(name: str, url: str, port: int, is_https: bool, tunnel_url: str = "") -> str:
    if is_https:
        content = HTTPS_CONTENT.substitute(
            app_link=escape(app_link(name, url, port)),
            name=escape(name),
        )
    else:
        if tunnel_url:
            hint = (
                f'<a class="btn red" href="{escape(tunnel_url)}">'
                f"Öppna HTTPS-adressen</a>"
            )
        else:
            hint = (
                "<p>Tunneln är inte igång. Kör <code>hamta-cloudflared.command</code> "
                "en gång och starta sedan om servern.</p>"
            )
        content = HTTP_CONTENT.substitute(tunnel_hint=hint)

    return PAGE.substitute(
        name=escape(name),
        content=content,
        url=escape(url),
        port=port,
    )
