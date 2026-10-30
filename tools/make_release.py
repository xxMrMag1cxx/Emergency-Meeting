"""
Makes the three files for a release on GitHub, one for each system:

    Emergency-Meeting-<version>-macos.zip     start.command and playitd for Mac
    Emergency-Meeting-<version>-windows.zip   start.bat and playitd for Windows
    Emergency-Meeting-<version>-linux.zip     start.sh and playitd for Linux

Each one has the server and only the files that system needs. playitd for
Windows and Linux is downloaded from playit.gg's GitHub page (the version in
playit/VERSION). GitHub Actions runs this by itself when a release is
published (.github/workflows/release-files.yml), and puts the files under
"Assets" on the release.

Run it by hand with:  python3 tools/make_release.py [--out dist]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that only one system needs (everything else goes in all three)
ONLY_FOR = {
    "macos": ["*.command", "playit/playitd-macos"],
    "windows": ["start.bat"],
    "linux": ["start.sh"],
}
# playit.gg's own playitd files, and the name they get in playit/
PLAYITD = {
    "windows": ("playitd-windows-x86_64.exe", "playitd-windows-x86_64.exe"),
    "linux": ("playit-linux-amd64", "playitd-linux-amd64"),
}
RUNNABLE = re.compile(r"(\.command|\.sh|playit/playitd-[^/]*)$")


def version() -> str:
    text = (ROOT / "server" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def tracked_files() -> list:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [name for name in out.decode("utf-8").split("\0") if name]


def belongs_to(name: str, system: str) -> bool:
    """Does the file go in the zip for this system?"""
    if name.startswith((".github/", ".git")):
        return False  # only for GitHub
    for other, patterns in ONLY_FOR.items():
        if any(Path(name).match(pattern) for pattern in patterns):
            return other == system
    return True


def add(z: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
    info.create_system = 3  # Unix, so that the file permissions below are kept
    info.external_attr = (0o100755 if RUNNABLE.search(arcname) else 0o100644) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(info, data)


def download_playitd(system: str, cache: Path) -> tuple:
    asset, name = PLAYITD[system]
    target = cache / name
    if not target.exists():
        playit_version = (ROOT / "playit" / "VERSION").read_text(encoding="utf-8").strip()
        url = f"https://github.com/playit-cloud/playit-agent/releases/download/v{playit_version}/{asset}"
        print(f"Downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as response:
            target.write_bytes(response.read())
    return name, target.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="dist", help="the folder for the zip files")
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "downloads"
    cache.mkdir(exist_ok=True)

    v = version()
    top = f"Emergency-Meeting-{v}"
    files = tracked_files()
    for system in ("macos", "windows", "linux"):
        path = out / f"{top}-{system}.zip"
        with zipfile.ZipFile(path, "w") as z:
            for name in files:
                source = ROOT / name
                if not belongs_to(name, system) or not source.is_file():
                    continue
                data = source.read_bytes()
                if name.endswith(".bat"):  # Windows needs CRLF
                    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                add(z, f"{top}/{name}", data)
            if system in PLAYITD:
                name, data = download_playitd(system, cache)
                add(z, f"{top}/playit/{name}", data)
        print(f"{path.name}: {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    sys.exit(main())
