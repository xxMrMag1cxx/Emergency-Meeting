#!/bin/bash
# Starts the server on Linux. Run it in a terminal: ./start.sh
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is missing. Install it with your package manager, for example:"
    echo "  sudo apt install python3"
    exit 1
fi

exec python3 -m server
