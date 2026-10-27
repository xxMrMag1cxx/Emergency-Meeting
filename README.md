# Emergency Meeting

En egen Among Us-server, byggd från grunden i Python. Servern körs på en Mac
(macOS 12.7 Monterey eller nyare) och målet är att den ska kunna köra spelet
med egna plugins.

## Färdplan

- [x] **Steg 1:** Servern tar emot spelet, läser spelarens namn och version,
      och svarar med ett eget meddelande som syns i spelet
- [x] **Steg 2:** HTTPS via en Cloudflare-tunnel, så att spelet kan ansluta
      från andra enheter
- [x] **Steg 3:** Skapa spel, få en spelkod och komma in i lobbyn
      (behöver testas med riktiga spelet)
- [x] **Steg 3b:** Loggen visar alla ändringar av spelinställningar
- [ ] **Steg 4:** Gå med i ett spel med spelkoden, flera spelare i samma lobby
      (klart i servern, behöver testas med två enheter)
- [x] **Steg 5:** Spela en hel runda och "Play Again". Loggen visar möten,
      dödsfall och röstning, och en sammanfattning när rundan är slut
      (behöver testas med riktiga spelet)
- [x] **Steg 6:** Eget pluginsystem, se [plugins/README.md](plugins/README.md)

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
låtsas vara två Among Us-spelare: den ena skapar ett spel, den andra går med
med spelkoden. Om allt fungerar skriver den `Allt fungerar!`.

## Ansluta med Among Us

Enheten som spelar måste vara på **samma wifi** som Macen.

1. Öppna HTTPS-adressen som servern skrev ut i en webbläsare på enheten
   som ska spela.
2. Tryck på **Lägg till i Among Us**. Spelet öppnas och servern läggs till.
   På PC kan man i stället ladda ner `regionInfo.json` från samma sida och
   lägga den i spelets mapp (sidan visar var).
3. Starta om Among Us helt, välj servern **Emergency Meeting** och tryck på
   **Create Game**.

Spelet får en spelkod och du hamnar i lobbyn. Andra på samma wifi kan gå med
genom att lägga till servern på samma sätt och skriva in spelkoden.

Eftersom adressen byts vid varje omstart behöver man göra om steg 1–2 efter
att servern har startats om.

## Vad loggen visar

Servern skriver ut vad som händer, till exempel:

```
15:01:12  spel    Blobi skapade spelet NUORZH (The Skeld, Vanligt, max 10 spelare, 1 impostor)
15:01:12  spel    Blobi gick med i NUORZH som värd (1/10 spelare)
15:02:40  spel    NUORZH: Blobi har färgen Lime
15:03:05  spel    NUORZH: Blobi ändrade Kill Cooldown: 30 s -> 25 s
15:03:30  spel    Kalle gick med i NUORZH som spelare (2/10 spelare)
15:03:41  spel    NUORZH chatt  Kalle: hej!
15:05:02  spel    NUORZH: spelet startar! (4 spelare, The Skeld)
15:06:10  spel    NUORZH: Bot_2 har dödats! (1 döda)
15:06:30  spel    NUORZH: MÖTE! Blobi hittade Bot_2
15:07:05  spel    NUORZH: Bot_1 röstades ut
15:07:20  spel    NUORZH: RUNDAN ÄR SLUT. Besättningen vann genom att rösta ut impostorerna
15:07:20  spel    NUORZH:   Impostors: Bot_1
15:07:20  spel    NUORZH:   Bot_2 dödades av Bot_1
```

Under rundan skriver loggen inte ut vem som dödade någon eller vilka som är
impostors, så att den som tittar på serverfönstret inte får veta det. Det
kommer först i sammanfattningen när rundan är slut.

Inställningarna har samma namn som i spelets meny. Om spelet får en ny
inställning som servern inte känner till står det "Övriga inställningar".

## Plugins

Mappen `plugins/` är till för plugins som servern laddar när den startar.
Ett plugin är en Python-fil som kan reagera på saker som händer (någon går
med, skriver i chatten, ändrar inställningar...) och själv skicka
chattmeddelanden eller lägga till bots.

Färdiga plugins finns i
[Common Emergency Meeting Plugins (CEMP)](https://github.com/xxMrMag1cxx/Common-Emergency-Meeting-Plugins).
Ladda ner det repot som ZIP, packa upp det och lägg hela mappen i
`plugins/`. Starta sedan om servern.

Hur man skriver egna plugins står i [plugins/README.md](plugins/README.md).

## Serverns inställningar

Serverns egna inställningar finns i `config.json`:

| Inställning        | Vad den gör |
|--------------------|-------------|
| `server_name`      | Serverns namn |
| `listen_ip`        | `0.0.0.0` = lyssna på alla nätverk. Behöver sällan ändras |
| `port`             | Port för både HTTP och spel. Among Us använder `22023` |
| `public_ip`        | `auto` = Macens adress i hemnätverket. Kan sättas till en egen adress |
| `https_tunnel`     | `true` = starta HTTPS-tunneln med cloudflared |
| `cloudflared_path` | `auto` = leta efter cloudflared själv (projektmappen först) |
| `plugins`          | `true` = ladda plugins från mappen `plugins/` |
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
  game.py        spellogiken: skapa spel, gå med, skicka vidare speldata
  lobby.py       en lobby: spelkod, spelare, värd och spelarinfo
  options.py     läser spelinställningarna och visar vad som ändrats
  plugins.py     laddar plugins och anropar dem när något händer
  bots.py        bots: låtsasspelare som servern styr
  blackbox.py    "svart låda": sparar vad som hände om någon kopplas från
plugins/         plugins som servern laddar (se plugins/README.md)
  gamecode.py    spelkoder ("ABCDEF") och talen spelet skickar
  messages.py    läsa och skriva bytes
  protocol.py    alla siffror och namn som Among Us använder
tools/
  testklient.py  två låtsas-Among Us som testar servern (skapa, gå med,
                 byta färg, ändra inställningar, chatta, lämna)
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
3. Spelet skickar **HostGame** ("skapa spel") med inställningarna. Servern
   skapar en lobby och svarar med spelkoden.
4. Spelet skickar **JoinGame** med koden. Servern svarar **JoinedGame**, och den
   första som går med blir värd.
5. Spelet laddar lobbyn. Servern skapar ett **spelarinfo**-objekt för spelaren
   (där spelet sparar namn, färg och hatt).
6. Därefter skickar värden **GameData** hela tiden (rörelser, färgbyten,
   chatt...). Servern skickar vidare allt till de andra i lobbyn.

Det mesta av spellogiken körs alltså hos värden. Servern är mest en brevbärare
som håller koll på vem som är med i vilket spel.

## Felsökning

- **Svart skärm och inget händer i serverfönstret**: spelet når inte servern.
  Kolla att ni använder HTTPS-adressen från *senaste* starten av servern.
- **"försökte ansluta med HTTPS direkt till port 22023"** i loggen: spelet är
  inställt på Macens IP-adress i stället för HTTPS-adressen. Lägg till servern
  igen via HTTPS-adressen.
- **"nådde servern via HTTPS men anslöt aldrig till spelet via UDP"** i loggen:
  enheten kommer åt servern via internet men inte direkt till Macen. På
  iPhone: Inställningar → Integritet och säkerhet → Lokalt nätverk → slå på
  Among Us. Kolla också att enheten är på samma wifi.
- **Token hämtas men inget mer händer**: spelet når HTTPS-delen men inte UDP.
  Kolla att enheten är på samma wifi och att brandväggen tillåter Python
  (Systeminställningar → Säkerhet och integritet → Brandvägg).
- **Spelet fastnar efter Create Game** eller lobbyn ser konstig ut: sätt
  `"debug": true` i `config.json`, prova igen och spara loggen. Den visar
  exakt vad spelet och servern skickar till varandra.
- **"Address already in use"**: servern körs redan i ett annat fönster. Stäng det.
- **Spelet säger fel version**: skriv ner vilken version spelet har (står uppe
  till vänster i huvudmenyn) och vad loggen visar.
- **Någon kopplas från oväntat**: varje gång en spelare i ett spel kopplas
  från sparas en rapport i mappen `loggar/` med de senaste meddelandena
  mellan spelet och servern. Skicka den filen, så går det att se vad som
  hände precis innan.
- Sätt `"debug": true` i `config.json` för att se allt som skickas.

## Tack

Protokollet är kartlagt med hjälp av det öppna projektet
[Impostor](https://github.com/Impostor/Impostor), som vi använder som
referens. Ingen kod är kopierad därifrån.
