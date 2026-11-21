#!/bin/sh
# Builds docs/images/gallery/E3_<map>.jpg (field maps) and the E.S. renders
# from Disc 1.
#   sh docs/gallery/make_maps.sh "Disc 1.iso" [work-dir]
# Maps: `cli.py model` on mdl\map\cf\E3_<map>.map -> render_gallery.py `map`
# (raised three-quarter view, sky shells hidden, back faces culled, 1600x1000)
# -> 960x600 JPEG. E.S.: mdl\rob\pcr\M3<name>.chr -> `char` -> 480x672 JPEG.
# Ported from the Episode II kit's gallery flow (render_gallery.py as-is).
set -e
ISO="$1"; WORK="${2:-out/gallery}"
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
OUT="$KIT/docs/images/gallery"
mkdir -p "$WORK" "$OUT"
render() {  # disc-path stem kind size
  python3 "$KIT/cli.py" model --iso "$ISO" --path "$1" --out "$WORK/$2.glb"
  "$BLENDER" -b --factory-startup --python "$KIT/docs/gallery/render_gallery.py" -- \
      "$WORK/$2.glb" "$WORK/$2.png" "$3" >/dev/null
  ffmpeg -loglevel error -y -i "$WORK/$2.png" -vf "scale=$4" -q:v 3 "$OUT/$2.jpg"
}
for m in ${MAPS:-CIT01 ELS05 KYM02 KYO06 SYU01 HOS01}; do
  render "mdl\\map\\cf\\E3_$m.map" "E3_$m" map 960:600
done
for e in ${ES:-asher01 zebulun01 reuben01}; do
  render "mdl\\rob\\pcr\\M3$e.chr" "M3$e" char 480:672
done
