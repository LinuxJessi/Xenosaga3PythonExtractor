"""udf.py — keep the UDF half of an ISO9660 + UDF bridge image in step after a write.

Every known Episode III image (USA Disc 1/2, Japan, the May 2006 prototype) is
an ISO9660 + UDF 1.02 bridge disc with the same shape:

    sector 256          anchor volume descriptor (AVDP, tag 2)
    sectors 32.., 48..  main and reserve volume descriptor sequences:
                        partition descriptor (tag 5, start 263, length = image - 264)
                        logical volume descriptor (tag 6) -> integrity descriptor
                        (LVID, tag 9, sector 64: one partition, size table = length)
    263 + ...           24 file entries (tag 261, one short_ad each: 22 files, 2 dirs)
    last sector         second anchor (its tag location = its own sector)

The PS2 and PCSX2 read the ISO9660 side, so the game never looks at any of
this; tools that mount or burn through UDF do. ``sync`` brings the UDF side
back in line after ``disc.py`` grew the image or moved/resized an ISO9660 file:

* partition length (both descriptor sequences) and the LVID size table follow
  the image size (partition = start .. last sector - 1, as on every original);
* each file entry whose extent moved or changed size gets the new position,
  length, information length and recorded-block count;
* the anchor in the last sector is (re)written with its new location.

Every changed descriptor gets a fresh tag checksum and CRC-CCITT. The caller
makes room for the trailing anchor (``Disc.sync_udf`` appends one sector when
the image grew). ``check`` re-reads all of it and lists problems; on every
untouched original image it returns nothing.

The descriptor offsets, the CRC and the tag fix-up are ported from Anzinono's
xenosaga3-translation-kit ``tools/x3rebuild.py`` (MIT,
https://github.com/Anzinono/xenosaga3-translation-kit), which proved them by
rebuilding an unchanged image byte for byte. That tool inserts sectors in the
middle of the image; this kit appends at the end instead, so the "what moved"
side is new here.
"""
from __future__ import annotations

import struct
from typing import BinaryIO, Dict, Iterable, List, Optional, Tuple

SECTOR = 2048
TAG_AVDP, TAG_PD, TAG_LVD, TAG_LVID, TAG_FE = 2, 5, 6, 9, 261
ANCHOR = 256
FE_SCAN = 2048        # file entries live right after the partition start (263..290 on XS3)


def crc_ccitt(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def fix_tag(d: bytearray, location: Optional[int] = None) -> None:
    """Recompute a descriptor tag's CRC (over the CRC length) and checksum."""
    if location is not None:
        struct.pack_into("<I", d, 12, location)
    crc_len = struct.unpack_from("<H", d, 10)[0]
    struct.pack_into("<H", d, 8, crc_ccitt(bytes(d[16:16 + crc_len])))
    d[4] = (sum(d[0:4]) + sum(d[5:16])) & 0xFF


def tag_id(d: bytes) -> int:
    return struct.unpack_from("<H", d, 0)[0]


def tag_ok(d: bytes, location: int) -> bool:
    if len(d) < 16 or (sum(d[0:4]) + sum(d[5:16])) & 0xFF != d[4]:
        return False
    crc_len = struct.unpack_from("<H", d, 10)[0]
    return (struct.unpack_from("<H", d, 8)[0] == crc_ccitt(bytes(d[16:16 + crc_len]))
            and struct.unpack_from("<I", d, 12)[0] == location)


def _read(fh: BinaryIO, lba: int) -> bytearray:
    fh.seek(lba * SECTOR)
    return bytearray(fh.read(SECTOR))


def _write(fh: BinaryIO, lba: int, d: bytes) -> None:
    fh.seek(lba * SECTOR)
    fh.write(d)


def has_udf(fh: BinaryIO) -> bool:
    """True when sector 256 holds a valid anchor volume descriptor."""
    d = _read(fh, ANCHOR)
    return len(d) == SECTOR and tag_id(d) == TAG_AVDP and tag_ok(d, ANCHOR)


def _vds(fh: BinaryIO) -> Iterable[Tuple[int, bytearray]]:
    a = _read(fh, ANCHOR)
    main_len, main_loc, res_len, res_loc = struct.unpack_from("<IIII", a, 16)
    for loc, ln in ((main_loc, main_len), (res_loc, res_len)):
        for lba in range(loc, loc + -(-ln // SECTOR)):
            yield lba, _read(fh, lba)


def partition_start(fh: BinaryIO) -> int:
    for _, d in _vds(fh):
        if tag_id(d) == TAG_PD:
            return struct.unpack_from("<I", d, 188)[0]
    raise ValueError("UDF: no partition descriptor")


def _file_entries(fh: BinaryIO, part: int) -> Iterable[Tuple[int, bytearray, int]]:
    """(lba, sector, short_ad offset) of every plain-file entry with one short_ad."""
    for lba in range(part, part + FE_SCAN):
        d = _read(fh, lba)
        if len(d) < SECTOR or tag_id(d) != TAG_FE or d[16 + 11] != 5:      # file type 5 = file
            continue
        l_ea, l_ad = struct.unpack_from("<II", d, 168)
        if struct.unpack_from("<H", d, 34)[0] & 7 != 0 or l_ad != 8:
            continue
        yield lba, d, 176 + l_ea


def sync(fh: BinaryIO, image_sectors: int, moves: Dict[int, Tuple[int, int]]) -> List[str]:
    """Bring the UDF side in line with an image of ``image_sectors`` sectors whose
    last sector is reserved for the end anchor. ``moves`` = {old LBA: (new LBA,
    new size)} for every ISO9660 file whose extent changed. Returns log lines;
    raises ValueError for a layout it does not know (nothing half-written past
    the first refusal is possible: every check runs before the first write)."""
    part = partition_start(fh)
    plen = image_sectors - 1 - part
    writes: List[Tuple[int, bytes]] = []
    log: List[str] = []
    for lba, d in _vds(fh):
        if tag_id(d) == TAG_PD:
            struct.pack_into("<I", d, 192, plen)
            fix_tag(d)
            writes.append((lba, bytes(d)))
        elif tag_id(d) == TAG_LVD:
            lvid_loc = struct.unpack_from("<I", d, 436)[0]
            lv = _read(fh, lvid_loc)
            if tag_id(lv) != TAG_LVID:
                raise ValueError(f"UDF: no integrity descriptor at {lvid_loc}")
            n = struct.unpack_from("<I", lv, 72)[0]
            if n != 1:
                raise ValueError(f"UDF: {n} partitions in the integrity descriptor (1 expected)")
            struct.pack_into("<I", lv, 80 + 4 * n, plen)
            fix_tag(lv)
            writes.append((lvid_loc, bytes(lv)))
    log.append(f"UDF partition: {plen} sectors")
    todo = dict(moves)
    for lba, d, ad in _file_entries(fh, part):
        raw, pos = struct.unpack_from("<II", d, ad)
        old = pos + part
        if old not in todo:
            continue
        new_lba, size = todo.pop(old)
        if new_lba < part or size >= 1 << 30:
            raise ValueError(f"UDF: file at {old} -> {new_lba} / {size} bytes does not fit a short_ad")
        struct.pack_into("<QQ", d, 56, size, -(-size // SECTOR))
        struct.pack_into("<II", d, ad, (raw & 0xC0000000) | size, new_lba - part)
        fix_tag(d)
        writes.append((lba, bytes(d)))
        log.append(f"UDF file entry @{lba}: {old} -> {new_lba}, {size} bytes")
    if todo:
        raise ValueError("UDF: no file entry for the ISO9660 extent(s) at " + ", ".join(map(str, sorted(todo))))
    a = _read(fh, ANCHOR)
    fix_tag(a, image_sectors - 1)
    writes.append((image_sectors - 1, bytes(a)))
    for lba, d in writes:
        _write(fh, lba, d)
    fh.flush()
    log.append(f"UDF end anchor: sector {image_sectors - 1}")
    return log


def check(fh: BinaryIO, image_sectors: int, iso_files: Dict[int, int]) -> List[str]:
    """Problems with the UDF side of an image (empty = consistent). ``iso_files`` =
    {LBA: size} of the ISO9660 files; every UDF file entry must match one."""
    bad: List[str] = []
    if not has_udf(fh):
        return ["UDF: no valid anchor at sector 256"]
    end = _read(fh, image_sectors - 1)
    if tag_id(end) != TAG_AVDP or not tag_ok(end, image_sectors - 1):
        bad.append(f"UDF: no valid anchor in the last sector ({image_sectors - 1})")
    part = None
    for lba, d in _vds(fh):
        t = tag_id(d)
        if t in (TAG_PD, TAG_LVD) and not tag_ok(d, lba):
            bad.append(f"UDF: descriptor {t} at {lba} has a bad tag")
        if t == TAG_PD:
            part, plen = struct.unpack_from("<II", d, 188)
            if part + plen != image_sectors - 1:
                bad.append(f"UDF: partition {part}+{plen} does not end at the last sector")
        if t == TAG_LVD:
            loc = struct.unpack_from("<I", d, 436)[0]
            lv = _read(fh, loc)
            if not tag_ok(lv, loc):
                bad.append(f"UDF: integrity descriptor at {loc} has a bad tag")
            elif part is not None and struct.unpack_from("<I", lv, 84)[0] != image_sectors - 1 - part:
                bad.append("UDF: integrity size table does not match the partition")
    if part is None:
        return bad + ["UDF: no partition descriptor"]
    n = 0
    for lba, d, ad in _file_entries(fh, part):
        n += 1
        raw, pos = struct.unpack_from("<II", d, ad)
        info, blocks = struct.unpack_from("<QQ", d, 56)
        size, at = raw & 0x3FFFFFFF, pos + part
        if not tag_ok(d, lba - part):
            bad.append(f"UDF: file entry at {lba} has a bad tag")
        # a 1 GiB X3.nn part: the short_ad length 0x40000000 spills into the type bits
        if info >= 1 << 30:
            size = info
        if iso_files.get(at) != info or size != info or blocks != -(-info // SECTOR):
            bad.append(f"UDF: file entry at {lba} ({at}, {info} bytes) does not match the ISO9660 file there "
                       f"({iso_files.get(at)})")
    if n == 0:
        bad.append("UDF: no file entries found")
    return bad


def self_test() -> int:
    import os
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    chk(crc_ccitt(b"123456789") == 0x31C3, "CRC-CCITT (poly 0x1021, init 0) check value 0x31C3")
    d = bytearray(SECTOR)
    struct.pack_into("<HH", d, 0, TAG_AVDP, 2)
    struct.pack_into("<H", d, 10, 496)
    d[16:20] = b"\x01\x02\x03\x04"
    fix_tag(d, 1234)
    chk(tag_ok(d, 1234) and not tag_ok(d, 1235), "fix_tag / tag_ok: checksum, CRC and location")
    d[20] ^= 1
    chk(not tag_ok(d, 1234), "tag_ok: a flipped byte under the CRC is caught")
    envs = [os.environ.get(k) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(envs):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    from iso9660 import IsoImage
    for p in filter(None, envs):
        iso = IsoImage(p)
        files = {f.lba: f.size for f in iso.files.values() if not f.is_dir and f.layer == 0}
        with open(p, "rb") as fh:
            probs = check(fh, iso.image_size // SECTOR, files)
        iso.close()
        chk(not probs, f"{os.path.basename(p)}: UDF side agrees with ISO9660 untouched"
            + (f" ({probs[0]})" if probs else ""))
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
