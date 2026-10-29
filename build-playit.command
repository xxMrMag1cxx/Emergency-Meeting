#!/bin/bash
# Builds playitd (playit.gg's tunnel program) on this Mac.
# Only needed if playit/playitd-macos is missing or can't be started.
# Takes 5-15 minutes the first time.
cd "$(dirname "$0")" || exit 1
PROJECT="$(pwd)"
VERSION="$(tr -d '[:space:]' < playit/VERSION)"

stop() {
    echo
    echo "$1"
    read -r -p "Press Enter to close..."
    exit 1
}

echo "Building playitd $VERSION ..."
echo

# 1. Apple's developer tools (needed to build programs)
if ! xcode-select -p >/dev/null 2>&1; then
    echo "The Mac needs Apple's developer tools (Command Line Tools)."
    echo "A window opens now: click Install and wait until it's done."
    xcode-select --install
    stop "Then double-click build-playit.command again."
fi

# 2. Rust (the programming language playitd is written in)
[ -x "$HOME/.cargo/bin/cargo" ] && export PATH="$HOME/.cargo/bin:$PATH"
if ! command -v cargo >/dev/null 2>&1; then
    echo "Installing Rust ..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
        || stop "Rust could not be installed. Check the internet connection and try again."
    export PATH="$HOME/.cargo/bin:$PATH"
fi
rustup update stable >/dev/null 2>&1

# 3. Download the source code and build
WORK="$(mktemp -d)"
echo "Downloading the source code of playit-agent $VERSION ..."
curl -fL --progress-bar -o "$WORK/src.tar.gz" \
    "https://github.com/playit-cloud/playit-agent/archive/refs/tags/v$VERSION.tar.gz" \
    || stop "The source code could not be downloaded. Check the internet connection and try again."
tar -xzf "$WORK/src.tar.gz" -C "$WORK" || stop "The source code could not be unpacked."

echo "Building (this takes a while) ..."
(cd "$WORK/playit-agent-$VERSION" && MACOSX_DEPLOYMENT_TARGET=11.0 cargo build --release --locked -p playitd) \
    || stop "The build failed. Report it with the error message above at https://github.com/xxMrMag1cxx/Emergency-Meeting/issues"

cp "$WORK/playit-agent-$VERSION/target/release/playitd" "$PROJECT/playit/playitd-macos"
cp "$WORK/playit-agent-$VERSION/LICENSE.txt" "$PROJECT/playit/LICENSE-playit.txt"
chmod +x "$PROJECT/playit/playitd-macos"
rm -rf "$WORK"

echo
if "$PROJECT/playit/playitd-macos" --help >/dev/null 2>&1; then
    echo "Done! Restart the server (start.command)."
else
    echo "playitd was built but could not be started. Report it with this text at https://github.com/xxMrMag1cxx/Emergency-Meeting/issues"
fi
read -r -p "Press Enter to close..."
