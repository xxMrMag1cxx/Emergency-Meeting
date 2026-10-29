#!/bin/bash
# Double-click to test the server (the server must be running in another window).
cd "$(dirname "$0")" || exit 1
python3 tools/testclient.py
read -r -p "Press Enter to close..."
