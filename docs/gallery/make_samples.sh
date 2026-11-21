#!/bin/sh
# Adds the movie voice-line clips and two more BGM excerpts to docs/samples/.
#   sh docs/gallery/make_samples.sh "Disc 1.iso" "Disc 2.iso" [work-dir]
# Voice lines: `dump` the movie, `browse --kinds movies` (SFD -> MP4, ADX
# track -> AAC), then cut the audio at the line's own subtitle timing from
# mov\us\<movie>.txt (mm:ss:ff, 30 frames a second), 0.4 s before the
# line starts to 0.6 s after it leaves the screen. The game's music and
# effects are mixed into the movie track, so they are in the clip too.
# BGM: `dump` + `browse --kinds audio` (ADX -> WAV), a 25 s excerpt from the
# start with a 2 s fade-out, the same shape as the existing bgm_*.mp3.
# The existing samples are left as they are. New for this kit.
set -e
D1="$1"; D2="$2"; WORK="${3:-out/samples}"
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$KIT/docs/samples"
mkdir -p "$WORK" "$OUT"
movie() {  # movie-id
  [ -f "$WORK/mvb/$1/movies/"*"/mov/$1.mp4" ] && return
  python3 "$KIT/cli.py" dump --iso "$D1" --iso "$D2" --out "$WORK/mv/$1" --match "mov\\$1.sfd"
  python3 "$KIT/cli.py" browse --dump "$WORK/mv/$1/dump" --stage "$WORK/mvb/$1" --kinds movies --sfd-preset ultrafast
}
clip() {  # movie-id start-seconds end-seconds out-name
  movie "$1"
  ffmpeg -loglevel error -y -ss "$2" -to "$3" -i "$WORK/mvb/$1/movies/"*"/mov/$1.mp4" -vn \
    -af "afade=t=in:d=0.05,areverse,afade=t=in:d=0.15,areverse" -c:a libmp3lame -b:a 128k "$OUT/$4.mp3"
}
#                 movie   from    to      file                           subtitle lines (start-end)
clip s030100  54.10  57.87 voice_s030100_do_it_anytime          # 00:54:15 "Do it anytime, KOS-MOS!" / 00:56:00 "Acknowledged." (-00:57:08)
clip s031300 415.10 419.27 voice_s031300_i_am_order             # 06:55:15 "I am order!" / 06:57:05 "Not you, KOS-MOS!" (+1:15)
clip s083110  17.27  20.17 voice_s083110_fear_drives_evolution  # 00:17:20 "Fear drives evolution." (-00:19:17)
clip s093500 119.43 125.87 voice_s093500_zarathustra_shall_speak # 01:59:25 "When Mary fulfills her duty," / 02:02:28 "Zarathustra shall speak!" (-02:05:08)
clip s094820 107.27 114.60 voice_s094820_i_am_not_mary          # 01:47:20 "I am not Mary." / 01:50:27 "I am..." / 01:52:25 "KOS-MOS!" (-01:54:00)
for a in A01 B01; do
  python3 "$KIT/cli.py" dump --iso "$D1" --out "$WORK/adx/$a" --match "snd\\adx\\$a.adx"
  python3 "$KIT/cli.py" browse --dump "$WORK/adx/$a/dump" --stage "$WORK/adxb/$a" --kinds audio
  low=$(echo "$a" | tr 'A-Z' 'a-z')
  ffmpeg -loglevel error -y -t 25 -i "$WORK/adxb/$a/audio/chain0/snd/adx/$a.wav" \
    -af "afade=t=out:st=23:d=2" -c:a libmp3lame -b:a 128k "$OUT/bgm_$low.mp3"
done
