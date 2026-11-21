"""align.py — Japanese <-> English text of Episode III side by side (JP retail vs USA retail).

New for this kit (2026-11-20), from the Japanese brief's X1 and its scratch
pair.py / align.py (survey code, not a kit module). Data only: nothing here
writes a disc.

    align-export --jp JP1.iso [--jp JP2.iso] --us D1.iso [--us D2.iso] --out DIR

What is paired, and how:

* ``.sb`` scene scripts (``cf\\jp`` <-> ``cf\\us``, ``bat\\jp`` <-> ``bat\\us``, same
  file name; the 140 JP-only scenes and ``mom1_b02`` have no partner and are
  listed as such). When the two text pools hold the same number of strings
  they pair index for index (method ``index``). Otherwise the pools are
  aligned with ``difflib.SequenceMatcher`` over per-string keys (method
  ``aligned``): an identifier (voice id, label) is its own key, a
  ``[Speaker]`` line is keyed by its speaker (the JP name mapped to the USA
  name most often paired with it in the index-paired files), any other string
  by a common placeholder. Equal runs and same-length replaced runs pair; the
  rest is emitted as ``unpaired`` rows, one side empty. Rows where both sides
  are the same identifier are counted but not written.
* ``.txd`` menu tables: index for index (``menutext`` 0-906; JP 907-908 are
  unpaired).
* subtitles (``mov\\xx\\``, ``mov\\xx\\bat\\``, ``evt\\xx\\``, same file name): the two
  builds were timed independently, so cues pair by TIME OVERLAP (method
  ``time``): each JP cue lasts until the next cue line (an empty cue clears),
  the last one 5 s; it is paired with every USA cue that overlaps it. USA cues
  that overlap no JP cue are ``unpaired``. Times: ``mm:ss:ff`` and plain frame
  counts at 30 frames per second (the JP files' own header: "30 = 1 second"),
  ``+`` relative to the previous cue. The time-0 style line is skipped.

Outputs: ``DIR/align.tsv`` (kind, file, jp_key, us_key, method, jp_role,
us_role, jp_speaker, us_speaker, jp_text, us_text; text in the kit's escape
form, a tab as ``⟦09⟧``), ``DIR/align.json`` (the same rows plus per-file and
total counts, the learned speaker map) and, per subtitle file,
``DIR/srt/<path>.jp.srt``, ``.en.srt`` and ``.dual.srt`` (JP timing, JP line
over the overlapping English). In the SRT files ``$...;`` commands are
dropped, ``\\n`` becomes a line break and ``[base/reading]`` ruby shows as
``base(reading)``.

Not paired: the mnu .bin databases (DBC2 is split differently, njDBcommon
differs), Message.Dat (871 vs 933 messages) and batdat.bin.

    python align.py --self-test
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import region as _region                                           # noqa: E402
import sb                                                          # noqa: E402
import subtitle                                                    # noqa: E402
import textcodec                                                   # noqa: E402
import txd                                                         # noqa: E402

FPS = 30
LAST_CUE = 5 * FPS
FIELDS = ("kind", "file", "jp_key", "us_key", "method", "jp_role", "us_role", "jp_speaker", "us_speaker",
          "jp_text", "us_text")
_SPK = re.compile(rb"^\[([^\]\0]{1,24})\]")


def _norm(p: str) -> str:
    return p.replace("/", "\\").lstrip("\\").lower()


def _row(**kw) -> dict:
    r = {k: "" for k in FIELDS}
    r.update(kw)
    return r


def _speaker(raw: bytes, codec: str) -> Tuple[Optional[bytes], str]:
    m = _SPK.match(raw)
    if not m:
        return None, ""
    return m.group(1), textcodec.codec_by_name(codec).to_text(m.group(1))


# ------------------------------------------------------------------ .sb

def _key(it: textcodec.Item, spk: Optional[bytes], smap: Optional[Dict[bytes, bytes]]) -> bytes:
    if it.role == "identifier":
        return b"I:" + it.raw
    if spk is not None:
        return b"D:" + (smap.get(spk, b"?" + spk) if smap is not None else spk)
    return b"T"


def speaker_map(pairs: List[Tuple[List[textcodec.Item], List[textcodec.Item]]]) -> Dict[bytes, bytes]:
    """JP speaker bytes -> the USA speaker most often paired with it in index-paired pools."""
    counts: Dict[bytes, collections.Counter] = collections.defaultdict(collections.Counter)
    for J, U in pairs:
        for a, b in zip(J, U):
            ma, mb = _SPK.match(a.raw), _SPK.match(b.raw)
            if ma and mb:
                counts[ma.group(1)][mb.group(1)] += 1
    return {j: c.most_common(1)[0][0] for j, c in counts.items()}


def align_items(J: List[textcodec.Item], U: List[textcodec.Item], smap: Dict[bytes, bytes]):
    """(pairs [(i, j)], unpaired JP indices, unpaired USA indices)."""
    kj = [_key(it, _SPK.match(it.raw) and _SPK.match(it.raw).group(1), smap) for it in J]
    ku = [_key(it, _SPK.match(it.raw) and _SPK.match(it.raw).group(1), None) for it in U]
    sm = difflib.SequenceMatcher(None, kj, ku, autojunk=False)
    pairs, uj, uu = [], [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            pairs += list(zip(range(i1, i2), range(j1, j2)))
        else:
            uj += list(range(i1, i2))
            uu += list(range(j1, j2))
    return pairs, uj, uu


def _text(it: textcodec.Item) -> str:
    return textcodec.codec_by_name(it.codec).to_text(it.raw).replace("\t", "⟦09⟧")


def sb_rows(name: str, J: List[textcodec.Item], U: List[textcodec.Item], method: str, pairs, uj, uu,
            stats: collections.Counter, smap: Dict[bytes, bytes]) -> List[dict]:
    rows = []

    def side(it, pre):
        if it is None:
            return {}
        _b, s = _speaker(it.raw, it.codec)
        return {f"{pre}_key": it.key, f"{pre}_role": it.role, f"{pre}_speaker": s, f"{pre}_text": _text(it)}

    for i, j in pairs:
        a, b = J[i], U[j]
        if a.role == b.role == "identifier" and a.raw == b.raw:
            stats["identical identifiers"] += 1
            continue
        stats[f"paired ({method})"] += 1
        sa, sb_ = _SPK.match(a.raw), _SPK.match(b.raw)
        if sa and sb_:
            stats["speaker agree" if smap.get(sa.group(1)) == sb_.group(1) else "speaker disagree"] += 1
        rows.append(_row(kind="sb", file=name, method=method, **side(a, "jp"), **side(b, "us")))
    for i in uj:
        stats["unpaired JP"] += 1
        rows.append(_row(kind="sb", file=name, method="unpaired", **side(J[i], "jp")))
    for j in uu:
        stats["unpaired US"] += 1
        rows.append(_row(kind="sb", file=name, method="unpaired", **side(U[j], "us")))
    return rows


# ------------------------------------------------------------------ subtitles

_TIME_RE = re.compile(r"^(\+?)(?:(\d+):(\d+):(\d+)|(\d+))$")


def parse_cues(text: str) -> List[Tuple[int, int, str]]:
    """(start frame, end frame, text) of each non-empty cue; time-0 style lines skipped."""
    starts: List[Tuple[int, str]] = []
    prev = 0
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not ln or ln.startswith(";") or ln[:1] not in "+0123456789":
            continue
        m = re.match(r"^(\S+)[ \t]*(.*)$", ln)
        tm = _TIME_RE.match(m.group(1))
        if not tm:
            continue
        if tm.group(5) is not None:
            f = int(tm.group(5))
        else:
            f = (int(tm.group(2)) * 60 + int(tm.group(3))) * FPS + int(tm.group(4))
        if tm.group(1):
            f += prev
        prev = f
        starts.append((f, m.group(2).rstrip()))
    out = []
    for k, (f, body) in enumerate(starts):
        if not body or (f == 0 and body.startswith("$")):
            continue
        end = starts[k + 1][0] if k + 1 < len(starts) else f + LAST_CUE
        out.append((f, max(end, f + 1), body))
    return out


def pair_cues(J, U) -> Tuple[List[Tuple[int, List[int]]], List[int]]:
    """(JP cue index, overlapping USA cue indices) and the USA cues no JP cue overlaps."""
    used, out = set(), []
    for i, (a0, a1, _t) in enumerate(J):
        hit = [j for j, (b0, b1, _u) in enumerate(U) if min(a1, b1) > max(a0, b0)]
        used.update(hit)
        out.append((i, hit))
    return out, [j for j in range(len(U)) if j not in used]


def _tc(f: int) -> str:
    ms = int(round(f * 1000 / FPS))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _ft(f: int) -> str:
    return f"{f // (60 * FPS):02d}:{f // FPS % 60:02d}:{f % FPS:02d}"


def srt_text(body: str) -> str:
    t = re.sub(r"\$[a-z]+[^;]*;", "", body)
    t = re.sub(r"\[([^/\]]+)/([^\]]+)\]", r"\1(\2)", t)
    return t.replace("\\n", "\n").strip()


def srt(cues: List[Tuple[int, int, str]]) -> str:
    return "".join(f"{k}\n{_tc(a)} --> {_tc(b)}\n{t}\n\n" for k, (a, b, t) in enumerate(cues, 1))


# ------------------------------------------------------------------ discs

class AlignError(ValueError):
    """A refused pairing (wrong build on a side, mixed Disc 1/Disc 2 builds)."""


class _Side:
    def __init__(self, isos: List[str], want: Tuple[str, ...]):
        from disc import Disc
        self.discs = [Disc(i) for i in isos]
        self.regions = [_region.detect(d) for d in self.discs]
        bad = [f"{d.path.name} ({r.name})" for d, r in zip(self.discs, self.regions) if r.name not in want]
        if bad:
            self.close()
            raise AlignError(f"expected a {' or '.join(want)} disc: {', '.join(bad)}")
        msg = _region.mixed_regions(self.discs)
        if msg:
            self.close()
            raise AlignError(msg.replace("warning: ", "", 1))
        self.region = self.regions[0]
        self.owner: Dict[str, Tuple[object, str]] = {}
        for d in self.discs:
            for _c, e in d.entries():
                self.owner.setdefault(_norm(e.path), (d, e.path.lstrip("\\")))

    def read(self, low: str) -> bytes:
        d, p = self.owner[low]
        return d.read(p)

    def close(self):
        for d in self.discs:
            d.close()


def _sub_name(low: str, lang: str) -> Optional[str]:
    """'mov\\jp\\bat\\x.txt' -> 'mov\\xx\\bat\\x.txt' (the common name) for movie/event files."""
    p = low.split("\\")
    if len(p) >= 3 and p[0] in ("mov", "evt") and p[1] == lang and p[-1].endswith(".txt"):
        return "\\".join([p[0], "xx"] + p[2:])
    return None


def align_export(jp_isos: List[str], us_isos: List[str], out_dir, srt_files: bool = True, log=print) -> dict:
    out = Path(out_dir)
    J = _Side(jp_isos, ("jp",))
    try:
        U = _Side(us_isos, ("us", "proto_2006_05"))
    except Exception:
        J.close()
        raise
    out.mkdir(parents=True, exist_ok=True)       # only once both sides are accepted
    try:
        jr, ur = J.region, U.region
        rows: List[dict] = []
        per_file: Dict[str, dict] = {}
        total: collections.Counter = collections.Counter()
        # .sb: collect both pools for every common name
        sbs = []
        only_jp, only_us = [], []
        for low in sorted(J.owner):
            p = low.split("\\")
            if len(p) == 3 and p[0] in ("cf", "bat") and p[1] == "jp" and p[2].endswith(".sb"):
                ul = f"{p[0]}\\us\\{p[2]}"
                if ul in U.owner:
                    sbs.append((f"{p[0]}\\xx\\{p[2]}", low, ul))
                else:
                    only_jp.append(J.owner[low][1])
        for low in sorted(U.owner):
            p = low.split("\\")
            if len(p) == 3 and p[0] in ("cf", "bat") and p[1] == "us" and p[2].endswith(".sb") \
                    and f"{p[0]}\\jp\\{p[2]}" not in J.owner:
                only_us.append(U.owner[low][1])
        pools = []
        for name, jl, ul in sbs:
            pools.append((name, sb.parse(J.read(jl), jr).items, sb.parse(U.read(ul), ur).items))
        smap = speaker_map([(a, b) for _n, a, b in pools if len(a) == len(b)])
        for name, a, b in pools:
            st: collections.Counter = collections.Counter()
            if len(a) == len(b):
                method, pairs, uj, uu = "index", list(zip(range(len(a)), range(len(b)))), [], []
                total["sb files index-paired"] += 1
            else:
                method = "aligned"
                pairs, uj, uu = align_items(a, b, smap)
                total["sb files aligned"] += 1
            rows += sb_rows(name, a, b, method, pairs, uj, uu, st, smap)
            per_file[name] = dict(st, jp_strings=len(a), us_strings=len(b), method=method)
            total.update(st)
        for p in only_jp:
            per_file[p] = {"status": sb.scene_status(p) or "JP only"}
        for p in only_us:
            per_file[p] = {"status": "USA only"}
        total["sb files JP only"] = len(only_jp)
        total["sb files USA only"] = len(only_us)
        # .txd: index for index
        for low in sorted(J.owner):
            p = low.split("\\")
            if len(p) == 3 and p[:2] == ["mnu", "jp"] and p[2].endswith(".txd") and f"mnu\\us\\{p[2]}" in U.owner:
                a = txd.parse(J.read(low), jr).items
                b = txd.parse(U.read(f"mnu\\us\\{p[2]}"), ur).items
                name = f"mnu\\xx\\{p[2]}"
                st = collections.Counter()
                for k in range(max(len(a), len(b))):
                    x = a[k] if k < len(a) else None
                    y = b[k] if k < len(b) else None
                    m = "index" if x is not None and y is not None else "unpaired"
                    st["paired (index)" if m == "index" else ("unpaired JP" if x is not None else "unpaired US")] += 1
                    rows.append(_row(kind="txd", file=name, method=m,
                                     jp_key=x.key if x else "", us_key=y.key if y else "",
                                     jp_role=x.role if x else "", us_role=y.role if y else "",
                                     jp_text=_text(x) if x else "", us_text=_text(y) if y else ""))
                per_file[name] = dict(st, jp_strings=len(a), us_strings=len(b), method="index")
                total.update({f"txd {k}": v for k, v in st.items()})
        # subtitles: time overlap
        jsubs = {_sub_name(low, jr.lang): low for low in J.owner if _sub_name(low, jr.lang)}
        usubs = {_sub_name(low, ur.lang): low for low in U.owner if _sub_name(low, ur.lang)}
        for name in sorted(set(jsubs) & set(usubs)):
            jl, ul = jsubs[name], usubs[name]
            jd, ud = J.read(jl), U.read(ul)
            _cj, jt = subtitle.to_text(jl, jd, jr)
            _cu, ut = subtitle.to_text(ul, ud, ur)
            cj, cu = parse_cues(jt), parse_cues(ut)
            pairs, lone = pair_cues(cj, cu)
            st = collections.Counter()
            for i, hit in pairs:
                a0, _a1, at = cj[i]
                st["paired (time)" if hit else "unpaired JP"] += 1
                rows.append(_row(kind="subtitle", file=name, method="time" if hit else "unpaired",
                                 jp_key=_ft(a0), us_key=" ".join(_ft(cu[j][0]) for j in hit),
                                 jp_text=at.replace("\t", "⟦09⟧"),
                                 us_text=" / ".join(cu[j][2] for j in hit).replace("\t", "⟦09⟧")))
            for j in lone:
                st["unpaired US"] += 1
                rows.append(_row(kind="subtitle", file=name, method="unpaired", us_key=_ft(cu[j][0]),
                                 us_text=cu[j][2].replace("\t", "⟦09⟧")))
            per_file[name] = dict(st, jp_cues=len(cj), us_cues=len(cu), method="time")
            total.update({f"subtitle {k}": v for k, v in st.items()})
            total["subtitle files"] += 1
            if srt_files:
                base = Path(out, "srt", *name.replace("\\xx\\", "\\").split("\\"))
                base.parent.mkdir(parents=True, exist_ok=True)
                jc = [(a, b, srt_text(t)) for a, b, t in cj]
                uc = [(a, b, srt_text(t)) for a, b, t in cu]
                Path(str(base) + ".jp.srt").write_text(srt(jc), encoding="utf-8")
                Path(str(base) + ".en.srt").write_text(srt(uc), encoding="utf-8")
                dual = [(cj[i][0], cj[i][1], jc[i][2] + "\n" + "\n".join(uc[j][2] for j in hit)) for i, hit in pairs]
                Path(str(base) + ".dual.srt").write_text(srt(dual), encoding="utf-8")
        total["subtitle files JP only"] = len(set(jsubs) - set(usubs))
        total["subtitle files USA only"] = len(set(usubs) - set(jsubs))
        with open(out / "align.tsv", "w", encoding="utf-8", newline="") as f:
            f.write("\t".join(FIELDS) + "\n")
            for r in rows:      # no field holds a tab or a line break (escape form, ⟦09⟧)
                f.write("\t".join(str(r[k]).replace("\t", "⟦09⟧").replace("\n", "⟦0A⟧").replace("\r", "⟦0D⟧")
                                  for k in FIELDS) + "\n")
        cj = textcodec.codec_by_name(jr.codec)
        cu = textcodec.codec_by_name(ur.codec)
        doc = {"tool": "xs3 align", "jp": [d.path.name for d in J.discs], "us": [d.path.name for d in U.discs],
               "jp_build": jr.name, "us_build": ur.name, "totals": dict(total), "files": per_file,
               "speaker_map": {cj.to_text(k): cu.to_text(v) for k, v in sorted(smap.items())},
               "rows": rows}
        (out / "align.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"align-export: {len(rows)} rows to {out}")
        for k in sorted(total):
            log(f"  {k}: {total[k]}")
        return doc
    finally:
        J.close()
        U.close()


def cmd_align(a) -> int:
    align_export(a.jp, a.us, a.out, srt_files=not a.no_srt)
    return 0


def add_commands(subparsers) -> None:
    if "align-export" in getattr(subparsers, "choices", {}):
        return                                   # already registered (textpack.add_commands)
    p = subparsers.add_parser("align-export", help="Japanese <-> English text side by side (JP retail vs USA): "
                                                   ".sb, .txd, subtitles; TSV + JSON + dual SRT")
    p.add_argument("--jp", action="append", required=True, help="Japanese disc image (repeat for Disc 2)")
    p.add_argument("--us", action="append", required=True, help="USA disc image (repeat for Disc 2)")
    p.add_argument("--out", required=True)
    p.add_argument("--no-srt", action="store_true", help="skip the per-file SRT files")
    p.set_defaults(func=cmd_align)


# ------------------------------------------------------------------ self-test

def self_test() -> int:
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    I = textcodec.Item
    # alignment: JP has an extra line, speakers map Shion <- シオン
    J = [I("0000", b"seg_a", "jp", "identifier"), I("0001", "[シオン]あ".encode("euc_jp"), "jp", "dialogue"),
         I("0002", "[シオン]い".encode("euc_jp"), "jp", "dialogue"), I("0003", "[アレン]う".encode("euc_jp"), "jp", "dialogue"),
         I("0004", b"seg_b", "jp", "identifier")]
    U = [I("0000", b"seg_a", "us", "identifier"), I("0001", b"[Shion]A", "us", "dialogue"),
         I("0002", b"[Allen]U", "us", "dialogue"), I("0003", b"seg_b", "us", "identifier")]
    smap = speaker_map([(J[1:2] + J[3:4], U[1:3])])
    check(smap == {"シオン".encode("euc_jp"): b"Shion", "アレン".encode("euc_jp"): b"Allen"}, "speaker map learned")
    pairs, uj, uu = align_items(J, U, smap)
    check(((1, 1) in pairs or (2, 1) in pairs) and (3, 2) in pairs and (0, 0) in pairs and (4, 3) in pairs
          and len(uj) == 1 and uu == [],
          f"speaker-anchored alignment pairs around the extra JP line (pairs {pairs}, unpaired JP {uj})")
    st = collections.Counter()
    rows = sb_rows("cf\\xx\\t.sb", J, U, "aligned", pairs, uj, uu, st, smap)
    check(st["identical identifiers"] == 2 and st["unpaired JP"] == 1 and st["speaker agree"] == 2
          and any(r["jp_speaker"] == "シオン" and r["us_speaker"] == "Shion" for r in rows), "rows and counts")
    # cues
    jt = "00:00:00\t$ay365;\n;comment\n00:01:00\t[漢字/かんじ]だ\n00:03:00\n+30\tつぎ\n"
    ut = "00:00:00\t$ay375;\n00:01:15\tKanji\n00:02:20\n00:03:10\tNext\nend\n"
    cj, cu = parse_cues(jt), parse_cues(ut)
    check(cj == [(30, 90, "[漢字/かんじ]だ"), (120, 270, "つぎ")] and cu[0] == (45, 80, "Kanji"),
          f"cue parse: mm:ss:ff, '+' relative, clear cues, style line skipped ({cj})")
    pr, lone = pair_cues(cj, cu)
    check(pr == [(0, [0]), (1, [1])] and lone == [], "cues pair by overlap")
    check(srt_text("$col707070;[漢字/かんじ]だ\\n2") == "漢字(かんじ)だ\n2" and _tc(45) == "00:00:01,500",
          "SRT text and time code")

    j1, u1 = os.environ.get("XS3_JP1"), os.environ.get("XS3_D1")
    if not (j1 and u1):
        print("SKIP  disc checks (set XS3_JP1 and XS3_D1; XS3_JP2/XS3_D2 optional)")
    else:
        jp = [j1] + ([os.environ["XS3_JP2"]] if os.environ.get("XS3_JP2") else [])
        us = [u1] + ([os.environ["XS3_D2"]] if os.environ.get("XS3_D2") else [])
        with tempfile.TemporaryDirectory() as tmp:
            doc = align_export(jp, us, tmp, log=lambda *x: None)
            t = doc["totals"]
            check(t["sb files index-paired"] + t["sb files aligned"] == 715 and t["sb files aligned"] == 148,
                  f"715 shared .sb: {t['sb files index-paired']} index-paired, {t['sb files aligned']} aligned")
            check(t["sb files JP only"] == 141, f"141 JP-only .sb ({t['sb files JP only']})")
            agree = t["speaker agree"] / max(1, t["speaker agree"] + t["speaker disagree"])
            check(agree > 0.9, f"speaker agreement {agree:.1%} ({t['speaker agree']}/{t['speaker agree'] + t['speaker disagree']}); "
                               f"unpaired JP {t['unpaired JP']} / US {t['unpaired US']}")
            m = next((r for r in doc["rows"] if r["file"] == "mnu\\xx\\menutext.txd" and r["jp_key"] == "0008"), None)
            check(m is not None and m["us_text"] == "Options" and t.get("txd unpaired JP") == 2,
                  f"menutext #8 pairs with 'Options' ({m and m['jp_text']}); JP 907-908 unpaired")
            check(t["subtitle files"] > 100 and (Path(tmp) / "align.tsv").exists()
                  and any(Path(tmp, "srt").rglob("*.dual.srt")),
                  f"{t['subtitle files']} subtitle files paired by time; TSV and dual SRT written")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    ap = argparse.ArgumentParser(description="XS3 JP <-> EN text alignment")
    add_commands(ap.add_subparsers(dest="cmd", required=True))
    a = ap.parse_args()
    sys.exit(a.func(a))
