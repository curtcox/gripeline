#!/bin/sh
# Install from a reviewed checkout. Override with GRIPELINE_BIN_DIR.
set -eu
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
dest=${GRIPELINE_BIN_DIR:-"$HOME/.local/bin"}
mkdir -p "$dest"
cp "$src/gripeline.py" "$src/gripeline" "$dest/"
chmod +x "$dest/gripeline"
printf 'Installed gripeline in %s. Add that directory to PATH if needed.\n' "$dest"
