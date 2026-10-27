# Kartdata

En JSON-fil per karta. Bots använder dem för att hitta vägar (se
`server/navigation.py`).

| Fil | Karta |
|-----|-------|
| `skeld.json` | The Skeld |
| `mira.json` | MIRA HQ |
| `polus.json` | Polus |
| `dleks.json` | dlekS ehT (The Skeld spegelvänd) |
| `airship.json` | The Airship |
| `fungle.json` | The Fungle |
| `lobby.json` | Lobbyn |

Varje fil innehåller:

- `colliders`: väggar, som linjer `[x1, y1, x2, y2, ...]`
- `tasks`: uppdragen (numret är samma som spelet använder), deras typ och
  var konsolerna finns
- `rooms`: rummens namn och ungefärliga mittpunkt
- `spawn`: var spelarna ställs i början av rundan och på möten
- `vents`, `doors`: ventiler och dörrar
- `open`: `true` om alla väggar inte finns med (utomhuskartor)

## Var datan kommer ifrån

- Väggarna: [SkeldJS](https://github.com/SkeldJS/SkeldJS) (paketet
  `pathfinding`, väggar som lästs ur spelet). Väggarna för The Fungle
  kommer från [BetterCrewLink](https://github.com/OhMyGuus/BetterCrewLink)
  och är inte kompletta.
- Uppdrag, startplatser, ventiler och dörrar: [Impostor](https://github.com/Impostor/Impostor),
  som läst ut dem ur Among Us 2026.9.29 med verktyget Dumpostor.
- Rummens mittpunkter: [TownOfHost-Enhanced](https://github.com/EnhancedNetwork/TownofHost-Enhanced).

Alla fyra projekten har licensen GPL-3.0, och därför har filerna i den här
mappen också licensen GPL-3.0. Själva kartorna är Innersloths.
