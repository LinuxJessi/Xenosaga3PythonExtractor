#!/bin/sh
# Builds docs/images/gallery/<name>.jpg (character portraits) from Disc 1.
#   sh docs/gallery/make_portraits.sh "Disc 1.iso" [work-dir]
# Each model: `cli.py model` -> .glb -> render_gallery.py (char, Eevee,
# 1000x1400) -> ffmpeg scale to 480x672 JPEG.
# Ported from the Episode II kit's gallery flow (its render_gallery.py is
# used as-is); the model lists below are this kit's own.
set -e
ISO="$1"; WORK="${2:-out/gallery}"
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
OUT="$KIT/docs/images/gallery"
mkdir -p "$WORK" "$OUT"
render() {  # dir name
  python3 "$KIT/cli.py" model --iso "$ISO" --path "mdl\\chr\\$1\\C3$2.chr" --out "$WORK/$2.glb"
  "$BLENDER" -b --factory-startup --python "$KIT/docs/gallery/render_gallery.py" -- \
      "$WORK/$2.glb" "$WORK/$2.png" char >/dev/null
  ffmpeg -loglevel error -y -i "$WORK/$2.png" -vf scale=480:672 -q:v 3 "$OUT/$2.jpg"
}
# Playable characters
for n in ${PCS:-kosmos00 shion00 jr00 momo00 chaos00 ziggy00 jin00 allen00 canan00 miyuki00}; do render pc "$n"; done
# Notable NPCs
for n in ${NPCS:-virhelm00 telos00 mary00 shelley00 marglis00 pelegri00 nephilim00 sergius00 yuriev00 albelt00}; do render npc "$n"; done
