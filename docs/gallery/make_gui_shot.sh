#!/bin/sh
# Builds docs/images/tour/gui-window.png: the window with two stand-in discs,
# so no real paths show. The stand-ins are sparse 4 GB files with the usual
# Redump names (they hold no data); HOME points at an empty folder so the
# scan of Downloads/Desktop/Documents finds nothing else.
#   sh docs/gallery/make_gui_shot.sh
set -e
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
B=/Users/Shared/xs3-standin
mkdir -p "$B/home"
rsync -a --exclude docs --exclude .git "$KIT/" "$B/Xenosaga3PythonExtractor/"
for d in 1 2; do
  python3 -c "import sys; open(sys.argv[1],'wb').truncate(4*1024**3)" \
    "$B/Xenosaga Episode III - Also sprach Zarathustra (USA) (Disc $d).iso"
done
UB=$(python3 -m site --user-base)
(cd "$B/Xenosaga3PythonExtractor" && HOME="$B/home" PYTHONUSERBASE="$UB" \
   python3 gui.py --no-browser --port 8792 >"$B/gui.log" 2>&1) &
sleep 3
python3 "$KIT/docs/gallery/shot_gui.py" http://127.0.0.1:8792/ "$KIT/docs/images/tour/gui-window.png"
pkill -f "gui.py --no-browser --port 8792" || true
rm -rf "$B"
