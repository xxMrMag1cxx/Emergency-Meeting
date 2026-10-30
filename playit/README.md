# playit/

This is where **playitd**, playit.gg's tunnel program, lives. The server starts
it by itself (see `server/playit.py`), so that friends can play with you from
their own homes.

| File                | What it is |
|---------------------|------------|
| `playitd-macos`     | playitd for Mac (Intel and Apple silicon, macOS 11 or newer) |
| `playitd-windows-x86_64.exe`, `playitd-linux-*` | playitd for Windows and Linux (downloaded by the server) |
| `LICENSE-playit.txt`| playit.gg's license (BSD-2), comes with the program |
| `VERSION`           | which version of playitd is built |

`playitd-macos` is built by GitHub Actions from playit.gg's open source code
(<https://github.com/playit-cloud/playit-agent>), see
`.github/workflows/build-playit.yml`. playit.gg has no ready-made Mac files,
so we build it ourselves.

**Changing the version:** write the new version number in `VERSION` and push.
Then GitHub builds a new `playitd-macos` and puts it here.

**If `playitd-macos` is missing or doesn't start:** double-click
`build-playit.command` in the project folder. It builds playitd on the Mac
instead (takes 5–15 minutes the first time).

**Windows and Linux:** playit.gg has ready-made files, so the server
downloads the right one by itself from
<https://github.com/playit-cloud/playit-agent/releases> (the version in
`VERSION`) and saves it here as `playitd-windows-x86_64.exe`,
`playitd-linux-amd64` or `playitd-linux-aarch64`. The Windows and Linux zip
files on Emergency Meeting's Releases page already have it.
