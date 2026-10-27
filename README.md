# Emergency Meeting

En egen Among Us-server, byggd från grunden i Python. Servern körs på en Mac
(macOS 12.7 Monterey eller nyare) och målet är att den ska kunna köra spelet
med egna plugins.

## Färdplan

- [x] **Steg 1:** Servern tar emot spelet, läser spelarens namn och version,
      och svarar med ett eget meddelande som syns i spelet
- [ ] **Steg 2:** HTTPS, så att telefoner och surfplattor kan ansluta
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
eller om datorn frågar om du vill installera utvecklarverktyg, ladda hellre
ner senaste Python från <https://www.python.org/downloads/macos/>
(välj "macOS 64-bit universal2 installer") och installera det.

Servern använder bara det som följer med Python, så inget annat behöver
installeras.

### 2. Hämta koden

Enklast: på GitHub-sidan för projektet, klicka på den gröna knappen **Code**
och välj **Download ZIP**. Packa upp mappen, till exempel på skrivbordet.

### 3. Starta servern

Dubbelklicka på **`start.command`** i mappen.

> Första gången kan macOS säga att filen inte går att öppna eftersom den kommer
> från internet. Högerklicka då på filen, välj **Öppna** och sedan **Öppna** igen.
> Om macOS frågar om Python får ta emot inkommande anslutningar, välj **Tillåt**.

Det går också att starta från Terminal:

```
cd ~/Desktop/emergency-meeting
python3 -m server
```

När servern är igång visas Macens adress i hemnätverket, till exempel
`192.168.1.23`. Den adressen behövs i nästa steg.

Stäng av servern med **Ctrl+C**.

### 4. Testa utan spelet

Låt servern vara igång och öppna ett **nytt** Terminal-fönster:

```
cd ~/Desktop/emergency-meeting
python3 tools/testklient.py
```

Testklienten låtsas vara Among Us. Om allt fungerar skriver den ut
välkomstmeddelandet från servern och sedan `Allt fungerar!`.

## Ansluta med Among Us

### På en PC (Steam, Epic eller Microsoft Store) i samma wifi

1. Gå till <https://impostor.github.io/Impostor/> (ett verktyg från
   Impostor-projektet som fungerar för alla kompatibla servrar).
2. Välj dator som plattform, protokoll **http**, adress = Macens adress (t.ex.
   `192.168.1.23`), port `22023`, och ett namn, t.ex. `Emergency Meeting`.
3. Ladda ner filen `regionInfo.json` och följ instruktionerna på sidan för
   var den ska ligga.
4. Starta Among Us, välj servern **Emergency Meeting** och tryck på
   **Create Game**.

Om allt fungerar visar spelet välkomstmeddelandet från servern. Det betyder
att spelet och servern pratar med varandra. Att faktiskt skapa ett spel kommer
i steg 3.

### På telefon eller surfplatta

Mobilversionerna av Among Us kräver HTTPS. Det fixar vi i steg 2.

## Inställningar

Inställningarna finns i `config.json`:

| Inställning       | Vad den gör |
|-------------------|-------------|
| `server_name`     | Serverns namn |
| `listen_ip`       | `0.0.0.0` = lyssna på alla nätverk. Behöver sällan ändras |
| `port`            | Port för både HTTP och spel. Among Us använder `22023` |
| `public_ip`       | `auto` = Macens adress i hemnätverket. Kan sättas till en egen adress |
| `welcome_message` | Texten som visas i spelet. `{namn}` byts mot spelarens namn |
| `debug`           | `true` = visa varje paket i loggen, bra vid felsökning |

## Så här är koden uppbyggd

```
server/
  __main__.py    startar allt
  config.py      läser config.json
  matchmaker.py  HTTP-delen: spelet frågar var servern finns
  hazel.py       nätverkslagret: kvitton, ping och omsändning av paket
  handshake.py   läser spelets första paket (namn, version, plattform)
  game.py        spellogiken: vad servern gör med meddelandena
  messages.py    läsa och skriva bytes
  protocol.py    alla siffror och namn som Among Us använder
tools/
  testklient.py  låtsas-Among Us för att testa servern
start.command    dubbelklicka för att starta på Mac
```

Så här går en anslutning till:

1. Spelet frågar servern via **HTTP** (TCP-port 22023): "Får jag en token?"
   och "Var ska jag skapa spelet?". Servern svarar med Macens adress.
2. Spelet skickar ett **Hello**-paket via **UDP** (port 22023) med namn och version.
3. Spelet skickar **HostGame** ("skapa spel"). Servern svarar med
   välkomstmeddelandet och kopplar bort spelaren.

## Felsökning

- **"Address already in use"**: servern körs redan i ett annat fönster. Stäng det.
- **Spelet hittar inte servern**: kolla att PC:n och Macen är på samma wifi,
  att adressen stämmer och att macOS-brandväggen tillåter Python
  (Systeminställningar → Säkerhet och integritet → Brandvägg).
- **Spelet säger fel version**: skriv ner vilken version spelet har (står uppe
  till vänster i huvudmenyn) och vad loggen visar, så felsöker vi.
- Sätt `"debug": true` i `config.json` för att se allt som skickas.

## Tack

Protokollet är kartlagt med hjälp av det öppna projektet
[Impostor](https://github.com/Impostor/Impostor), som vi använder som
referens. Ingen kod är kopierad därifrån.
