"""
disasm_code.py — MIPS R5900 disassembly + string-load cross-references.

Produces two artefacts per ELF input:

* ``<name>.disasm.txt`` — full Capstone disassembly. MIPS64-LE mode with
  ``skipdata=True`` so the EE's MMI / VU0-macro instructions don't halt the
  disassembler — they appear as ``.byte`` runs.
* ``<name>.strings_xrefs.txt`` — one line per unique printable string that
  the code loads via the classic ``lui rt, hi`` + ``addiu rt, rt, lo`` (or
  ``ori``) pair. Far more readable than the raw asm; this is how you find
  the call sites of, e.g. ``"mwPlyCreateSofdec: can't skghn."``.

Optional dependency: ``capstone`` (``pip install capstone``). The function
raises a friendly :class:`DisasmError` if it's missing.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class DisasmError(Exception):
    """Raised when disassembly cannot proceed (missing capstone, bad ELF, …)."""


# ---------------------------------------------------------------------------
# ELF parsing — just enough for PS2 ELFs (32-bit, MIPS, LE)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProgramHeader:
    p_type: int
    p_offset: int
    p_vaddr: int
    p_filesz: int
    p_flags: int

    @property
    def executable(self) -> bool:
        return bool(self.p_flags & 1)


@dataclass(frozen=True)
class ElfInfo:
    entry: int
    program_headers: Tuple[ProgramHeader, ...]

    def text_segments(self) -> List[ProgramHeader]:
        return [ph for ph in self.program_headers if ph.p_type == 1 and ph.executable]

    def all_load_segments(self) -> List[ProgramHeader]:
        return [ph for ph in self.program_headers if ph.p_type == 1]


def parse_elf(data: bytes) -> ElfInfo:
    if data[:4] != b"\x7fELF":
        raise DisasmError("not an ELF file (missing magic)")
    if data[4] != 1:  # EI_CLASS = ELFCLASS32
        raise DisasmError(f"unexpected ELF class {data[4]} (want 1 for 32-bit)")
    if data[5] != 1:  # EI_DATA = ELFDATA2LSB
        raise DisasmError(f"unexpected ELF data {data[5]} (want 1 for little-endian)")
    e_entry, e_phoff = struct.unpack_from("<II", data, 0x18)
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x2A)
    phs: List[ProgramHeader] = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, _align = struct.unpack_from("<8I", data, off)
        phs.append(ProgramHeader(p_type, p_offset, p_vaddr, p_filesz, p_flags))
    return ElfInfo(entry=e_entry, program_headers=tuple(phs))


def _vaddr_of_file(elf: ElfInfo, file_off: int) -> Optional[int]:
    for ph in elf.all_load_segments():
        if ph.p_offset <= file_off < ph.p_offset + ph.p_filesz:
            return ph.p_vaddr + (file_off - ph.p_offset)
    return None


# ---------------------------------------------------------------------------
# Disassembly (one big text file)
# ---------------------------------------------------------------------------

def write_disassembly(elf_path: Path, out_path: Path) -> int:
    """Write the full disassembly. Returns the number of instructions written."""
    try:
        from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN
    except ImportError as exc:
        raise DisasmError("capstone is not installed; pip install capstone") from exc

    data = elf_path.read_bytes()
    elf = parse_elf(data)
    text = elf.text_segments()
    if not text:
        raise DisasmError(f"no executable segment in {elf_path}")
    ph = text[0]

    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
    md.skipdata = True
    md.detail = False

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# Disassembly of {elf_path.name} (PS2 EE, MIPS R5900 + Sony MMI / VU0)\n")
        f.write("# Decoded with Capstone MIPS64-LE + skipdata. MMI/VU0-macro instructions appear as `.byte` runs.\n")
        f.write(f"# Entry: 0x{elf.entry:08X}    .text vaddr 0x{ph.p_vaddr:08X}  size {ph.p_filesz}\n\n")
        for ins in md.disasm(data[ph.p_offset : ph.p_offset + ph.p_filesz], ph.p_vaddr):
            f.write(f"0x{ins.address:08x}: {ins.bytes.hex():>8}  {ins.mnemonic:<8} {ins.op_str}\n")
            n += 1
    return n


# ---------------------------------------------------------------------------
# String cross-references (lui/addiu pairs)
# ---------------------------------------------------------------------------

_STR_RE = re.compile(rb"[\x20-\x7e]{6,}")


def _find_strings(data: bytes, elf: ElfInfo) -> Dict[int, str]:
    strings: Dict[int, str] = {}
    for m in _STR_RE.finditer(data):
        va = _vaddr_of_file(elf, m.start())
        if va is not None:
            strings[va] = m.group(0).decode("ascii", errors="ignore")
    return strings


def write_string_xrefs(
    elf_path: Path,
    disasm_path: Path,
    out_path: Path,
) -> int:
    """Find every ``lui`` + ``addiu``/``ori`` pair that loads a string address.

    Parses the Capstone disassembly text rather than the bytes directly — the
    text already has all the boring instruction-form work done for us. We
    track outstanding ``lui rt, hi`` writes and pair them with the next
    arithmetic instruction that uses the same register.

    Returns the count of unique strings referenced.
    """
    if not disasm_path.exists():
        raise DisasmError(f"disassembly file missing: {disasm_path}")
    data = elf_path.read_bytes()
    elf = parse_elf(data)
    strings = _find_strings(data, elf)

    INST_RE = re.compile(r"0x([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)\s*(.*)")
    LUI_RE = re.compile(r"\$([a-z0-9]+),\s*0x([0-9a-f]+)")
    IMM_RE = re.compile(r"\$([a-z0-9]+),\s*\$([a-z0-9]+),\s*(-?(?:0x[0-9a-f]+|\d+))")

    pending: Dict[str, Tuple[int, int]] = {}
    xrefs: List[Tuple[int, int, str]] = []

    with disasm_path.open() as f:
        for line in f:
            m = INST_RE.match(line)
            if not m:
                continue
            va = int(m.group(1), 16)
            mn = m.group(2)
            op = m.group(3)
            if mn == "lui":
                lm = LUI_RE.match(op)
                if lm:
                    pending[lm.group(1)] = (va, int(lm.group(2), 16))
            elif mn in ("addiu", "ori"):
                im = IMM_RE.match(op)
                if not im:
                    continue
                rt, rs, imm_text = im.group(1), im.group(2), im.group(3)
                imm = int(imm_text, 0)
                if rs in pending and rt == rs:
                    lui_va, hi = pending[rs]
                    if mn == "addiu":
                        addr = (hi << 16) + imm
                    else:
                        addr = (hi << 16) + (imm & 0xFFFF)
                    addr &= 0xFFFFFFFF
                    if addr in strings:
                        xrefs.append((va, addr, strings[addr]))
                    del pending[rs]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set = set()
    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# Strings referenced from {elf_path.name}\n")
        f.write("# format: <load_va>  ->  <string_va>  <string (quoted)>\n\n")
        for va, addr, s in xrefs:
            if addr in seen:
                continue
            seen.add(addr)
            quoted = s[:200].replace("\n", "\\n").replace("\t", "\\t")
            f.write(f"0x{va:08x}  ->  0x{addr:08x}  {quoted!r}\n")
    return len(seen)


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------

@dataclass
class DisasmStats:
    files: int = 0
    instructions: int = 0
    unique_string_xrefs: int = 0


def disassemble_all(elf_paths: List[Path], out_dir: Path) -> DisasmStats:
    """Run disassembly + string xrefs for every ELF in ``elf_paths``.

    Writes alongside each ELF: ``<name>.disasm.txt`` + ``<name>.strings_xrefs.txt``.
    Returns aggregate stats.
    """
    stats = DisasmStats()
    for elf in elf_paths:
        target_dir = out_dir if out_dir != elf.parent else elf.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        disasm = target_dir / (elf.name + ".disasm.txt")
        xrefs = target_dir / (elf.name + ".strings_xrefs.txt")
        n_inst = write_disassembly(elf, disasm)
        n_xrefs = write_string_xrefs(elf, disasm, xrefs)
        stats.files += 1
        stats.instructions += n_inst
        stats.unique_string_xrefs += n_xrefs
        print(f"[disasm] {elf.name}: {n_inst:,} instructions, {n_xrefs:,} string xrefs")
    return stats


__all__ = [
    "DisasmError",
    "ProgramHeader",
    "ElfInfo",
    "DisasmStats",
    "parse_elf",
    "write_disassembly",
    "write_string_xrefs",
    "disassemble_all",
]
