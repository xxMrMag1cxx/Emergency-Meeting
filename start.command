#!/bin/bash
# Double-click this file in Finder to start the server.
cd "$(dirname "$0")" || exit 1

# The last line is shown in the server's language (the "language" setting in config.json).
close_text() {
    if grep -qiE '"language": *"(swedish|svenska|sv)"' config.json 2>/dev/null; then
        echo "Tryck Enter för att stänga..."
    else
        echo "Press Enter to close..."
    fi
}

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is missing. Download it from https://www.python.org/downloads/macos/"
    read -r -p "$(close_text)"
    exit 1
fi

python3 -m server
read -r -p "$(close_text)"
