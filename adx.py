"""adx.py — CRI ADX stream headers, and which streams are Episode III's soundtrack.

Episode III has no sequenced music to render (Episode I has Procyon SMD/SWD
sequences, Episode II Standard MIDI files on a KORG driver; both kits turn
those into MIDI, SoundFont and WAV). Here the music is recorded: 120 stereo
ADX streams that sit directly in ``snd\\adx\\``, beside the folders of voice
and event streams. Counted on the five images, 2026-11-21 (USA Disc 1 and 2,
Japan Disc 1 and 2, the May 2006 prototype), the same on every one::

    snd\\adx\\*.adx     120 streams, 3.31 hours; 44 at 48,000 Hz, 76 at 24,000 Hz;
                      114 carry a loop, 6 play once
    by first letter   A 1, B 17, C 33, E 53, M 10, S 6

The other ADX folders are not music: ``mev\\`` (scene voice), ``bat_voice\\``,
``evt\\`` (event scenes' audio tracks), ``sys\\`` (twelve short system sounds) and, on
the Japanese discs only, ``arasuji\\`` (70 streams).

Header (big-endian; CRI's published layout, the fields this module reads)::

    0x00  u16 0x8000
    0x02  u16 offset of the "(c)CRI" signature's end minus 4: audio starts at +4
    0x04  u8 encoding (3 = the standard 4-bit ADPCM)   0x05 u8 block size (18)
    0x06  u8 bits per sample (4)                       0x07 u8 channels
    0x08  u32 sample rate      0x0C u32 samples per channel
    0x10  u16 high-pass cutoff 0x12 u8 version (3 or 4)  0x13 u8 flags
    loop block at 0x14 (version 3) or 0x20 (version 4):
      +0x04 u32 loop flag (1 = looped)
      +0x08 u32 loop start sample   +0x10 u32 loop end sample

Every soundtrack stream on the discs is version 4, encoding 3, stereo. The
loop fields are checked before they are believed (start < end <= samples);
a header that fails is reported as not looped with a note, never guessed.

``browse --kinds music`` (browse_bundle.py) writes the 120 streams as WAV
under ``music/`` with ``music/music.csv`` (this module's table); ffmpeg
decodes a stream once through, so the loop points are in the table, not in
the WAV. ``music-list --iso DISC.iso`` prints the table straight from a disc.
"""
from __future__ import annotations

import re
import struct
import sys
from dataclasses import dataclass
from typing import List, Optional

_SOUNDTRACK = re.compile(r"^snd\\adx\\[^\\]+\.adx$", re.I)

CSV_HEADER = ("track", "path", "bytes", "sample_rate", "channels", "samples", "seconds",
              "looped", "loop_start_sample", "loop_end_sample", "loop_start_seconds",
              "loop_end_seconds", "note")


class AdxError(ValueError):
    """The bytes are not an ADX stream header."""


@dataclass(frozen=True)
class Header:
    rate: int
    channels: int
    samples: int
    version: int
    encoding: int
    data_offset: int
    looped: bool
    loop_start: Optional[int]
    loop_end: Optional[int]
    note: str = ""

    @property
    def seconds(self) -> float:
        return self.samples / self.rate if self.rate else 0.0


def is_soundtrack(game_path: str) -> bool:
    """True for a stream directly in ``snd\\adx\\`` (the soundtrack); the voice,
    event and system folders below it are not music."""
    return bool(_SOUNDTRACK.match(game_path.replace("/", "\\").lstrip("\\")))


def parse_header(data: bytes) -> Header:
    if len(data) < 0x14 or data[:2] != b"\x80\x00":
        raise AdxError("not an ADX stream (no 0x8000 at the start)")
    copyright_off, = struct.unpack_from(">H", data, 2)
    encoding, _block, _bits, channels = data[4], data[5], data[6], data[7]
    rate, samples = struct.unpack_from(">II", data, 8)
    version = data[0x12]
    if not rate or not channels:
        raise AdxError("ADX header with no sample rate or no channels")
    looped, start, end, note = False, None, None, ""
    base = {3: 0x14, 4: 0x20}.get(version)
    if base is None:
        note = f"version {version}: loop block not read"
    elif len(data) >= base + 0x14 and copyright_off + 4 >= base + 0x14:
        flag, = struct.unpack_from(">I", data, base + 4)
        s, = struct.unpack_from(">I", data, base + 8)
        e, = struct.unpack_from(">I", data, base + 0x10)
        if flag == 1:
            if s < e <= samples:
                looped, start, end = True, s, e
            else:
                note = f"loop flag set but its points do not fit ({s}..{e} of {samples})"
        elif flag != 0:
            note = f"loop flag {flag:#x} not understood"
    return Header(rate, channels, samples, version, encoding, copyright_off + 4, looped, start, end, note)


def table_row(game_path: str, data: bytes, nbytes: Optional[int] = None) -> List[str]:
    """One ``music.csv`` row; ``data`` need only hold the header (0x40 bytes)."""
    h = parse_header(data)
    name = game_path.replace("/", "\\").rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    return [name, game_path, str(len(data) if nbytes is None else nbytes), str(h.rate), str(h.channels),
            str(h.samples), f"{h.seconds:.3f}", "yes" if h.looped else "no",
            "" if h.loop_start is None else str(h.loop_start),
            "" if h.loop_end is None else str(h.loop_end),
            "" if h.loop_start is None else f"{h.loop_start / h.rate:.3f}",
            "" if h.loop_end is None else f"{h.loop_end / h.rate:.3f}", h.note]


def disc_table(iso_path: str) -> List[List[str]]:
    """The soundtrack table of a disc image, in path order."""
    from disc import Disc
    rows = []
    with Disc(iso_path) as d:
        for _chain, e in d.entries():
            if is_soundtrack(e.path) and e.size:
                data = d.read(e.path)
                rows.append(table_row(e.path, data[:0x40], len(data)))
    rows.sort(key=lambda r: r[1].lower())
    return rows


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("music-list", help="the soundtrack streams of a disc (snd\\adx\\*.adx): "
                              "rate, length and loop points, as a table or CSV")
    p.add_argument("--iso", required=True, help="disc image (read only)")
    p.add_argument("--csv", help="also write the table to this CSV file")

    def run(a):
        rows = disc_table(a.iso)
        if not rows:
            print("no soundtrack streams found (snd\\adx\\*.adx)")
            return 1
        for r in rows:
            loop = f"loop {r[10]}-{r[11]} s" if r[7] == "yes" else "plays once"
            print(f"{r[0]:<10} {int(r[3]):>6} Hz  {r[4]} ch  {float(r[6]):8.1f} s  {loop}"
                  + (f"  [{r[12]}]" if r[12] else ""))
        total = sum(float(r[6]) for r in rows)
        print(f"{len(rows)} streams, {total / 3600:.2f} hours, "
              f"{sum(1 for r in rows if r[7] == 'yes')} looped")
        if a.csv:
            import csv
            with open(a.csv, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(CSV_HEADER)
                w.writerows(rows)
            print(f"wrote {a.csv}")
        return 0
    p.set_defaults(func=run)


def _synthetic(version: int = 4, flag: int = 1, start: int = 1000, end: int = 48000,
               samples: int = 48000, rate: int = 48000, channels: int = 2) -> bytes:
    base = {3: 0x14, 4: 0x20}.get(version, 0x20)
    size = base + 0x18
    h = bytearray(size + 6)
    struct.pack_into(">HH", h, 0, 0x8000, size - 4 + 6)
    h[4:8] = bytes((3, 18, 4, channels))
    struct.pack_into(">II", h, 8, rate, samples)
    h[0x12] = version
    struct.pack_into(">I", h, base + 4, flag)
    struct.pack_into(">I", h, base + 8, start)
    struct.pack_into(">I", h, base + 0x10, end)
    h[-6:] = b"(c)CRI"
    return bytes(h)


def self_test() -> int:
    import os
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok = ok and bool(cond)

    h = parse_header(_synthetic())
    check((h.rate, h.channels, h.samples, h.looped, h.loop_start, h.loop_end) ==
          (48000, 2, 48000, True, 1000, 48000), "version 4 header: rate, channels, samples, loop")
    h3 = parse_header(_synthetic(version=3, start=5, end=10, samples=20, rate=24000))
    check(h3.looped and (h3.loop_start, h3.loop_end) == (5, 10) and abs(h3.seconds - 20 / 24000) < 1e-9,
          "version 3 header: the loop block sits at 0x14")
    check(not parse_header(_synthetic(flag=0)).looped, "loop flag 0 plays once")
    bad = parse_header(_synthetic(start=50000, end=40000))
    check(not bad.looped and "do not fit" in bad.note, "loop points that do not fit are reported, not used")
    try:
        parse_header(b"RIFF" + bytes(64))
        check(False, "a WAV is refused")
    except AdxError:
        check(True, "a file that is not ADX is refused")
    check(is_soundtrack("snd\\adx\\B01.adx") and is_soundtrack("snd/adx/C01B.adx")
          and not is_soundtrack("snd\\adx\\mev\\s010100_01.adx") and not is_soundtrack("snd\\adx\\sys\\system01.adx"),
          "the soundtrack is the streams directly in snd\\adx\\")
    row = table_row("snd\\adx\\B01.adx", _synthetic(), 1234)
    check(len(row) == len(CSV_HEADER) and row[0] == "B01" and row[2] == "1234" and row[7] == "yes",
          "music.csv row shape")
    iso = os.environ.get("XS3_D1")
    if iso and os.path.exists(iso):
        rows = disc_table(iso)
        looped = sum(1 for r in rows if r[7] == "yes")
        hours = sum(float(r[6]) for r in rows) / 3600
        check(len(rows) == 120 and looped == 114 and not any(r[12] for r in rows),
              f"XS3_D1: {len(rows)} soundtrack streams, {looped} looped, {hours:.2f} hours, no header notes")
    else:
        print("skip  disc check (XS3_D1 not set)")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
