#!/usr/bin/env bash
# Xenosaga III translation editor — Linux launcher.
# Opens the translation editor directly (the same program as launch.sh,
# started on the editor page instead of the extractor cards).
exec "$(dirname "$0")/launch.sh" --editor "$@"
