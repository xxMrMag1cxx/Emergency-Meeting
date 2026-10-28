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
- [x] **Steg 7:** Impostors kan döda (servern bestämmer, som Among Us egna
      servrar). Bots går runt i lobbyn och på alla kartor och går till sina
      uppdrag (behöver testas med riktiga spelet)
- [x] **Steg 8:** Kompisar kan spela från sina egna hem, på dator eller
      mobil, via playit.gg. Inget behöver ändras i routern
- [x] **Steg 9:** En HTTPS-adress som är samma varje gång (ngrok), så att
      kompisar bara behöver lägga till servern en gång (behöver testas med
      riktiga spelet)

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

Among Us kräver HTTPS när spelet och servern är på olika enheter. Servern
använder helst ngrok (se nedan), och cloudflared är reserven om ngrok inte
fungerar. cloudflared ger en gratis HTTPS-adress via Cloudflare, utan konto.
Skriptet väljer själv en version som fungerar på er macOS.

### 4. Starta servern

Dubbelklicka på **`start.command`**. Om macOS frågar om Python får ta emot
inkommande anslutningar, välj **Tillåt**.

Första gången frågar servern efter två saker. Båda behövs bara en gång:

- **FAST HTTPS-ADRESS MED NGROK**: klistra in en nyckel från ngrok, se
  [Fast HTTPS-adress med ngrok](#fast-https-adress-med-ngrok).
- **KOPPLA SERVERN TILL PLAYIT.GG**: öppna en länk och godkänn servern, se
  [Spela med kompisar hemifrån](#spela-med-kompisar-hemifrån).

Efter 10–30 sekunder skriver servern ut **HTTPS ÄR KLART!** och en adress,
till exempel:

```
https://glad-pingvin-1234.ngrok-free.dev
```

Med ngrok är adressen samma varje gång. Utan ngrok blir det en
Cloudflare-adress (`...trycloudflare.com`) som byts vid varje start.

Stäng av servern med **Ctrl+C**.

### 5. Testa utan spelet (valfritt)

Låt servern vara igång och dubbelklicka på **`testa.command`**. Testklienten
låtsas vara två Among Us-spelare: den ena skapar ett spel, den andra går med
med spelkoden. Om allt fungerar skriver den `Allt fungerar!`.

## Ansluta med Among Us

Med playit.gg (se nästa del) kan den som spelar vara var som helst. Utan
playit.gg måste enheten vara på **samma wifi** som Macen.

1. Öppna HTTPS-adressen som servern skrev ut i en webbläsare på enheten
   som ska spela.
2. Tryck på **Lägg till i Among Us**. Spelet öppnas och servern läggs till.
   På PC kan man i stället ladda ner `regionInfo.json` från samma sida och
   lägga den i spelets mapp (sidan visar var).
3. Starta om Among Us helt, välj servern **Emergency Meeting** och tryck på
   **Create Game**.

Spelet får en spelkod och du hamnar i lobbyn. Andra på samma wifi kan gå med
genom att lägga till servern på samma sätt och skriva in spelkoden.

Med ngrok behöver man bara göra steg 1–2 en gång. Med en Cloudflare-adress
byts adressen vid varje omstart, och då måste man göra om steg 1–2.

## Fast HTTPS-adress med ngrok

**ngrok** (gratis) ger servern en HTTPS-adress som är samma varje gång, till
exempel `https://glad-pingvin-1234.ngrok-free.dev`. Då behöver kompisar bara
lägga till servern i Among Us en gång.

### Första gången (bara värden)

1. Starta servern. Den visar rutan **FAST HTTPS-ADRESS MED NGROK**.
2. Skapa ett gratiskonto på <https://dashboard.ngrok.com/signup> (eller logga
   in).
3. Öppna <https://dashboard.ngrok.com/get-started/your-authtoken> och kopiera
   din **Authtoken**.
4. Klicka i terminalfönstret, klistra in nyckeln (Cmd+V) och tryck **Enter**.
   Det gör inget om det kommer andra rader i fönstret under tiden.
5. Servern hämtar själv programmet ngrok och skriver sedan **HTTPS ÄR KLART!**
   med den nya adressen.

Nyckeln sparas i `ngrok-nyckel.txt` och adressen i `ngrok-adress.txt`. Dela
inte nyckeln med någon (filen är redan undantagen i `.gitignore`).

Tills nyckeln är inklistrad används Cloudflare, så servern fungerar ändå.
Tryck bara Enter om ni vill hoppa över ngrok den gången.

### Bra att veta

- Första gången man öppnar adressen i en webbläsare visar ngrok en
  varningssida. Tryck **Visit Site**. Spelet själv får ingen varningssida.
- Om ngrok inte kommer igång inom 40 sekunder tar servern Cloudflare i
  stället. Det står i rutan **HTTPS ÄR KLART!** vilken adress som gäller.
- Gratiskontot räcker gott: ngrok tillåter 20 000 anrop i månaden, och en
  spelare som går med gör bara ett fåtal.
- Vill ni bara använda Cloudflare: sätt `"ngrok": false` i `config.json`.

## Spela med kompisar hemifrån

Servern använder **playit.gg** (gratis) för att kompisar ska kunna spela med
er från sina egna hem, på wifi eller mobildata. Ingenting behöver ändras i
routern. Spelet får en fast adress hos playit.gg som är samma varje gång.

### Första gången (bara värden)

1. Starta servern. Den visar rutan **KOPPLA SERVERN TILL PLAYIT.GG** med en
   länk, till exempel `https://playit.gg/claim/3fa91c0d2e`.
2. Öppna länken i en webbläsare. Logga in, eller skapa ett gratiskonto, och
   godkänn servern.
3. Servern skapar sedan själv en tunnel hos playit.gg. Om det inte går visar
   den rutan **SKAPA EN TUNNEL PÅ PLAYIT.GG** med vad man ska klicka på
   playit.gg. Servern märker själv när tunneln är klar.
4. När rutan **PLAYIT ÄR KLART!** syns är allt klart.

Servern sparar en hemlig nyckel i `playit-nyckel.txt`. Därefter går allt av
sig självt varje gång servern startar. Dela inte filen med någon, och lägg
inte upp den på GitHub (den är redan undantagen i `.gitignore`).

### Så går kompisar med

Precis som på wifi: de öppnar HTTPS-adressen som servern skrev ut, trycker
**Lägg till i Among Us**, startar om spelet, väljer **Emergency Meeting** och
skriver in spelkoden. Skicka adressen till dem i en chatt.

Med ngrok gör de det bara en gång. Nästa gång väljer de bara **Emergency
Meeting** i spelet och skriver in spelkoden.

Telefoner behöver inte längre tillståndet "Lokalt nätverk", eftersom spelet
går via internet i stället för direkt till Macen.

### Om något strular

- **PLAYIT.GG KÄNNER INTE IGEN SERVERN**: nyckeln fungerar inte längre (till
  exempel om servern togs bort på playit.gg). Ta bort `playit-nyckel.txt` och
  starta om servern, så kommer en ny länk.
- **"playit.gg finns inte här"** i loggen: filen `playit/playitd-macos`
  saknas. Ladda ner koden som ZIP igen, eller dubbelklicka på
  `bygg-playit.command` (se [playit/README.md](playit/README.md)).
- Vill ni bara spela på ert wifi: sätt `"playit": false` i `config.json`.

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
15:05:31  bot     Bot_1 gjorde ett uppdrag (Fix Wiring) (1/4)
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

## Dödande

I Among Us är det servern, inte värden, som bestämmer om en impostor får
döda. Spelet frågar servern ("CheckMurder"), servern kontrollerar att
mördaren är en levande impostor, att offret lever och inte är impostor och
att det inte pågår ett möte, och skickar sedan "MurderPlayer" till alla.
Om en Guardian Angel har skyddat offret misslyckas mordet. Servern sköter
också Phantoms "bli osynlig" och "synas igen" på samma sätt.

## Bots som går

Bots (från botpluginet) går runt i lobbyn och på kartan. Under en runda går
de till sina uppdrag, står vid konsolen en stund och gör uppdraget. När
allt är klart vandrar de mellan rummen. På möten står de vid bordet och
röstar skip när diskussionstiden är slut.

Kartorna finns i `server/kartdata/`: väggarna, var uppdragen görs och var
spelarna börjar. Servern delar kartan i små rutor och letar upp en väg runt
väggarna (se `server/navigation.py`). The Skeld, MIRA HQ, Polus, dlekS ehT
och The Airship har riktiga väggar. På The Fungle finns bara en del av
väggarna med, så där kan en bot ibland gå igenom ett träd eller en sten.
På The Airship kan bots inte klättra på stegar eller åka plattformen, så de
gör uppdragen som de kan gå till.

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
| `https_tunnel`     | `true` = starta en HTTPS-tunnel (ngrok, annars cloudflared) |
| `ngrok`            | `true` = använd ngrok, så att HTTPS-adressen är samma varje gång |
| `ngrok_path`       | `auto` = leta efter ngrok själv (mappen `ngrok/` först) och hämta det om det saknas |
| `cloudflared_path` | `auto` = leta efter cloudflared själv (projektmappen först) |
| `playit`           | `true` = gör spelet nåbart hemifrån med playit.gg |
| `playit_path`      | `auto` = leta efter playitd själv (mappen `playit/` först) |
| `plugins`          | `true` = ladda plugins från mappen `plugins/` |
| `debug`            | `true` = visa varje paket i loggen, bra vid felsökning |

## Så här är koden uppbyggd

```
server/
  __main__.py    startar allt
  config.py      läser config.json
  matchmaker.py  HTTP-delen: spelet frågar var servern finns
  ngrok.py       startar ngrok: HTTPS-adress som är samma varje gång
  tunnel.py      startar cloudflared (reserv): HTTPS-adress som byts varje gång
  playit.py      startar playitd och håller koll på playit.gg-tunneln
  webpage.py     startsidan med knappen "Lägg till i Among Us"
  region.py      bygger regionInfo.json och amongus://-länken
  hazel.py       nätverkslagret: kvitton, ping och omsändning av paket
  handshake.py   läser spelets första paket (namn, version, plattform)
  game.py        spellogiken: skapa spel, gå med, skicka vidare speldata
  lobby.py       en lobby: spelkod, spelare, värd och spelarinfo
  options.py     läser spelinställningarna och visar vad som ändrats
  plugins.py     laddar plugins och anropar dem när något händer
  bots.py        bots: låtsasspelare som servern styr
  navigation.py  hittar vägar runt väggarna åt bots
  kartdata/      kartorna: väggar, uppdrag, rum och startplatser
  blackbox.py    "svart låda": sparar vad som hände om någon kopplas från
  gamecode.py    spelkoder ("ABCDEF") och talen spelet skickar
  messages.py    läsa och skriva bytes
  protocol.py    alla siffror och namn som Among Us använder
plugins/         plugins som servern laddar (se plugins/README.md)
playit/          playitd, playit.gg:s tunnelprogram (se playit/README.md)
tools/
  testklient.py  två låtsas-Among Us som testar servern (skapa, gå med,
                 byta färg, ändra inställningar, chatta, lämna)
start.command               starta servern
testa.command               kör testklienten
hamta-cloudflared.command   hämtar cloudflared
bygg-playit.command         bygger playitd på Macen (behövs sällan)
.github/workflows/          GitHub bygger playitd för Mac
```

Så här går en anslutning till:

```
Among Us --HTTPS--> ngrok -------tunnel--> ngrok -------HTTP---> servern (TCP 22023)
Among Us --UDP----> playit.gg ---tunnel--> playitd -----UDP----> servern (UDP 22023)
```

Om ngrok inte fungerar går HTTPS i stället via Cloudflare (programmet
cloudflared). Utan playit.gg (eller om spelet frågar servern direkt, utan
HTTPS) går UDP direkt från spelet till Macen på ert wifi.

1. Spelet frågar servern via **HTTPS**: "Får jag en token?" och "Var ska jag
   skapa spelet?". Servern svarar med playit.gg-adressen (eller Macens
   adress i hemnätverket om playit.gg inte används).
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
  Med ngrok är adressen samma varje gång, men om rutan **HTTPS ÄR KLART!**
  visar en `trycloudflare.com`-adress har servern tagit Cloudflare i stället.
- **NGROK KÄNNER INTE IGEN NYCKELN**: klistra in en ny nyckel från
  <https://dashboard.ngrok.com/get-started/your-authtoken> i terminalfönstret.
- **NGROK ANVÄNDS REDAN**: ngrok-kontot används av en annan dator eller ett
  annat program. Stäng det och starta om servern.
- **"försökte ansluta med HTTPS direkt till port 22023"** i loggen: spelet är
  inställt på Macens IP-adress i stället för HTTPS-adressen. Lägg till servern
  igen via HTTPS-adressen.
- **"nådde servern via HTTPS men anslöt aldrig till spelet via UDP"** i loggen:
  enheten kommer åt servern via internet men inte själva spelet. Kolla att
  rutan **PLAYIT ÄR KLART!** har visats. Utan playit.gg måste enheten vara på
  samma wifi, och på iPhone: Inställningar → Integritet och säkerhet → Lokalt
  nätverk → slå på Among Us.
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

Kartdatan i `server/kartdata/` kommer från andra öppna projekt, se
[server/kartdata/README.md](server/kartdata/README.md). De projekten har
licensen GPL-3.0, och kartdatan har samma licens.
