#!/usr/bin/env bash
# Xenosaga III Extractor — macOS double-click launcher.
# A `.command` file is auto-opened by Terminal when double-clicked in Finder.
# Make it executable once if needed: `chmod +x launch.command`.
# The kit needs numpy, Pillow, capstone, fonttools and uharfbuzz
# (requirements.txt). If the Python found here lacks any of them, the first
# run makes a private environment in .venv/ beside this file and installs
# them there; later runs use that environment.
# (Launcher pattern borrowed from Xenosaga2PythonExtractor/launch.command;
# changed: checks all five requirements instead of numpy alone.)
set -e
cd "$(dirname "$0")"
REQ_CHECK="import numpy, PIL, capstone, fontTools, uharfbuzz"
BASE=""
if command -v python3 >/dev/null 2>&1; then BASE=python3
elif command -v python >/dev/null 2>&1; then BASE=python
fi
PY="$BASE"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi
if [ -z "$PY" ]; then
    echo "Python 3 is not installed."
    echo "Install Python 3 from https://www.python.org/downloads/macos/ or via brew (brew install python),"
    echo "then double-click this launcher again."
    read -p "Press Enter to close..."
    exit 1
fi
if ! "$PY" -c "$REQ_CHECK" >/dev/null 2>&1; then
    echo "Setting up the kit's requirements (numpy, Pillow, capstone, fonttools, uharfbuzz) in .venv/ ..."
    if ! { { [ -x .venv/bin/python ] || "${BASE:-$PY}" -m venv .venv; } \
           && .venv/bin/python -m pip install --quiet -r requirements.txt \
           && .venv/bin/python -c "$REQ_CHECK"; }; then
        echo "Could not install the requirements automatically. Install them yourself with"
        echo "    ${BASE:-python3} -m pip install -r requirements.txt"
        echo "then double-click this launcher again."
        read -p "Press Enter to close..."
        exit 1
    fi
    PY=.venv/bin/python
fi
exec "$PY" gui.py "$@"
