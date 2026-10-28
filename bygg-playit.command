#!/bin/bash
# Bygger playitd (playit.gg:s tunnelprogram) på den här Macen.
# Behövs bara om playit/playitd-macos saknas eller inte går att starta.
# Tar 5-15 minuter första gången.
cd "$(dirname "$0")" || exit 1
PROJECT="$(pwd)"
VERSION="$(tr -d '[:space:]' < playit/VERSION)"

stop() {
    echo
    echo "$1"
    read -r -p "Tryck Enter för att stänga..."
    exit 1
}

echo "Bygger playitd $VERSION ..."
echo

# 1. Apples utvecklarverktyg (behövs för att bygga program)
if ! xcode-select -p >/dev/null 2>&1; then
    echo "Macen behöver Apples utvecklarverktyg (Command Line Tools)."
    echo "Ett fönster öppnas nu: klicka på Installera och vänta tills det är klart."
    xcode-select --install
    stop "Dubbelklicka sedan på bygg-playit.command igen."
fi

# 2. Rust (programspråket som playitd är skrivet i)
[ -x "$HOME/.cargo/bin/cargo" ] && export PATH="$HOME/.cargo/bin:$PATH"
if ! command -v cargo >/dev/null 2>&1; then
    echo "Installerar Rust ..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
        || stop "Det gick inte att installera Rust. Kolla internetanslutningen och försök igen."
    export PATH="$HOME/.cargo/bin:$PATH"
fi
rustup update stable >/dev/null 2>&1

# 3. Hämta källkoden och bygg
WORK="$(mktemp -d)"
echo "Hämtar källkoden till playit-agent $VERSION ..."
curl -fL --progress-bar -o "$WORK/src.tar.gz" \
    "https://github.com/playit-cloud/playit-agent/archive/refs/tags/v$VERSION.tar.gz" \
    || stop "Det gick inte att hämta källkoden. Kolla internetanslutningen och försök igen."
tar -xzf "$WORK/src.tar.gz" -C "$WORK" || stop "Det gick inte att packa upp källkoden."

echo "Bygger (det här tar en stund) ..."
(cd "$WORK/playit-agent-$VERSION" && MACOSX_DEPLOYMENT_TARGET=11.0 cargo build --release --locked -p playitd) \
    || stop "Bygget misslyckades. Skicka felmeddelandet ovan till Claude så hittar vi en lösning."

cp "$WORK/playit-agent-$VERSION/target/release/playitd" "$PROJECT/playit/playitd-macos"
cp "$WORK/playit-agent-$VERSION/LICENSE.txt" "$PROJECT/playit/LICENSE-playit.txt"
chmod +x "$PROJECT/playit/playitd-macos"
rm -rf "$WORK"

echo
if "$PROJECT/playit/playitd-macos" --help >/dev/null 2>&1; then
    echo "Klart! Starta om servern (start.command)."
else
    echo "playitd byggdes men gick inte att starta. Skicka det här till Claude."
fi
read -r -p "Tryck Enter för att stänga..."
