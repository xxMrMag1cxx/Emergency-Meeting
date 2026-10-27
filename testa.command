#!/bin/bash
# Dubbelklicka för att testa servern (servern måste vara igång i ett annat fönster).
cd "$(dirname "$0")" || exit 1
python3 tools/testklient.py
read -r -p "Tryck Enter för att stänga..."
