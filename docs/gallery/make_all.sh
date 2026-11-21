#!/bin/sh
# Rebuilds every picture and clip added for the front page, in order.
#   sh docs/gallery/make_all.sh "Disc 1.iso" "Disc 2.iso" [work-dir]
# Needs Blender (BLENDER=... or /Applications/Blender.app), ffmpeg, Pillow,
# and for the window shot Playwright + Google Chrome.
#   make_portraits.sh  docs/images/gallery/<model>.jpg   party + NPC portraits
#   make_maps.sh       docs/images/gallery/E3_*.jpg, M3*.jpg   field maps, E.S.
#   make_tour.py       docs/images/tour/*                movie frame, UI, font, synopsis, textures
#   make_gui_shot.sh   docs/images/tour/gui-window.png   the window, stand-in discs
#   make_samples.sh    docs/samples/voice_s*.mp3, bgm_a01/b01.mp3
set -e
D="$(dirname "$0")"; W="${3:-out/gallery}"
sh "$D/make_portraits.sh" "$1" "$W/models"
sh "$D/make_maps.sh" "$1" "$W/models"
python3 "$D/make_tour.py" "$1" "$W/tour"
sh "$D/make_gui_shot.sh"
sh "$D/make_samples.sh" "$1" "$2" "$W/samples"
