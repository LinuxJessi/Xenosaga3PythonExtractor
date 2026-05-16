#!/usr/bin/env bash
# Xenosaga III Extractor — Linux double-click launcher.
# Make sure this file is executable: `chmod +x launch.sh`.
set -e
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
    exec python3 gui.py "$@"
fi
if command -v python >/dev/null 2>&1; then
    exec python gui.py "$@"
fi
echo "Python 3 is not installed on this machine."
echo "Install it from your distribution's package manager, then run this script again."
read -p "Press Enter to close..."
exit 1
