# Map data

One JSON file per map. Bots use them to find paths (see
`server/navigation.py`).

| File | Map |
|------|-----|
| `skeld.json` | The Skeld |
| `mira.json` | MIRA HQ |
| `polus.json` | Polus |
| `dleks.json` | dlekS ehT (The Skeld mirrored) |
| `airship.json` | The Airship |
| `fungle.json` | The Fungle |
| `lobby.json` | The lobby |

Every file contains:

- `colliders`: walls, as lines `[x1, y1, x2, y2, ...]`
- `tasks`: the tasks (the number is the same one the game uses), their type
  and where the consoles are
- `rooms`: the rooms' names and approximate center points
- `spawn`: where the players are put at the start of the round and in meetings
- `vents`, `doors`: vents and doors
- `open`: `true` if not all walls are included (outdoor maps)

## Where the data comes from

- The walls: [SkeldJS](https://github.com/SkeldJS/SkeldJS) (the package
  `pathfinding`, walls read from the game). The walls for The Fungle
  come from [BetterCrewLink](https://github.com/OhMyGuus/BetterCrewLink)
  and are not complete.
- Tasks, start places, vents and doors: [Impostor](https://github.com/Impostor/Impostor),
  which read them from Among Us 2026.9.29 with the tool Dumpostor.
- The rooms' center points: [TownOfHost-Enhanced](https://github.com/EnhancedNetwork/TownofHost-Enhanced).

All four projects have the GPL-3.0 license, and therefore the files in this
folder also have the GPL-3.0 license. The maps themselves are Innersloth's.
