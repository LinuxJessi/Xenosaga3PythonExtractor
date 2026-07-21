#!/usr/bin/env python3
"""fmv_sfd.py — Xenosaga III SofDec (.sfd) demux / splice core.

An `.sfd` cutscene is a **sector-aligned (2048-byte pack-per-sector) MPEG-1
Program Stream**: video in PES stream 0xE0 (`mpeg1video` 512x320), CRI **ADX**
audio in PES stream 0xC0, padding in 0xBE. ffmpeg decodes both but cannot
*mux* ADX back, so an HD replacement can't be a plain ffmpeg remux — it must
substitute the video stream while preserving the ADX audio and all pack/timing
bytes verbatim. This module does exactly that.

Model: parse the PS into units and record the byte span of every video (0xE0)
*payload*. The "video elementary stream" is the concatenation of those spans;
everything else (packs, system headers, ADX packets, padding) is left untouched.

- `demux(data)`            -> (video_es, audio_es, video_spans, audio_spans)
- `splice(data, new_es)`   -> new .sfd; substitutes video payloads in place.
                              Requires len(new_es) == len(original video_es),
                              which keeps the container byte-for-byte except the
                              video payload bytes (sector framing preserved).
- `pad_video_es(es, n)`    -> zero-pad a shorter re-encoded ES up to the budget
                              (trailing stuffing after the sequence-end code is
                              ignored by the decoder) so it can be spliced.

Round-trip identity (the proof): `splice(data, demux(data)[0]) == data`.

Growing a movie past its original byte budget (true higher bitrate/res) needs
a repacketizing muxer + the disc-side append/repoint from docs/REPACK.md — that
is the next rung and is out of scope for this splice core. See
docs/FMV-HD-SCHEME.md.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

VIDEO_SID = 0xE0        # MPEG video stream 0
AUDIO_SID = 0xC0        # audio stream 0 (carries CRI ADX here)


def iter_units(data: bytes):
    """Yield every Program-Stream unit as a dict, covering every byte with no
    gaps. Kinds: 'pack', 'system', 'end', 'pes', 'tail'. PES units carry
    'payload_start'/'payload_end'."""
    i, n = 0, len(data)
    while i + 4 <= n:
        if data[i:i + 3] != b"\x00\x00\x01":
            # tolerated only as trailing sector fill (MPEG stuffing: 0x00/0xFF)
            if set(data[i:]) <= {0x00, 0xFF}:
                yield {"kind": "tail", "start": i, "end": n}
                return
            raise ValueError(f"lost sync at 0x{i:x}: {data[i:i+4].hex()}")
        sid = data[i + 3]
        if sid == 0xBA:                       # pack header
            b4 = data[i + 4]
            if (b4 & 0xF0) == 0x20:           # MPEG-1 pack: 12 bytes
                size = 12
            elif (b4 & 0xC0) == 0x40:         # MPEG-2 pack: 14 + stuffing
                size = 14 + (data[i + 13] & 0x07)
            else:
                raise ValueError(f"bad pack marker at 0x{i:x}: {b4:02x}")
            yield {"kind": "pack", "sid": sid, "start": i, "end": i + size}
            i += size
        elif sid == 0xB9:                     # program end code
            yield {"kind": "end", "sid": sid, "start": i, "end": i + 4}
            i += 4
        elif sid == 0xBB:                     # system header
            ln = struct.unpack_from(">H", data, i + 4)[0]
            size = 6 + ln
            yield {"kind": "system", "sid": sid, "start": i, "end": i + size}
            i += size
        else:                                 # PES packet
            ln = struct.unpack_from(">H", data, i + 4)[0]
            pstart, pend = i + 6, i + 6 + ln
            payload = pstart
            if sid not in (0xBE, 0xBF):        # padding / private_stream_2: no PES header
                j = pstart
                k = 0
                while j < pend and data[j] == 0xFF and k < 16:  # stuffing
                    j += 1
                    k += 1
                if j < pend and (data[j] & 0xC0) == 0x40:       # STD buffer scale/size
                    j += 2
                if j < pend:
                    flag = data[j]
                    if (flag & 0xF0) == 0x20:      # PTS
                        j += 5
                    elif (flag & 0xF0) == 0x30:    # PTS + DTS
                        j += 10
                    elif flag == 0x0F:             # no PTS/DTS marker
                        j += 1
                payload = j
            yield {"kind": "pes", "sid": sid, "start": i, "end": pend,
                   "payload_start": payload, "payload_end": pend}
            i = pend
    if i != n:
        yield {"kind": "tail", "start": i, "end": n}


def demux(data: bytes):
    """Return (video_es, audio_es, video_spans, audio_spans). *_spans are lists
    of (start,end) byte ranges into `data`."""
    vid, aud = bytearray(), bytearray()
    vspans, aspans = [], []
    covered = 0
    for u in iter_units(data):
        covered += u["end"] - u["start"]
        if u["kind"] == "pes":
            if u["sid"] == VIDEO_SID:
                vspans.append((u["payload_start"], u["payload_end"]))
                vid += data[u["payload_start"]:u["payload_end"]]
            elif u["sid"] == AUDIO_SID:
                aspans.append((u["payload_start"], u["payload_end"]))
                aud += data[u["payload_start"]:u["payload_end"]]
    if covered != len(data):
        raise ValueError(f"unit coverage {covered} != file {len(data)} (parser gap)")
    return bytes(vid), bytes(aud), vspans, aspans


def video_es(data: bytes) -> bytes:
    return demux(data)[0]


def pad_video_es(es: bytes, target_len: int) -> bytes:
    """Zero-pad a re-encoded video ES up to `target_len`. The bytes fall after
    the stream's sequence-end code and are ignored by the MPEG decoder."""
    if len(es) > target_len:
        raise ValueError(f"ES {len(es)} exceeds budget {target_len}; needs the "
                         "repacketizing/grow path, not in-place splice")
    return es + b"\x00" * (target_len - len(es))


def splice(data: bytes, new_video_es: bytes) -> bytes:
    """Substitute the video payload bytes with `new_video_es` (same total
    length as the original video ES). Everything else is byte-identical."""
    vid, _aud, vspans, _asp = demux(data)
    if len(new_video_es) != len(vid):
        raise ValueError(
            f"video ES length {len(new_video_es)} != original {len(vid)}; pad it "
            "to the budget with pad_video_es(), or use the grow path")
    out = bytearray(data)
    pos = 0
    for s, e in vspans:
        L = e - s
        out[s:e] = new_video_es[pos:pos + L]
        pos += L
    return bytes(out)


# --------------------------------------------------------------------------
# self-test / CLI
# --------------------------------------------------------------------------

def _disc(iso):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repack import Disc
    return Disc(iso)


def _movie(d, discpath):
    r = d.rows.get(discpath.strip().replace("/", "\\").lower())
    if not r:
        sys.exit(f"{discpath}: not a movie on this disc")
    return r


def selftest(iso):
    d = _disc(iso)
    rows = [r for k, r in sorted(d.rows.items()) if k.endswith(".sfd")]
    print(f"{len(rows)} .sfd movies on this disc\n")
    ok = 0
    for r in rows:
        data = d.read(r)
        vid, aud, vspans, aspans = demux(data)
        identical = splice(data, vid) == data
        ok += identical
        print(f"  {r.path.split(chr(92))[-1]:14s} {len(data)/1e6:6.1f}MB  "
              f"video={len(vid)/1e6:5.1f}MB/{len(vspans)}pk  "
              f"audio={len(aud)/1e6:5.1f}MB/{len(aspans)}pk  "
              f"round-trip={'IDENTICAL' if identical else 'MISMATCH!!'}")
    print(f"\n{ok}/{len(rows)} byte-identical round-trips")
    return ok == len(rows)


def cmd_video(iso, discpath, out):
    """Extract the movie's video elementary stream (feed this to the upscaler)."""
    d = _disc(iso)
    vid = video_es(d.read(_movie(d, discpath)))
    Path(out).write_bytes(vid)
    print(f"{discpath} video ES -> {out} ({len(vid)} bytes); re-encode to "
          "mpeg1video 512x320 within this budget, keeping the frame count")


def cmd_splice(iso, discpath, new_es_path, out):
    """Splice a re-encoded video ES back in (zero-padded to the budget) and write
    a same-size .sfd ready for `repack.py patch`."""
    d = _disc(iso)
    data = d.read(_movie(d, discpath))
    budget = len(video_es(data))
    new = Path(new_es_path).read_bytes()
    if len(new) > budget:
        sys.exit(f"new video ES {len(new)} exceeds the in-place budget {budget}; "
                 "growing the movie needs the append/repoint path (docs/REPACK.md)")
    out_data = splice(data, pad_video_es(new, budget))
    assert len(out_data) == len(data)
    Path(out).write_bytes(out_data)
    print(f"spliced -> {out} ({len(new)}/{budget} bytes video, {budget-len(new)} "
          f"padded). Audio preserved verbatim. Patch it in with:\n"
          f"  python3 repack.py patch <iso> '{discpath}' {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "selftest":
        sys.exit(0 if selftest(a[1]) else 1)
    elif len(a) >= 4 and a[0] == "video":
        cmd_video(a[1], a[2], a[3])
    elif len(a) >= 5 and a[0] == "splice":
        cmd_splice(a[1], a[2], a[3], a[4])
    else:
        print(__doc__)
        print("Commands:\n"
              "  selftest <iso>                        byte-identical round-trip, all movies\n"
              "  video    <iso> <discpath> <out.m1v>   extract video ES to re-encode\n"
              "  splice   <iso> <discpath> <new.m1v> <out.sfd>   put re-encoded video back")
