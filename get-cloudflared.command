#!/bin/bash
# Double-click to download cloudflared, which gives the server an HTTPS address.
# Only needs to be done once. The program ends up in the project folder.
cd "$(dirname "$0")" || exit 1

MACOS=$(sw_vers -productVersion | cut -d. -f1)
CHIP=$(uname -m)   # arm64 = Apple silicon (M1, M2 ...), x86_64 = Intel

# The latest versions of cloudflared require macOS 15. For older Macs
# we use version 2025.4.0, the latest that works on macOS 12-14.
# It only exists for Apple silicon from macOS 13, so on macOS 12 with
# Apple silicon the Intel version is used (it runs through Rosetta).
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
echo "Downloading $BASE/$FILE ..."
if ! curl -fL --progress-bar -o cloudflared.tgz "$BASE/$FILE"; then
    echo
    echo "The file could not be downloaded. Check the internet connection and try again."
    read -r -p "Press Enter to close..."
    exit 1
fi

rm -f cloudflared
tar -xzf cloudflared.tgz && rm -f cloudflared.tgz
chmod +x cloudflared

echo
if ./cloudflared --version; then
    echo
    echo "Done! Restart the server (start.command) and it gets an HTTPS address."
elif [ "$CHIP" = "arm64" ] && [ "$FILE" = "cloudflared-darwin-amd64.tgz" ]; then
    echo "This Mac needs Rosetta to run cloudflared."
    echo "Installing Rosetta (you may need to type your password)..."
    softwareupdate --install-rosetta --agree-to-license
    ./cloudflared --version && echo "Done! Restart the server (start.command)."
else
    echo "cloudflared was downloaded but could not be started on this Mac."
    echo "Send this error message to Claude and we'll find a solution."
fi
read -r -p "Press Enter to close..."
