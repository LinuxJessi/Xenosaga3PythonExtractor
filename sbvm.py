"""sbvm.py — Xenosaga III's script machine: disassemble the code of a ``.sb``.

``sb.py`` reads and rebuilds the text pool of a scene script; this module reads
the program around it. Episode II ran a stack machine of 16-bit words
(Xenosaga2PythonExtractor/sb.py); Episode III keeps the design (the same
operators, typed arguments, threads, natives registered by class) and re-encodes
it as BYTES with short and long operand forms. Read from the boot executable
(USA Disc 1, SLUS_213.89, Ghidra output + the bytes; 2026-11-21):

* the interpreter step is ``FUN_001d2738``: it fetches the byte at the thread's
  pc and calls ``handler[op](thread, op)`` for ``op < 99``; a larger byte is the
  error hook ``FUN_001d1828``;
* the handlers are a 99-entry table at ``0x407b70`` (39 distinct functions,
  ``FUN_001d27e0`` .. ``FUN_001d3eb0``), the instruction lengths a 99-byte table
  at ``0x407b08`` read by ``FUN_001d2700``; op 0x62 (``switch``) is sized
  ``8n + 6`` instead;
* operands are BIG-endian, read a byte at a time by ``FUN_001d2498``;
* natives are registered by class with ``FUN_001d1868(name, table)`` and an
  import is resolved to ``class << 16 | index`` when a script loads
  (``FUN_001d1a50`` / ``FUN_001d1b60``): see ``sbnatives.py``.

The same two tables and the same registration call are in every build read:
``read_vm_tables`` finds them by content, not by address (prototype: lengths at
0x4078c8; Japan: 0x406378; the 99 lengths are byte-identical in all five).

File layout (``sb.py`` has the header and the text pool)::

    +0x08  code section      u32 12, u32 pc of ``main``, u32 code size, the code
    +0x0C  globals section   u32 8, u32 slots, u32 values[slots]
    +0x10  text pool         (sb.py)
    +0x14  entries section   u32 8, u32 n, n x {u32 name offset, u32 pc}, the names
    +0x18  imports section   u32 8, u32 n, n x u32 (class name offset << 16 |
                             function name offset), the names; offsets count from
                             the end of the table
    +0x1C  chunk list        {u32 id, u32 size, data}...; id 1 = the source name

A pc counts BYTES from the start of the code. Jumps are relative to the pc of
their own opcode (signed 16 bits; ``switch`` uses signed 32). ``main`` (the
code header's second word) is an entry in all 715 USA scripts; the loader
(``FUN_001d1538``) starts one thread there.

The thread (``FUN_001d1cc8``; 32 threads of 0x48 bytes at 0x60e140): +0x00 pc,
+0x04 stack depth, +0x08 frame pointer, +0x0C the last native's result, +0x18
the script image, +0x1C its id (= the pc it was started at), +0x20 the value
stack (0x80 slots of 32 bits), +0x24 a parallel stack of one TYPE byte per
slot, +0x30 its message queue. Globals live in the script image (the file's
values are the initial values); locals are stack slots above the frame pointer.

Every push carries a type, which a native reads back with ``FUN_001d4088``
(``FUN_001d4108`` treats type 0 as "argument omitted")::

    0 none      pushnone (an omitted argument)
    1 int       push / pushaddr and every computed value
    2 text      pushtext: an index into the script's own text pool, resolved by
                FUN_001d4238 (all 246,009 operands on USA Disc 1 are inside the pool)
    3           literal form 0x27/0x28: no script on any disc uses it
    4 code      pushcode: the pc of an entry (the operand is its index)
    5 table     only as the type of a loaded global whose value is the slot number
                of a block of globals: on the discs always the 4-slot message
                buffer handed to send/recv (9,790 of 9,790 on USA Disc 1)

A native call is: the arguments in order, then their COUNT as an int, then
``native k``; the handler checks the count against the function's minimum
(table word 3), calls it, stores the result in the thread and drops count + 1
slots. ``result`` pushes that value. A native that sets its second argument to
1 has not finished: the same instruction runs again next frame.

Opcodes (hex; the mnemonics are this kit's, taken from Xenosaga2PythonExtractor
where the handler does the same thing: the executable has no names for them)::

    00 nop                         01 neg
    02 add 03 sub 04 mul 05 div 06 mod 07 or 08 and 09 shr 0a shl
    0b eq 0c gt 0d lt 0e ge 0f le 10 ne 11 lor 12 land       (pop b, pop a, push a op b)
    13 push i32   14 push i8   15 push i16   16 push -1   17-1f push 0..8
    20/21 pushaddr u16/u8     a variable's slot number, for st*/ld*.ind/inc*/dec*
    22/23 pushcode u16/u8     entry index -> its pc, type code
    24    pushnone
    25/26 pushtext u16/u8     text pool index, type text
    27/28 push3    u16/u8     type 3 (unused)
    29-2d ldg u16, types 1..5     2e-32 ldg u8, types 1..5      global slot
    33-37 ldl u16, types 1..5     38-3c ldl u8, types 1..5      local slot
    3d stg   3e stl               pop slot, pop value, store
    3f stg.keep  40 stl.keep      the same, the value stays on the stack
    41 jmp s16   42 jz s16   43 jnz s16
    44 enter                      open a call frame (3 slots), arguments follow
    45/46 call u16/u8             entry index
    47 ret   48 retv              retv returns the top of the stack
    49/4a native u16/u8           import index
    4b result                     push the last native's result
    4c start    pop a pc, start a thread there       4d stop   pop a pc, stop that thread
    4e drop
    4f-53 ldg.ind (types 1..5)    54-58 ldl.ind       pop slot, push its value
    59 end      5a yield          stop for this frame (end: pc back to the thread's start)
    5b sleep    pop n, wait n frames
    5c send     pop thread id, pop slot: queue the 16 bytes at that global to the thread
    5d recv     pop thread id, pop slot: take a queued message into that global, push 1/0
    5e incg  5f incl  60 decg  61 decl      pop slot
    62 switch   u8 n, s32 default, n x {s32 value, s32 offset}; values sorted
                (the handler searches them by halving)

34 of the 99 never occur on any disc read (USA 1/2, prototype, Japan 1/2):
00 0a 22 27 28 2a 2b 2c 30 31 33-37 39-3c 3f 40 43 45 49 51-58 5f 61.

Measured (``python sbvm.py --self-test`` with the XS3_* variables set): every
``.sb`` disassembles from pc 0 to exactly the code size with no unknown byte,
every jump, switch arm, entry and ``main`` lands on an instruction, every
import resolves in ``sbnatives.CLASSES``, and every native call's argument list
is recovered by the symbolic walk in ``native_calls``.

    python sbvm.py --self-test
    python sbvm.py FILE.sb                  # listing of a local file
"""
from __future__ import annotations

import collections
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb as _sb                                                   # noqa: E402
import sbnatives                                                   # noqa: E402
from sb import SbError                                             # noqa: E402

N_OPS = 99
# instruction lengths in bytes, the executable's table (USA 0x407b08); 0x62 is 8n + 6
LENGTHS = bytes((
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,     # 00-0f
    1, 1, 1, 5, 2, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,     # 10-1f
    3, 2, 3, 2, 1, 3, 2, 3, 2, 3, 3, 3, 3, 3, 2, 2,     # 20-2f
    2, 2, 2, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 1, 1, 1,     # 30-3f
    1, 3, 3, 3, 1, 3, 2, 1, 1, 3, 2, 1, 1, 1, 1, 1,     # 40-4f
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,     # 50-5f
    1, 1, 0))                                           # 60-62
assert len(LENGTHS) == N_OPS

TYPES = {0: "none", 1: "int", 2: "text", 3: "type3", 4: "code", 5: "table"}
OPERATORS = {0x02: "add", 0x03: "sub", 0x04: "mul", 0x05: "div", 0x06: "mod", 0x07: "or",
             0x08: "and", 0x09: "shr", 0x0A: "shl", 0x0B: "eq", 0x0C: "gt", 0x0D: "lt",
             0x0E: "ge", 0x0F: "le", 0x10: "ne", 0x11: "lor", 0x12: "land"}
NAMES: Dict[int, str] = {0x00: "nop", 0x01: "neg", **OPERATORS,
                         0x13: "push", 0x14: "push", 0x15: "push", 0x16: "push",
                         0x20: "pushaddr", 0x21: "pushaddr", 0x22: "pushcode", 0x23: "pushcode",
                         0x24: "pushnone", 0x25: "pushtext", 0x26: "pushtext",
                         0x27: "push3", 0x28: "push3",
                         0x3D: "stg", 0x3E: "stl", 0x3F: "stg.keep", 0x40: "stl.keep",
                         0x41: "jmp", 0x42: "jz", 0x43: "jnz", 0x44: "enter",
                         0x45: "call", 0x46: "call", 0x47: "ret", 0x48: "retv",
                         0x49: "native", 0x4A: "native", 0x4B: "result",
                         0x4C: "start", 0x4D: "stop", 0x4E: "drop",
                         0x59: "end", 0x5A: "yield", 0x5B: "sleep", 0x5C: "send", 0x5D: "recv",
                         0x5E: "incg", 0x5F: "incl", 0x60: "decg", 0x61: "decl", 0x62: "switch"}
for _k in range(0x17, 0x20):
    NAMES[_k] = "push"
for _k in range(5):
    NAMES[0x29 + _k] = NAMES[0x2E + _k] = "ldg"
    NAMES[0x33 + _k] = NAMES[0x38 + _k] = "ldl"
    NAMES[0x4F + _k] = "ldg.ind"
    NAMES[0x54 + _k] = "ldl.ind"
assert len(NAMES) == N_OPS

PUSH_INT = frozenset(range(0x13, 0x20))            # literal ints
PUSH_TEXT = frozenset((0x25, 0x26))
PUSH_CODE = frozenset((0x22, 0x23))
PUSH_ADDR = frozenset((0x20, 0x21))
JUMPS = frozenset((0x41, 0x42, 0x43))
CALLS = frozenset((0x45, 0x46))
NATIVES = frozenset((0x49, 0x4A))
SIGNED = frozenset((0x13, 0x14, 0x15)) | JUMPS
SWITCH = 0x62
# the type a load pushes: ldg/ldl/ldg.ind carry it in the opcode, ldl.ind is always int
_LOAD_TYPE = {**{0x29 + k: k + 1 for k in range(5)}, **{0x2E + k: k + 1 for k in range(5)},
              **{0x33 + k: k + 1 for k in range(5)}, **{0x38 + k: k + 1 for k in range(5)},
              **{0x4F + k: k + 1 for k in range(5)}, **{0x54 + k: 1 for k in range(5)}}


# what a pushaddr addresses, from the instruction that consumes it: a global (stg,
# stg.keep, ldg.ind, incg, decg) or a local (stl, stl.keep, ldl.ind, incl, decl)
_ADDR_KIND = {**{k: "g" for k in (0x3D, 0x3F, 0x4F, 0x50, 0x51, 0x52, 0x53, 0x5E, 0x60)},
              **{k: "l" for k in (0x3E, 0x40, 0x54, 0x55, 0x56, 0x57, 0x58, 0x5F, 0x61)}}


@dataclass
class Insn:
    pc: int
    op: int
    size: int
    operand: Optional[int] = None          # jumps: the TARGET pc; pushcode/call: entry index
    default: Optional[int] = None          # switch: target pc of the default arm
    table: List[Tuple[int, int]] = field(default_factory=list)   # switch: (value, target pc)

    @property
    def name(self) -> str:
        return NAMES[self.op]

    @property
    def value(self) -> Optional[int]:
        """The int a literal push leaves (None for anything else)."""
        if self.op in (0x13, 0x14, 0x15):
            return self.operand
        if self.op == 0x16:
            return -1
        if 0x17 <= self.op <= 0x1F:
            return self.op - 0x17
        return None

    @property
    def load_type(self) -> Optional[int]:
        return _LOAD_TYPE.get(self.op)


@dataclass
class Program:
    code: bytes
    main: int                               # pc of 'main' (code header word 2)
    entries: List[Tuple[str, int]]          # (name, pc), file order
    imports: List[Tuple[str, str]]          # (class, function), file order
    globals_: Tuple[int, ...]               # initial values of the global slots
    n_strings: int                          # strings in the text pool
    source: str                             # e.g. 'us\\2940'
    code_header: Tuple[int, int, int] = (12, 0, 0)

    def entry_pc(self, index: int) -> Optional[int]:
        return self.entries[index][1] if 0 <= index < len(self.entries) else None

    def table_strings(self) -> List[Tuple[int, int]]:
        """(global slot, text index), one per pool string that no ``pushtext`` names:
        the strings a script reads through a table of string numbers in its globals
        (``ldg.ind`` with type text). A slot is a candidate when its initial value is
        such a string's index; a small index can also be some counter's initial value,
        so each string is given the candidate slot in the longest run of adjacent
        slots holding consecutive string numbers (the tables on the discs are such
        runs). On every disc read, each string no pushtext
        names has a candidate slot (USA Disc 1: 45 strings in 3 files)."""
        pushed = {i.operand for i in disassemble(self.code) if i.op in PUSH_TEXT}
        want = set(range(self.n_strings)) - pushed
        cand = [slot for slot, v in enumerate(self.globals_) if v in want]
        run_len: Dict[int, int] = {}
        k = 0
        while k < len(cand):
            j = k
            while (j + 1 < len(cand) and cand[j + 1] == cand[j] + 1
                   and self.globals_[cand[j + 1]] == self.globals_[cand[j]] + 1):
                j += 1
            for slot in cand[k:j + 1]:
                run_len[slot] = j + 1 - k
            k = j + 1
        best: Dict[int, int] = {}
        for slot in cand:
            v = self.globals_[slot]
            if v not in best or run_len[slot] > run_len[best[v]]:
                best[v] = slot
        return sorted((slot, v) for v, slot in best.items())


def _cstr(data: bytes, off: int, limit: int) -> str:
    end = data.find(b"\0", off, limit)
    if off < 0 or end < 0:
        raise SbError("unterminated name")
    return data[off:end].decode("latin-1")


def parse(data: bytes) -> Program:
    """The program of an XS3 ``.sb`` (the text pool itself is ``sb.parse``'s)."""
    if data[:4] != _sb.MAGIC or len(data) < 0x40:
        raise SbError("not an XS3 'SB  ' script")
    code_o, glob_o, pool_o, ent_o, imp_o, name_o = struct.unpack_from("<6I", data, _sb.HDR)
    for o in (code_o, glob_o, pool_o, ent_o, imp_o):
        if not (0x40 <= o <= len(data) - 8):
            raise SbError("a section offset points outside the file")
    hs, main, size = struct.unpack_from("<III", data, code_o)
    if hs != 12 or code_o + hs + size > len(data):
        raise SbError(f"code header {hs}/{size:#x} does not fit the file")
    code = bytes(data[code_o + hs:code_o + hs + size])
    hs, n = struct.unpack_from("<II", data, glob_o)
    if glob_o + hs + 4 * n > len(data):
        raise SbError("the globals run past the end of the file")
    globals_ = struct.unpack_from(f"<{n}I", data, glob_o + hs)
    n_strings = struct.unpack_from("<I", data, pool_o + 4)[0]
    hs, n = struct.unpack_from("<II", data, ent_o)
    if ent_o + hs + 8 * n > len(data):
        raise SbError("the entry table runs past the end of the file")
    entries = []
    for k in range(n):
        name_off, pc = struct.unpack_from("<II", data, ent_o + hs + 8 * k)
        entries.append((_cstr(data, ent_o + hs + name_off, len(data)), pc))
    hs, n = struct.unpack_from("<II", data, imp_o)
    if imp_o + hs + 4 * n > len(data):
        raise SbError("the import table runs past the end of the file")
    base = imp_o + hs + 4 * n
    imports = []
    for k in range(n):
        v = struct.unpack_from("<I", data, imp_o + hs + 4 * k)[0]
        imports.append((_cstr(data, base + (v >> 16), len(data)), _cstr(data, base + (v & 0xFFFF), len(data))))
    source = ""
    o = name_o
    while o and o + 8 <= len(data):                      # chunk list: {id, size, data}
        cid, csz = struct.unpack_from("<II", data, o)
        if cid == 0:
            break
        if cid == 1:
            source = data[o + 8:o + 8 + csz].split(b"\0", 1)[0].decode("latin-1")
            break
        o += 8 + csz
    return Program(code, main, entries, imports, globals_, n_strings, source, (12, main, size))


def _be(code: bytes, off: int, n: int, signed: bool = False) -> int:
    return int.from_bytes(code[off:off + n], "big", signed=signed)


def disassemble(code: bytes) -> List[Insn]:
    """Every instruction from pc 0 to the end of the code. An unknown opcode or an
    instruction that runs past the end is an SbError: nothing is skipped."""
    out: List[Insn] = []
    pc, end = 0, len(code)
    while pc < end:
        op = code[pc]
        if op >= N_OPS:
            raise SbError(f"unknown opcode {op:#04x} at pc {pc:#x}")
        if op == SWITCH:
            if pc + 6 > end:
                raise SbError(f"switch at pc {pc:#x} runs past the end of the code")
            n = code[pc + 1]
            size = 8 * n + 6
            if pc + size > end:
                raise SbError(f"switch at pc {pc:#x} runs past the end of the code")
            table = [(_be(code, pc + 6 + 8 * k, 4, True), pc + _be(code, pc + 10 + 8 * k, 4, True))
                     for k in range(n)]
            out.append(Insn(pc, op, size, n, pc + _be(code, pc + 2, 4, True), table))
        else:
            size = LENGTHS[op]
            if pc + size > end:
                raise SbError(f"{NAMES[op]} at pc {pc:#x} runs past the end of the code")
            operand = None
            if size > 1:
                operand = _be(code, pc + 1, size - 1, op in SIGNED)
                if op in JUMPS:
                    operand += pc
            out.append(Insn(pc, op, size, operand))
        pc += size
    return out


def code_refs(prog: Program, insns: Optional[Sequence[Insn]] = None) -> Dict[int, str]:
    """pc -> label for every place the code is entered: entries (their own names), jump
    and switch targets (``L_xxxx``)."""
    insns = disassemble(prog.code) if insns is None else insns
    labels: Dict[int, str] = {}
    for name, pc in prog.entries:
        labels.setdefault(pc, name)
    for i in insns:
        if i.op in JUMPS:
            labels.setdefault(i.operand, f"L_{i.operand:04x}")
        elif i.op == SWITCH:
            for t in [i.default] + [t for _, t in i.table]:
                labels.setdefault(t, f"L_{t:04x}")
    return labels


def check(prog: Program, insns: Optional[Sequence[Insn]] = None) -> List[str]:
    """Structural problems of a program ([] when sound): targets off an instruction,
    operands outside their table."""
    insns = disassemble(prog.code) if insns is None else insns
    starts = {i.pc for i in insns}
    bad = []
    for i in insns:
        if i.op in JUMPS and i.operand not in starts:
            bad.append(f"{i.pc:#x}: jump to {i.operand:#x}, not an instruction")
        elif i.op == SWITCH:
            bad += [f"{i.pc:#x}: switch arm to {t:#x}, not an instruction"
                    for t in [i.default] + [t for _, t in i.table] if t not in starts]
            if [v for v, _ in i.table] != sorted(v for v, _ in i.table):
                bad.append(f"{i.pc:#x}: switch values are not sorted")
        elif i.op in PUSH_TEXT and i.operand >= prog.n_strings:
            bad.append(f"{i.pc:#x}: pushtext {i.operand}, the pool holds {prog.n_strings}")
        elif i.op in (PUSH_CODE | CALLS) and i.operand >= len(prog.entries):
            bad.append(f"{i.pc:#x}: entry {i.operand} of {len(prog.entries)}")
        elif i.op in NATIVES and i.operand >= len(prog.imports):
            bad.append(f"{i.pc:#x}: import {i.operand} of {len(prog.imports)}")
    bad += [f"entry {n} at {pc:#x}, not an instruction" for n, pc in prog.entries if pc not in starts]
    if prog.main not in starts:
        bad.append(f"main at {prog.main:#x}, not an instruction")
    return bad


# ------------------------------------------------------------ native calls

Arg = Tuple[str, Optional[int]]


def native_calls(prog: Program, insns: Optional[Sequence[Insn]] = None
                 ) -> Iterator[Tuple[int, str, Optional[List[Arg]]]]:
    """(pc, 'class.function', arguments) for every native call, from a symbolic walk
    of the stack (arguments, then their count, then ``native``). The stack is
    forgotten at every label. An argument is ``(kind, value)``:

        ('int', n)  ('text', pool index)  ('code', entry index)  ('none', None)
        ('addr', slot)                    a pushaddr
        ('global:<type>', slot)  ('local:<type>', slot)   a loaded variable
        ('ind:<type>', None)              a variable loaded through a computed slot
        ('result', None)                  the previous native's result
        ('expr', None)                    anything computed

    ``arguments`` is None when the count is not a literal (no call on any disc read)."""
    insns = disassemble(prog.code) if insns is None else insns
    labels = set(code_refs(prog, insns))
    st: List[Arg] = []

    def pop() -> Arg:
        return st.pop() if st else ("?", None)

    for i in insns:
        if i.pc in labels:
            st = []
        op = i.op
        if op == 0x00:
            pass
        elif op == 0x01:
            pop()
            st.append(("expr", None))
        elif op in OPERATORS:
            pop()
            pop()
            st.append(("expr", None))
        elif op in PUSH_INT:
            st.append(("int", i.value))
        elif op in PUSH_ADDR:
            st.append(("addr", i.operand))
        elif op in PUSH_CODE:
            st.append(("code", i.operand))
        elif op == 0x24:
            st.append(("none", None))
        elif op in PUSH_TEXT:
            st.append(("text", i.operand))
        elif op in (0x27, 0x28):
            st.append(("type3", i.operand))
        elif 0x29 <= op <= 0x32:
            st.append((f"global:{TYPES[i.load_type]}", i.operand))
        elif 0x33 <= op <= 0x3C:
            st.append((f"local:{TYPES[i.load_type]}", i.operand))
        elif op in (0x3D, 0x3E):
            pop()
            pop()
        elif op in (0x3F, 0x40):
            pop()
        elif op in (0x42, 0x43, SWITCH, 0x41, 0x47, 0x48, 0x59):
            st = []
        elif op == 0x44:
            st += [("frame", None)] * 3
        elif op in CALLS:
            st = []
        elif op in NATIVES:
            cnt = pop()
            args: Optional[List[Arg]] = None
            if cnt[0] == "int" and 0 <= cnt[1] <= 0x7F:
                args = [pop() for _ in range(cnt[1])][::-1]
            else:
                st = []
            cls, fn = prog.imports[i.operand] if i.operand < len(prog.imports) else ("?", "?")
            yield i.pc, f"{cls}.{fn}", args
        elif op == 0x4B:
            st.append(("result", None))
        elif op in (0x4C, 0x4D, 0x4E, 0x5B):
            pop()
        elif 0x4F <= op <= 0x58:
            pop()
            st.append((f"ind:{TYPES[i.load_type]}", None))
        elif op == 0x5C:
            pop()
            pop()
        elif op == 0x5D:
            pop()
            pop()
            st.append(("expr", None))
        elif 0x5E <= op <= 0x61:
            pop()


def text_uses(prog: Program, insns: Optional[Sequence[Insn]] = None) -> Dict[int, List[Tuple[str, int]]]:
    """text pool index -> [(native, argument position)] for every string a native call
    receives as a literal ``pushtext`` argument."""
    out: Dict[int, List[Tuple[str, int]]] = collections.defaultdict(list)
    for _pc, name, args in native_calls(prog, insns):
        for k, (kind, v) in enumerate(args or ()):
            if kind == "text":
                out[v].append((name, k))
    return dict(out)


# ---------------------------------------------------------------- listing

def _text_of(script: Optional["_sb.Script"]):
    if script is None:
        return lambda k: None
    import textcodec
    items = script.items

    def get(k: int) -> Optional[str]:
        if not 0 <= k < len(items):
            return None
        it = items[k]
        return textcodec.codec_by_name(it.codec).to_text(it.raw)
    return get


def listing(prog: Program, script: Optional["_sb.Script"] = None) -> str:
    """A text listing of the program. With ``script`` (``sb.parse`` of the same file)
    each ``pushtext`` shows its string."""
    insns = disassemble(prog.code)
    labels = code_refs(prog, insns)
    text = _text_of(script)
    known = sum(1 for c, f in prog.imports if sbnatives.lookup(c, f) is not None)
    lines = [f"; source {prog.source}",
             f"; {len(prog.entries)} entries, {len(prog.imports)} imports ({known} in sbnatives), "
             f"{len(insns)} instructions, {len(prog.code)} code bytes, {len(prog.globals_)} global slots, "
             f"{prog.n_strings} strings; main at {prog.main:04x}"]
    for k, (cls, fn) in enumerate(prog.imports):
        lines.append(f";   import {k:3d} = {cls}.{fn}")
    for slot, idx in prog.table_strings():
        t = text(idx)
        lines.append(f";   table g{slot} = text#{idx}" + (f"    ; {t[:70]}" if t else ""))
    following = {a.pc: b for a, b in zip(insns, insns[1:])}
    for i in insns:
        if i.pc in labels:
            lines.append(f"{labels[i.pc]}:")
        op, arg = i.op, ""
        if op in PUSH_INT:
            arg = str(i.value)
        elif op in PUSH_ADDR:
            nxt = following.get(i.pc)
            kind = "slot " if nxt is None else _ADDR_KIND.get(nxt.op, "slot ")
            arg = f"{kind}{i.operand}"
        elif op in PUSH_CODE or op in CALLS:
            pc = prog.entry_pc(i.operand)
            arg = labels.get(pc, f"entry{i.operand}") if pc is not None else f"entry{i.operand}"
        elif op in PUSH_TEXT:
            arg = f"text#{i.operand}"
            t = text(i.operand)
            if t is not None:
                arg += "    ; " + t.replace("\n", "\\n")[:70]
        elif 0x29 <= op <= 0x3C:
            arg = ("g" if op <= 0x32 else "l") + str(i.operand)
            if i.load_type != 1:
                arg += f" :{TYPES[i.load_type]}"
        elif 0x4F <= op <= 0x53 and i.load_type != 1:
            arg = f":{TYPES[i.load_type]}"
        elif op in JUMPS:
            arg = labels.get(i.operand, f"{i.operand:#x}")
        elif op in NATIVES:
            cls, fn = prog.imports[i.operand] if i.operand < len(prog.imports) else ("?", str(i.operand))
            arg = f"{cls}.{fn}"
        elif op == SWITCH:
            arg = f"default {labels.get(i.default)}; " + ", ".join(f"{v}:{labels.get(t)}" for v, t in i.table)
        elif i.operand is not None:
            arg = str(i.operand)
        lines.append(f"  {i.pc:04x}  {i.name:9s} {arg}".rstrip())
    return "\n".join(lines)


# ------------------------------------------------- the tables in an executable

@dataclass
class VmTables:
    lengths_va: int                          # the 99-byte instruction-length table
    handlers: List[int]                      # 99 handler addresses (the table follows at +0x68)
    register_va: int                         # the class registration function
    classes: Dict[str, Tuple[int, List[Tuple[str, int, int]]]]   # name -> (table va, [(fn, min_args, handler)])
    unterminated: List[str] = field(default_factory=list)        # classes whose table has no closing zero


class _Image:
    """Several ELF images (the boot executable and its overlays) as one address space."""

    def __init__(self, blobs: Sequence[bytes]):
        import region
        self.parts = [(b, region.elf_segments(b)) for b in blobs]

    def find(self, va: int, n: int = 1) -> Optional[Tuple[bytes, int]]:
        for blob, segs in self.parts:
            for v, off, size in segs:
                if v <= va and va + n <= v + size:
                    return blob, off + (va - v)
        return None

    def cstr(self, va: int) -> Optional[str]:
        hit = self.find(va)
        if hit is None:
            return None
        blob, off = hit
        end = blob.find(b"\0", off, off + 64)
        raw = blob[off:end] if end > off else b""
        return raw.decode("ascii") if raw and all(32 < c < 127 for c in raw) else None

    def table(self, va: int) -> Optional[Tuple[List[Tuple[str, int, int]], bool]]:
        """(records, closed by a zero name) of a native table at ``va``; None if it is
        not one."""
        out = []
        while True:
            hit = self.find(va, 12)
            if hit is None:
                return None
            name_va, handler, argc = struct.unpack_from("<III", hit[0], hit[1])
            if name_va == 0:
                return (out, True) if out else None
            name = self.cstr(name_va)
            if name is None:
                return (out, False) if out else None
            if handler & 3 or argc > 32 or self.find(handler) is None:
                return None
            out.append((name, argc, handler))
            va += 12


def _call_args(words: Sequence[int], i: int) -> Tuple[Optional[int], Optional[int]]:
    """Constant $a0 and $a1 at the jal/j at ``words[i]`` (lui/addiu/ori in the 24
    instructions before it and its delay slot)."""
    val: Dict[int, int] = {}
    for j in range(max(0, i - 24), min(len(words), i + 2)):
        w = words[j]
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 0x0F:                                     # lui
            val[rt] = imm << 16
        elif op == 0x09:                                   # addiu
            simm = imm - 0x10000 if imm & 0x8000 else imm
            if rs == 0:
                val[rt] = simm & 0xFFFFFFFF
            elif rs in val:
                val[rt] = (val[rs] + simm) & 0xFFFFFFFF
            else:
                val.pop(rt, None)
        elif op == 0x0D and rs in val:                     # ori
            val[rt] = val[rs] | imm
    return val.get(4), val.get(5)


def read_vm_tables(exe: bytes, overlays: Sequence[bytes] = ()) -> VmTables:
    """The script machine's tables of a build, found by content: the instruction
    lengths are the 99 bytes of ``LENGTHS`` (one place in the executable), the
    handler table follows them at +0x68, and the registration function is the call
    target that the most (class name, native table) constant pairs are passed to."""
    import region
    k = exe.find(LENGTHS)
    if k < 0 or exe.find(LENGTHS, k + 1) >= 0:
        raise SbError("the instruction-length table is not in this executable (or not once)")
    lengths_va = region.offset_to_va(exe, k)
    handlers = list(struct.unpack_from(f"<{N_OPS}I", exe, region.va_to_offset(exe, lengths_va + 0x68, 4 * N_OPS)))
    img = _Image([exe, *overlays])
    sites: Dict[int, List[Tuple[int, int]]] = collections.defaultdict(list)
    for blob, segs in img.parts:
        for _va, off, size in segs:
            n = size // 4
            words = struct.unpack_from(f"<{n}I", blob, off)
            for i, w in enumerate(words):
                if w >> 26 in (2, 3):                      # j / jal
                    a0, a1 = _call_args(words, i)
                    if a0 and a1:
                        sites[(w & 0x3FFFFFF) << 2].append((a0, a1))
    best: Tuple[int, Dict[str, Tuple[int, List[Tuple[str, int, int]]]], List[str]] = (0, {}, [])
    for target, pairs in sites.items():
        got: Dict[str, Tuple[int, List[Tuple[str, int, int]]]] = {}
        open_: List[str] = []
        for a0, a1 in pairs:
            name = img.cstr(a0)
            tab = img.table(a1) if name else None
            if tab:
                got[name] = (a1, tab[0])
                if not tab[1] and name not in open_:
                    open_.append(name)
        if len(got) > len(best[1]):
            best = (target, got, open_)
    if not best[1]:
        raise SbError("no native class registration found in this executable")
    classes = dict(sorted(best[1].items(), key=lambda kv: kv[1][0]))
    return VmTables(lengths_va, handlers, best[0], classes, best[2])


def disc_vm_tables(disc) -> VmTables:
    """``read_vm_tables`` for a disc.Disc: its boot executable and OV0x.OVL files."""
    import region
    _name, exe = region.executable(disc)
    ovl = []
    for n in ("OV01.OVL", "OV02.OVL", "OV04.OVL"):
        if disc.iso.find(n) is not None:
            ovl.append(bytes(disc.iso.read_file(n)))
    return read_vm_tables(exe, ovl)


# ------------------------------------------------------------ test helpers

def assemble(ops: Sequence) -> bytes:
    """Code bytes from ``(opcode, operand)`` pairs or bare opcodes (for tests). A jump's
    operand is its relative offset; ``(0x62, default, [(value, offset), ...])`` a switch."""
    out = bytearray()
    for item in ops:
        if isinstance(item, int):
            item = (item,)
        op = item[0]
        if op == SWITCH:
            _, default, table = item
            out += bytes((op, len(table))) + default.to_bytes(4, "big", signed=True)
            for v, t in table:
                out += v.to_bytes(4, "big", signed=True) + t.to_bytes(4, "big", signed=True)
            continue
        out.append(op)
        n = LENGTHS[op] - 1
        if n:
            out += int(item[1]).to_bytes(n, "big", signed=op in SIGNED)
    return bytes(out)


def build_script(code: bytes, imports: Sequence[Tuple[str, str]], entries: Sequence[Tuple[str, int]],
                 strings: Sequence[bytes] = (), globals_: Sequence[int] = (), source: str = "us\\0000",
                 main: Optional[int] = None) -> bytes:
    """A script file from its parts, in the layout ``parse`` and ``sb.parse`` read."""
    def sec(n: int, body: bytes) -> bytes:
        body = struct.pack("<II", 8, n) + body
        return body + b"\0" * ((-len(body)) % 4)
    if main is None:
        main = dict(entries).get("main", 0)
    code_sec = struct.pack("<III", 12, main, len(code)) + code
    code_sec += b"\0" * ((-len(code_sec)) % 4)
    names, tab = b"", b""
    for name, pc in entries:
        tab += struct.pack("<II", 8 * len(entries) + len(names), pc)
        names += name.encode() + b"\0"
    ent = sec(len(entries), tab + names)
    pool, where = b"", {}
    for cls, fn in imports:
        for s in (cls, fn):
            if s not in where:
                where[s] = len(pool)
                pool += s.encode() + b"\0"
    imp = sec(len(imports), b"".join(struct.pack("<I", where[c] << 16 | where[f]) for c, f in imports) + pool)
    src = source.encode() + b"\0"
    src += b"\0" * ((-len(src)) % 4)
    parts = [code_sec, sec(len(globals_), struct.pack(f"<{len(globals_)}I", *globals_)),
             _sb.build_pool(list(strings)), ent, imp, struct.pack("<II", 1, len(src)) + src + b"\0" * 8]
    offs, cur = [], 0x40
    for p in parts:
        offs.append(cur)
        cur += len(p)
    return _sb.MAGIC + struct.pack("<HH", 1, 1) + struct.pack("<6I", *offs) + b"\0" * 0x20 + b"".join(parts)


# ---------------------------------------------------------------- self-test

def survey(disc, region=None) -> dict:
    """Disassemble every .sb of a disc.Disc and count what the docstring claims."""
    res = collections.Counter()
    ops: collections.Counter = collections.Counter()
    natives: collections.Counter = collections.Counter()
    for _c, e in disc.entries():
        if not e.path.lower().endswith(".sb"):
            continue
        data = disc.read(e.path)
        res["files"] += 1
        try:
            prog = parse(data)
            insns = disassemble(prog.code)
        except SbError:
            res["failed"] += 1
            continue
        res["instructions"] += len(insns)
        res["problems"] += len(check(prog, insns))
        res["main is an entry"] += prog.main in {pc for _n, pc in prog.entries}
        ops.update(i.op for i in insns)
        res["unknown imports"] += sum(1 for c, f in prog.imports if sbnatives.lookup(c, f) is None)
        res["text pushes"] += sum(1 for i in insns if i.op in PUSH_TEXT)
        pushed = {i.operand for i in insns if i.op in PUSH_TEXT}
        res["strings"] += prog.n_strings
        res["strings pushed"] += len(pushed)
        res["strings by table"] += len({v for _s, v in prog.table_strings()})
        res["strings unreached"] += prog.n_strings - len(pushed | {v for _s, v in prog.table_strings()})
        for _pc, name, args in native_calls(prog, insns):
            res["native calls"] += 1
            natives[name] += 1
            if args is None or any(k == "?" for k, _ in args):
                res["calls not recovered"] += 1
            else:
                res["text arguments"] += sum(1 for k, _ in args if k == "text")
                hit = sbnatives.lookup(*name.split(".", 1))
                if hit is not None and len(args) < hit[0]:
                    res["calls under the minimum"] += 1
    res["opcodes used"] = len(ops)
    res["natives used"] = len(natives)
    return dict(res)


def self_test() -> int:
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    chk(len(LENGTHS) == 99 and len(NAMES) == 99 and LENGTHS[0x13] == 5 and LENGTHS[0x62] == 0,
        "99 opcodes, each with a length and a mnemonic")
    chk(sbnatives.count() == (22, 327) and sbnatives.lookup("talk", "EvtMsg") == (0, 0x26C1A8)
        and sbnatives.lookup("runtime", "setDoorAttr")[0] == 3, "sbnatives: 22 classes, 327 functions")

    # main: talk.Msg("hello", 1); if (g0 == 3) deb.put("dbg"); switch(g1){...}; end
    strs = [b"[Shion]<l1>Hello.<w15>", b"dbg", b"table line"]
    ops = [(0x26, 0), 0x18, 0x19, (0x4A, 0), 0x4B, 0x4E,            # 00 pushtext 0; push 1; push 2 (count); native 0; result; drop
           (0x2E, 0), 0x1A, 0x0B, (0x42, 3 + 5),                     # 08 ldg g0; push 3; eq; jz +8 -> 14
           (0x26, 1), 0x18, (0x4A, 1),                               # 0f pushtext 1; push 1 (count); native 1
           (0x2E, 1), (SWITCH, 23, [(1, 22), (7, 23)]),              # 14 ldg g1; switch (22 bytes)
           0x00, 0x59,                                               # 2c nop; 2d end; sub at 2e
           0x44, (0x13, -70000), (0x14, -2), (0x15, -300), (0x23, 1), (0x46, 1), 0x47]
    code = assemble(ops)
    data = build_script(code, [("talk", "Msg"), ("deb", "put")], [("main", 0), ("sub", 0x2E)],
                        strs, [0, 0, 2])
    prog = parse(data)
    insns = disassemble(prog.code)
    chk(prog.main == 0 and prog.entries == [("main", 0), ("sub", 0x2E)] and prog.source == "us\\0000"
        and prog.imports == [("talk", "Msg"), ("deb", "put")] and prog.globals_ == (0, 0, 2),
        "synthetic: header, entries, imports, globals, source name")
    chk(sum(i.size for i in insns) == len(code) and check(prog, insns) == [],
        f"synthetic: {len(insns)} instructions cover the code exactly; structure sound")
    sw = next(i for i in insns if i.op == SWITCH)
    chk(sw.size == 22 and sw.default == sw.pc + 23 and sw.table == [(1, sw.pc + 22), (7, sw.pc + 23)],
        "switch: 8n + 6 bytes, big-endian values, offsets relative to the opcode")
    jz = next(i for i in insns if i.op == 0x42)
    chk(jz.operand == jz.pc + 8 and [i.value for i in insns if i.op in (0x13, 0x14, 0x15)] == [-70000, -2, -300],
        "jumps are relative to their opcode; literals are signed big-endian")
    calls = list(native_calls(prog, insns))
    chk(calls == [(0x04, "talk.Msg", [("text", 0), ("int", 1)]), (0x12, "deb.put", [("text", 1)])],
        "native calls: arguments, then the count, then native")
    chk(text_uses(prog, insns) == {0: [("talk.Msg", 0)], 1: [("deb.put", 0)]} and prog.table_strings() == [(2, 2)],
        "text uses per native; a string no pushtext names is found through its global slot")
    lst = listing(prog, _sb.parse(data))
    chk("main:" in lst and "native    talk.Msg" in lst and "text#0    ; [Shion]" in lst and "sub:" in lst
        and "table g2 = text#2" in lst, "listing: labels, natives by name, strings inline")
    bad = bytearray(data)
    bad[struct.unpack_from("<I", data, 8)[0] + 12 + 2] = 0x63
    try:
        disassemble(parse(bytes(bad)).code)
        chk(False, "an unknown opcode is refused")
    except SbError:
        chk(True, "an unknown opcode is refused, not skipped")
    try:
        disassemble(code[:-3] + b"\x13\x00")
        chk(False, "a truncated instruction is refused")
    except SbError:
        chk(True, "an instruction running past the code is refused")

    isos = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(v for _, v in isos):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    from disc import Disc
    for env, iso in isos:
        if not iso:
            continue
        with Disc(iso) as disc:
            r = survey(disc)
            chk(r["files"] > 0 and r.get("failed", 0) == 0 and r.get("problems", 0) == 0,
                f"{env}: {r['files']} .sb disassemble end to end, {r['instructions']} instructions, "
                f"{r.get('failed', 0)} failed, {r.get('problems', 0)} bad targets/operands; "
                f"{r['opcodes used']} of 99 opcodes occur")
            chk(r["main is an entry"] == r["files"] and r.get("unknown imports", 0) == 0,
                f"{env}: main is a named entry in every script; every import is in sbnatives "
                f"({r['natives used']} natives called)")
            chk(r.get("calls not recovered", 0) == 0 and r.get("calls under the minimum", 0) == 0,
                f"{env}: {r['native calls']} native calls, all argument lists recovered, none under "
                f"its minimum; {r['text arguments']} of {r['text pushes']} text pushes are arguments")
            chk(r.get("strings unreached", 0) == 0,
                f"{env}: {r['strings']} pool strings = {r['strings pushed']} named by pushtext + "
                f"{r['strings by table']} by a global table; {r.get('strings unreached', 0)} unreached")
            t = disc_vm_tables(disc)
            fns = {c: [(f, a) for f, a, _h in v[1]] for c, v in t.classes.items()}
            ref = {c: [(f, a) for f, a, _h in v[1]] for c, v in sbnatives.CLASSES.items()}
            chk(len(set(t.handlers)) == 39 and fns == ref and t.unterminated == ["mm"],
                f"{env}: executable tables found by content (lengths {t.lengths_va:#x}, register "
                f"{t.register_va:#x}): 99 handlers (39 functions), {len(fns)} classes / "
                f"{sum(len(v) for v in fns.values())} natives equal to sbnatives; 'mm' has no closing zero")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


# ------------------------------------------------------------------ commands

def _disc_scripts(isos: Sequence[str], pattern: Optional[str] = None):
    """(disc, region, path, data) for every .sb of the given images, each path once."""
    import fnmatch
    import region as _region
    from disc import Disc
    seen = set()
    for iso in isos:
        with Disc(iso) as disc:
            reg = _region.detect(disc)
            for _c, e in disc.entries():
                p = e.path.lstrip("\\")
                if not p.lower().endswith(".sb") or p.lower() in seen:
                    continue
                if pattern and not fnmatch.fnmatch(p.lower(), pattern.lower().replace("/", "\\")):
                    continue
                seen.add(p.lower())
                yield disc, reg, p, disc.read(e.path)


def _cmd_sb(a) -> int:
    import region as _region
    if a.iso:
        from disc import Disc
        with Disc(a.iso) as disc:
            reg = _region.detect(disc)
            path = _region.resolve(disc, a.path, reg) or a.path
            if disc.lookup(path) is None:
                print(f"no script {a.path!r} on this disc (try: python cli.py list --iso ... | grep .sb)",
                      file=sys.stderr)
                return 1
            data = disc.read(path)
    else:
        if not os.path.isfile(a.path):
            print(f"{a.path!r} is not a file; give --iso to read an in-game path from a disc", file=sys.stderr)
            return 1
        reg = _region.as_region(a.region)
        data = open(a.path, "rb").read()
    text = listing(parse(data), _sb.parse(data, reg))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {a.out}")
    else:
        print(text)
    return 0


def _cmd_natives(a) -> int:
    from pathlib import Path
    if a.table:
        if a.iso:
            from disc import Disc
            with Disc(a.iso[0]) as disc:
                t = disc_vm_tables(disc)
            print(f"from the executable: lengths at {t.lengths_va:#x}, handlers at {t.lengths_va + 0x68:#x}, "
                  f"registration function {t.register_va:#x}")
            classes = {c: (va, fns) for c, (va, fns) in t.classes.items()}
        else:
            print("the kit's table (USA Disc 1 addresses; give --iso to read a disc's own executable)")
            classes = {c: (va, list(fns)) for c, (va, fns) in sbnatives.CLASSES.items()}
        for cls, (va, fns) in classes.items():
            print(f"{cls}  table {va:#x}, {len(fns)} functions")
            for fn, argc, handler in fns:
                print(f"  {cls}.{fn:<22} min args {argc}  handler {handler:#x}")
        print(f"{len(classes)} classes, {sum(len(f) for _v, f in classes.values())} functions")
        return 0
    if not a.iso:
        print("natives: give --iso (or --table for the registered natives)", file=sys.stderr)
        return 2
    calls: collections.Counter = collections.Counter()
    scripts = collections.defaultdict(set)
    sigs = collections.defaultdict(collections.Counter)
    out = Path(a.out) if a.out else None
    n = 0
    for _disc, reg, path, data in _disc_scripts(a.iso, a.glob):
        prog = parse(data)
        n += 1
        for _pc, name, args in native_calls(prog):
            calls[name] += 1
            scripts[name].add(path)
            sigs[name][tuple(k.split(":")[-1] if ":" in k else k for k, _ in (args or ()))] += 1
        if out:
            dest = out / "listings" / Path(*path.split("\\")).with_suffix(".txt")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(listing(prog, _sb.parse(data, reg)) + "\n", encoding="utf-8")
    print(f"{n} scripts, {len(calls)} natives, {sum(calls.values())} calls")
    rows = []
    for name in sorted(calls, key=lambda k: (k.split(".")[0], k)):
        sig = "; ".join(f"({', '.join(t)}) x{c}" for t, c in sigs[name].most_common(3))
        hit = sbnatives.lookup(*name.split(".", 1))
        rows.append((name, calls[name], len(scripts[name]), "" if hit is None else hit[0], sig))
        print(f"  {name:<28} {calls[name]:>6} calls {len(scripts[name]):>4} scripts  {sig}")
    never = [f"{c}.{f}" for c, (_va, fns) in sbnatives.CLASSES.items() for f, _a, _h in fns
             if f"{c}.{f}" not in calls]
    if not a.glob:
        print(f"registered but never called on these discs ({len(never)}): " + ", ".join(never))
    if out:
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "natives.tsv", "w", encoding="utf-8") as fh:
            fh.write("native\tcalls\tscripts\tmin_args\tsignatures\n")
            fh.writelines("\t".join(str(x) for x in r) + "\n" for r in rows)
        print(f"wrote {out / 'natives.tsv'}, {n} listings")
    return 0


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("sb", help="disassemble one scene script (.sb), its strings inline")
    p.add_argument("--iso", help="disc image (read only); without it --path is a local file")
    p.add_argument("--path", required=True, help="in-game path (cf\\us\\2940.sb; cf\\xx\\2940.sb takes the disc's "
                   "language folder) or a local .sb file")
    p.add_argument("--region", default="us", help="for a local file: us (default), proto_2006_05 or jp")
    p.add_argument("--out", help="write the listing to this file")
    p.set_defaults(func=_cmd_sb)

    p = subparsers.add_parser("natives", help="every script native with call counts and argument types "
                              "(+ listings); --table lists the natives the executable registers")
    p.add_argument("--iso", action="append", help="disc image (read only; repeat for both discs)")
    p.add_argument("--glob", help="only scripts whose path matches (e.g. 'bat\\us\\*')")
    p.add_argument("--out", help="write natives.tsv and one listing per script under listings/")
    p.add_argument("--table", action="store_true",
                   help="list the registered natives: read from the --iso executable, or the kit's table")
    p.set_defaults(func=_cmd_natives)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    if len(sys.argv) == 2 and os.path.isfile(sys.argv[1]):
        _d = open(sys.argv[1], "rb").read()
        print(listing(parse(_d), _sb.parse(_d)))
        sys.exit(0)
    print(__doc__)
