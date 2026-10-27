#!/bin/bash
# Dubbelklicka på den här filen i Finder för att starta servern.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 saknas. Ladda ner det från https://www.python.org/downloads/macos/"
    read -r -p "Tryck Enter för att stänga..."
    exit 1
fi

python3 -m server
read -r -p "Tryck Enter för att stänga..."
