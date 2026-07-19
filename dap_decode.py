"""
dap_decode.py — Decode ``.dap`` CRI/SEGA DTPK sound banks into per-cue WAVs.

The 607 ``.dap`` files per disc (``snd/dat/``, ``mg1/com/Sound/``) are PS2
DTPK driver banks. Layout (all little-endian), reversed from the retail
files — every structural claim below was verified across MER06.dap (6
samples), Master.dap (4 segments, 55 samples) and MIK03.dap (0 samples):

    0x00   u32 0x14, then zeros — 0x40-byte file preamble
    0x40   first DTPK segment; a file is a chain of segments

Each segment:

    +0x00  8   magic "ps2_DTPK"
    +0x08  u32 version (0x4C02 on both discs)
    +0x0C  u32 segment size (next segment starts at seg + size)
    +0x60  8   magic "ps2_TBLD" — driver tables: programs, tones, sequences
    +0xB8  u32 sample-table pointer, segment-relative; 0 when the segment
               has no PCM data (pure sequence/definition banks)

Sample table (at seg + pointer):

    +0x00  u32 sample count - 1
    +0x04  16-byte records: {u32 offset, u32 pad, u16 flags, u16 rate_hz,
                             u32 length}

``offset``/``length`` address the segment's ``ps2_VAGD`` chunk (located by
scanning the segment; audio bytes start at VAGD+0x10, whose first 16 bytes
are the customary null SPU frame — sample offsets already skip it, so they
are used as-is). ``rate_hz`` is a literal sample rate (48000, 22050, and
pitch-corrected values like 47866 all appear). ``flags`` bit 2 marks looped
cues; WAV export plays them once.

The ADPCM payload is standard PS2 SPU frames — decoded with the same
pure-Python decoder proven bit-exact against ffmpeg's ``adpcm_psx`` in the
Xenosaga I extractor. No external tools needed.
"""
from __future__ import annotations

import struct
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List

DTPK_MAGIC = b"ps2_DTPK"
VAGD_MAGIC = b"ps2_VAGD"

_SPU_FILTERS = ((0, 0), (60, 0), (115, -52), (98, -55), (122, -60))
_SIGNED_NIBBLE = tuple(n - 16 if n >= 8 else n for n in range(16))


class DAPError(Exception):
    """Raised when a file does not look like a DTPK bank."""


def decode_spu_adpcm(data: bytes) -> bytes:
    """Decode headerless SPU ADPCM to 16-bit little-endian mono PCM.

    Ported from the Xenosaga I extractor (browse.py); the predictor divides
    by 64 rounding toward zero, which matches the SPU / ffmpeg ``adpcm_psx``
    exactly (a plain ``>> 6`` floors and drifts).
    """
    import array

    out = array.array("h")
    h1 = h2 = 0
    nib = _SIGNED_NIBBLE
    for base in range(0, len(data) - 15, 16):
        hdr = data[base]
        shift = hdr & 0x0F
        filt = hdr >> 4
        if filt > 4 or shift > 12:  # invalid frame; keep sync, emit silence
            out.extend((0,) * 28)
            continue
        f0, f1 = _SPU_FILTERS[filt]
        up = 12 - shift
        for b in data[base + 2 : base + 16]:
            for n in (nib[b & 0x0F], nib[b >> 4]):
                p = h1 * f0 + h2 * f1
                s = (n << up) + (p // 64 if p >= 0 else -((-p) // 64))
                if s > 32767:
                    s = 32767
                elif s < -32768:
                    s = -32768
                h2 = h1
                h1 = s
                out.append(s)
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


@dataclass(frozen=True)
class Cue:
    segment: int      # segment ordinal within the file
    index: int        # cue ordinal within the segment
    rate: int         # sample rate in Hz
    flags: int        # bit 2 = looped
    adpcm: bytes      # raw SPU ADPCM frames


def parse_cues(data: bytes) -> List[Cue]:
    """Walk the segment chain and return every PCM cue in the bank."""
    if data[0x40:0x48] != DTPK_MAGIC:
        raise DAPError("no ps2_DTPK segment at 0x40")
    cues: List[Cue] = []
    seg = 0x40
    seg_no = 0
    while seg + 0x10 <= len(data) and data[seg : seg + 8] == DTPK_MAGIC:
        seg_size = struct.unpack_from("<I", data, seg + 0x0C)[0]
        if seg_size <= 0:
            break
        table_ptr = struct.unpack_from("<I", data, seg + 0xB8)[0]
        if table_ptr:
            body = data[seg : seg + seg_size]
            vpos = body.find(VAGD_MAGIC)
            if vpos < 0:
                raise DAPError(f"segment {seg_no} has a sample table but no ps2_VAGD")
            vagd_data = seg + vpos + 0x10
            count = struct.unpack_from("<I", data, seg + table_ptr)[0] + 1
            for i in range(count):
                off, _pad, flags, rate, length = struct.unpack_from(
                    "<IIHHI", data, seg + table_ptr + 4 + 16 * i
                )
                start = vagd_data + off
                if not (0 < rate <= 96000) or start + length > len(data):
                    raise DAPError(
                        f"segment {seg_no} cue {i} out of range "
                        f"(rate={rate}, off={off:#x}, len={length:#x})"
                    )
                cues.append(
                    Cue(segment=seg_no, index=i, rate=rate, flags=flags,
                        adpcm=data[start : start + length])
                )
        seg += seg_size
        seg_no += 1
    return cues


def decode_to_wavs(data: bytes, out_dir: Path, stem: str) -> int:
    """Write ``<stem>_sSS_cNN.wav`` per cue under ``out_dir``. Returns the
    number of WAVs written (0 for pure sequence banks — not an error)."""
    cues = parse_cues(data)
    if not cues:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    multi_seg = len({c.segment for c in cues}) > 1
    for c in cues:
        name = (f"{stem}_s{c.segment:02d}_c{c.index:02d}.wav" if multi_seg
                else f"{stem}_c{c.index:02d}.wav")
        pcm = decode_spu_adpcm(c.adpcm)
        with wave.open(str(out_dir / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(c.rate)
            w.writeframes(pcm)
    return len(cues)


__all__ = ["DAPError", "Cue", "decode_spu_adpcm", "parse_cues", "decode_to_wavs"]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Decode a .dap DTPK bank to WAVs")
    ap.add_argument("dap", nargs="+")
    ap.add_argument("--out", default=".", help="output directory")
    args = ap.parse_args()
    for f in args.dap:
        p = Path(f)
        n = decode_to_wavs(p.read_bytes(), Path(args.out), p.stem)
        print(f"{p.name}: {n} cues")
