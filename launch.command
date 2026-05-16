#!/usr/bin/env bash
# Xenosaga III Extractor — macOS double-click launcher.
# A `.command` file is auto-opened by Terminal when double-clicked in Finder.
# Make it executable once: `chmod +x launch.command`.
set -e
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
    exec python3 gui.py "$@"
fi
if command -v python >/dev/null 2>&1; then
    exec python gui.py "$@"
fi
echo "Python 3 is not installed."
echo "Install Python 3 from https://www.python.org/downloads/macos/ or via brew (brew install python),"
echo "then double-click this launcher again."
read -p "Press Enter to close..."
exit 1
