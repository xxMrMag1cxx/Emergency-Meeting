# playit/

Här ligger **playitd**, playit.gg:s tunnelprogram. Servern startar det själv
(se `server/playit.py`), så att kompisar kan spela med er från sina egna hem.

| Fil                 | Vad det är |
|---------------------|------------|
| `playitd-macos`     | playitd för Mac (Intel och Apple-chip, macOS 11 eller nyare) |
| `LICENSE-playit.txt`| playit.gg:s licens (BSD-2), följer med programmet |
| `VERSION`           | vilken version av playitd som byggs |

`playitd-macos` byggs av GitHub Actions från playit.gg:s öppna källkod
(<https://github.com/playit-cloud/playit-agent>), se
`.github/workflows/bygg-playit.yml`. playit.gg har inga färdiga Mac-filer,
därför bygger vi den själva.

**Byta version:** skriv det nya versionsnumret i `VERSION` och pusha. Då
bygger GitHub en ny `playitd-macos` och lägger den här.

**Om `playitd-macos` saknas eller inte startar:** dubbelklicka på
`bygg-playit.command` i projektmappen. Det bygger playitd på Macen i
stället (tar 5–15 minuter första gången).

På Linux letar servern efter `playitd-linux-amd64` eller
`playitd-linux-aarch64` här. Dem kan man ladda ner från
<https://github.com/playit-cloud/playit-agent/releases>.
