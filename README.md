# Emergency Meeting

En egen Among Us-server, byggd från grunden i Python. Servern körs på en Mac
(macOS 12.7 Monterey eller nyare) och målet är att den ska kunna köra spelet
med egna plugins.

## Färdplan

- [x] **Steg 1:** Servern tar emot spelet, läser spelarens namn och version,
      och svarar med ett eget meddelande som syns i spelet
- [x] **Steg 2:** HTTPS via en Cloudflare-tunnel, så att spelet kan ansluta
      från andra enheter (behöver testas med riktiga spelet)
- [ ] **Steg 3:** Skapa spel och få en spelkod
- [ ] **Steg 4:** Gå med i ett spel med spelkoden, flera spelare i samma lobby
- [ ] **Steg 5:** Skicka speldata mellan spelarna, så att man kan spela en hel runda
- [ ] **Steg 6:** Eget pluginsystem

## Kom igång på Macen

### 1. Kolla att Python finns

Öppna **Terminal** (finns under Program → Verktygsprogram) och skriv:

```
python3 --version
```

Om det står `Python 3.8` eller högre är allt klart. Om det står något annat,
ladda ner senaste Python från <https://www.python.org/downloads/macos/>
(välj "macOS 64-bit universal2 installer") och installera det.

Servern använder bara det som följer med Python.

### 2. Hämta koden

På GitHub-sidan för projektet: klicka på den gröna knappen **Code** och välj
**Download ZIP**. Packa upp mappen. Var den hamnar spelar ingen roll, alla
filer nedan startas med dubbelklick i Finder.

> Första gången macOS säger att en fil inte går att öppna eftersom den kommer
> från internet: högerklicka på filen, välj **Öppna** och sedan **Öppna** igen.

### 3. Hämta cloudflared (en gång)

Dubbelklicka på **`hamta-cloudflared.command`**.

Among Us kräver HTTPS när spelet och servern är på olika enheter. Programmet
cloudflared ger servern en gratis HTTPS-adress via Cloudflare, utan konto.
Skriptet väljer själv en version som fungerar på er macOS.

### 4. Starta servern

Dubbelklicka på **`start.command`**. Om macOS frågar om Python får ta emot
inkommande anslutningar, välj **Tillåt**.

Efter 10–30 sekunder skriver servern ut **HTTPS ÄR KLART!** och en adress,
till exempel:

```
https://kingston-inside-best-graphic.trycloudflare.com
```

Adressen byts varje gång servern startas om.

Stäng av servern med **Ctrl+C**.

### 5. Testa utan spelet (valfritt)

Låt servern vara igång och dubbelklicka på **`testa.command`**. Testklienten
låtsas vara Among Us. Om allt fungerar skriver den `Allt fungerar!`.

## Ansluta med Among Us

Enheten som spelar måste vara på **samma wifi** som Macen.

1. Öppna HTTPS-adressen som servern skrev ut i en webbläsare på enheten
   som ska spela.
2. Tryck på **Lägg till i Among Us**. Spelet öppnas och servern läggs till.
   På PC kan man i stället ladda ner `regionInfo.json` från samma sida och
   lägga den i spelets mapp (sidan visar var).
3. Starta om Among Us helt, välj servern **Emergency Meeting** och tryck på
   **Create Game**.

Om allt fungerar visar spelet välkomstmeddelandet från servern. Att faktiskt
skapa ett spel kommer i steg 3.

Eftersom adressen byts vid varje omstart behöver man göra om steg 1–2 efter
att servern har startats om.

## Inställningar

Inställningarna finns i `config.json`:

| Inställning        | Vad den gör |
|--------------------|-------------|
| `server_name`      | Serverns namn |
| `listen_ip`        | `0.0.0.0` = lyssna på alla nätverk. Behöver sällan ändras |
| `port`             | Port för både HTTP och spel. Among Us använder `22023` |
| `public_ip`        | `auto` = Macens adress i hemnätverket. Kan sättas till en egen adress |
| `welcome_message`  | Texten som visas i spelet. `{namn}` byts mot spelarens namn |
| `https_tunnel`     | `true` = starta HTTPS-tunneln med cloudflared |
| `cloudflared_path` | `auto` = leta efter cloudflared själv (projektmappen först) |
| `debug`            | `true` = visa varje paket i loggen, bra vid felsökning |

## Så här är koden uppbyggd

```
server/
  __main__.py    startar allt
  config.py      läser config.json
  matchmaker.py  HTTP-delen: spelet frågar var servern finns
  tunnel.py      startar cloudflared och läser ut HTTPS-adressen
  webpage.py     startsidan med knappen "Lägg till i Among Us"
  region.py      bygger regionInfo.json och amongus://-länken
  hazel.py       nätverkslagret: kvitton, ping och omsändning av paket
  handshake.py   läser spelets första paket (namn, version, plattform)
  game.py        spellogiken: vad servern gör med meddelandena
  messages.py    läsa och skriva bytes
  protocol.py    alla siffror och namn som Among Us använder
tools/
  testklient.py  låtsas-Among Us för att testa servern
start.command               starta servern
testa.command               kör testklienten
hamta-cloudflared.command   hämtar cloudflared
```

Så här går en anslutning till:

```
Among Us --HTTPS--> Cloudflare --tunnel--> cloudflared --HTTP--> servern (TCP 22023)
Among Us -----------------------UDP-----------------------> servern (UDP 22023)
```

1. Spelet frågar servern via **HTTPS**: "Får jag en token?" och "Var ska jag
   skapa spelet?". Servern svarar med Macens adress i hemnätverket.
2. Spelet skickar ett **Hello**-paket direkt till Macen via **UDP** med namn
   och version.
3. Spelet skickar **HostGame** ("skapa spel"). Servern svarar med
   välkomstmeddelandet och kopplar bort spelaren.

## Felsökning

- **Svart skärm och inget händer i serverfönstret**: spelet når inte servern.
  Kolla att ni använder HTTPS-adressen från *senaste* starten av servern.
- **"försökte ansluta med HTTPS direkt till port 22023"** i loggen: spelet är
  inställt på Macens IP-adress i stället för HTTPS-adressen. Lägg till servern
  igen via HTTPS-adressen.
- **Token hämtas men inget mer händer**: spelet når HTTPS-delen men inte UDP.
  Kolla att enheten är på samma wifi och att brandväggen tillåter Python
  (Systeminställningar → Säkerhet och integritet → Brandvägg).
- **"Address already in use"**: servern körs redan i ett annat fönster. Stäng det.
- **Spelet säger fel version**: skriv ner vilken version spelet har (står uppe
  till vänster i huvudmenyn) och vad loggen visar.
- Sätt `"debug": true` i `config.json` för att se allt som skickas.

## Tack

Protokollet är kartlagt med hjälp av det öppna projektet
[Impostor](https://github.com/Impostor/Impostor), som vi använder som
referens. Ingen kod är kopierad därifrån.
