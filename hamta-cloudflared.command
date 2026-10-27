#!/bin/bash
# Dubbelklicka för att hämta cloudflared, som ger servern en HTTPS-adress.
# Behöver bara göras en gång. Programmet hamnar i projektmappen.
cd "$(dirname "$0")" || exit 1

MACOS=$(sw_vers -productVersion | cut -d. -f1)
CHIP=$(uname -m)   # arm64 = Apple-chip (M1, M2 ...), x86_64 = Intel

# De senaste versionerna av cloudflared kräver macOS 15. För äldre Macar
# använder vi version 2025.4.0, den senaste som fungerar på macOS 12-14.
# Den finns för Apple-chip bara från macOS 13, så på macOS 12 med
# Apple-chip används Intel-versionen (den körs via Rosetta).
if [ "$MACOS" -ge 15 ]; then
    BASE="https://github.com/cloudflare/cloudflared/releases/latest/download"
    [ "$CHIP" = "arm64" ] && FILE="cloudflared-darwin-arm64.tgz" || FILE="cloudflared-darwin-amd64.tgz"
else
    BASE="https://github.com/cloudflare/cloudflared/releases/download/2025.4.0"
    if [ "$CHIP" = "arm64" ] && [ "$MACOS" -ge 13 ]; then
        FILE="cloudflared-darwin-arm64.tgz"
    else
        FILE="cloudflared-darwin-amd64.tgz"
    fi
fi

echo "macOS $MACOS, processor $CHIP"
echo "Hämtar $BASE/$FILE ..."
if ! curl -fL --progress-bar -o cloudflared.tgz "$BASE/$FILE"; then
    echo
    echo "Det gick inte att hämta filen. Kolla internetanslutningen och försök igen."
    read -r -p "Tryck Enter för att stänga..."
    exit 1
fi

rm -f cloudflared
tar -xzf cloudflared.tgz && rm -f cloudflared.tgz
chmod +x cloudflared

echo
if ./cloudflared --version; then
    echo
    echo "Klart! Starta om servern (start.command) så får den en HTTPS-adress."
elif [ "$CHIP" = "arm64" ] && [ "$FILE" = "cloudflared-darwin-amd64.tgz" ]; then
    echo "Den här Macen behöver Rosetta för att köra cloudflared."
    echo "Installerar Rosetta (du kan behöva skriva ditt lösenord)..."
    softwareupdate --install-rosetta --agree-to-license
    ./cloudflared --version && echo "Klart! Starta om servern (start.command)."
else
    echo "cloudflared hämtades men gick inte att starta på den här Macen."
    echo "Skicka det här felmeddelandet till Claude så hittar vi en lösning."
fi
read -r -p "Tryck Enter för att stänga..."
