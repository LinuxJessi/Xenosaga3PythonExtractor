"""txbuild.py — build translated disc images from a translation-editor project (Episode III).

The editor (``/editor``) saves a project JSON (txproject): the retail id of
the disc set it was made against and ``{row id: {"text", "state"}}``. This
module turns that into patched COPIES of the retail images in one pass:

  1. find the disc set (``txdiscs.pair``: Disc 1 + Disc 2 when the other disc
     is next to the one given, or named with ``--disc2``) and check the
     project was made for it (``txproject.retail_id``);
  2. split the translations by family (row id prefix ``sb: mnu: bat: sub:``)
     and validate EVERY row against the retail discs (``txfam_core.validate``:
     codec, the disc's fonts, the containers' own rules); any error stops
     the build with a per-id list before a single byte is written;
  3. builtin languages: each family returns its change set, ``{in-game path:
     new bytes}`` (``plan``), built by the same functions ``text-import``
     uses and read back in memory;
  3b. a language that needs letters the disc's fonts lack (``txtarget``): the
     kit's new-script pipeline runs instead (export the tree, write the
     translations in, ``lang scan`` / ``encode``), which also gives new
     font0.bin / font1.bin;
  4. ``patch.patch_copy`` writes everything into copies of both discs:
     APFS clone / reflink / full copy to ``<name>.partial``, chain-0 objects
     to both discs at the same place, each disc's subtitles to that disc,
     grown objects appended, every written byte verified, then renamed;
  5. the copies are read again: every changed object must hold the planned
     bytes, every OTHER text object must still be the retail bytes, and
     (builtin) every edited row must read back as the text that was asked for.

The source images are never written. Translations usually get longer, and no
loader buffer size is known for any Episode III text object (TRANSLATING.md),
so the build allows growth (``text-import --grow``) and lists every object
that grew: those are the first places to look at in the emulator.

Output: one ``.iso`` path when the set is a single disc; a FOLDER when it is
a pair (``OUT/<each source image's name>``). An output that already exists is
refused unless ``--overwrite``.

The GUI never imports this module: its Build button runs ``cli.py tx-build``
as a Job like every other card.

    python3 txbuild.py build --project P.json --retail DISC1.iso --out OUT/ [--disc2 DISC2.iso] [--overwrite]
    python3 txbuild.py selftest --iso DISC1 [--scratch DIR]

Nothing built here has been booted in PCSX2.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import txcodec as tc  # noqa: E402
import txproject  # noqa: E402
import txtarget  # noqa: E402

FAMILIES = (("sb", "txfam_sb"), ("mnu", "txfam_mnu"), ("bat", "txfam_bat"), ("sub", "txfam_sub"))


class BuildError(tc.TxBuildError):
    pass


# ---------------------------------------------------------------------------
# small pieces
# ---------------------------------------------------------------------------

def load_edits(project: dict) -> Tuple[Dict[str, str], int]:
    """Non-empty translations of the project -> ({id: text}, drafts)."""
    edits, drafts = {}, 0
    for rid, t in (project.get("translations") or {}).items():
        text = t.get("text", "") if isinstance(t, dict) else str(t)
        if not text.strip():
            continue
        edits[rid] = text
        if isinstance(t, dict) and t.get("state") != "done":
            drafts += 1
    return edits, drafts


def split_edits(edits: Dict[str, str]) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    per = {fam: {} for fam, _ in FAMILIES}
    unknown = []
    for rid, text in edits.items():
        fam = rid.split(":", 1)[0]
        if fam in per:
            per[fam][rid] = text
        else:
            unknown.append(rid)
    return per, unknown


def out_paths(isos: List[str], out) -> List[Path]:
    """Where ``patch.patch_copy`` puts the copies (its own rule: one ``.iso``
    path for a single image, else ``OUT/<source name>``)."""
    od = Path(out).expanduser()
    if len(isos) == 1 and (od.suffix.lower() == ".iso" and not od.is_dir()):
        return [od]
    outs = [od / Path(p).name for p in isos]
    if len({str(o).lower() for o in outs}) != len(outs):
        # (patch_copy names each copy after its source: the second would be written over the first)
        raise BuildError(f"the two disc images have the same file name ({Path(isos[0]).name}, in two folders): "
                         f"the copies are named after them and would overwrite each other. Rename one image "
                         f"(for example add 'Disc 1' / 'Disc 2') and choose it again")
    return outs


def _take_lock(out: Path) -> Path:
    """Create ``OUT.lock`` holding our pid; refuse while another live build
    holds it (a lock left by a dead process is taken over)."""
    lock = out.with_name(out.name + ".lock")
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or "0")
                age = time.time() - lock.stat().st_mtime
            except (OSError, ValueError):
                pid, age = 0, 0.0
            alive = age < 60 if pid <= 0 else True
            # signal 0 only asks "is it alive" on POSIX; on Windows os.kill(pid, 0)
            # sends a console event to that process, so the lock is trusted there
            if pid > 0 and os.name != "nt":
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    alive = False
                except PermissionError:
                    pass
            if alive:
                raise BuildError(f"another build{f' (pid {pid})' if pid > 0 else ''} is writing "
                                 f"{out.name}; wait for it to finish (or delete {lock.name} "
                                 f"if no build is running)")
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        return lock
    raise BuildError(f"could not take {lock.name}")


def raw_objects(isos: List[str]) -> Dict[str, bytes]:
    """{normalised in-game path: bytes} of every text object and both fonts of
    a disc set, read through the discs' own indexes (no parsing)."""
    import region as regionmod
    import textpack
    out: Dict[str, bytes] = {}
    srcs = [textpack.DiscSource(p) for p in isos]
    try:
        reg = srcs[0].region
        owner = {}
        for s in srcs:
            for _c, p in s.chained():
                owner.setdefault(textpack._norm(p), (s, p))
        for path, _kind in textpack.collect([v[1] for v in owner.values()], reg):
            s, p = owner[textpack._norm(path)]
            out[textpack._norm(p)] = s.read(p)
        for k in (0, 1):
            p = regionmod.resolve(srcs[0].disc, f"mnu\\xx\\font{k}.bin", reg)
            if p:
                out[textpack._norm(p)] = srcs[0].read(p)
        # chain 0 must be the same on both discs
        if len(srcs) == 2:
            for key, data in list(out.items()):
                other = srcs[1] if owner.get(key, (srcs[0],))[0] is srcs[0] else srcs[0]
                if other.chain_of(key) == 0 and other.read(key) != data:
                    out[key + " (differs between the two discs)"] = b""
    finally:
        for s in srcs:
            s.close()
    return out


class _ReadBackDone(Exception):
    """The read-back of an unlocked build ends after the byte comparison."""


def verify_objects(retail_isos: List[str], outs: List[str], expected: Dict[str, bytes]) -> Tuple[int, int, List[str]]:
    """Re-read the copies: every object of ``expected`` holds its bytes, every
    other text object (and font) is the retail one. -> (changed, untouched, problems)."""
    import textpack
    want = {textpack._norm(p): b for p, b in expected.items()}
    before, after = raw_objects(retail_isos), raw_objects(outs)
    problems = []
    for k in sorted(set(before) | set(after)):
        if k.endswith("(differs between the two discs)"):
            problems.append(k)
        elif k not in after:
            problems.append(f"{k}: gone from the copy")
        elif k in want:
            if after[k] != want[k]:
                problems.append(f"{k}: the copy does not hold the planned bytes")
        elif after.get(k) != before.get(k):
            problems.append(f"{k}: changed although no translation touches it")
    missing = [k for k in want if k not in after]
    problems += [f"{k}: planned but not a text object of the copy" for k in missing]
    return len(want), len(after) - len(want), problems


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def _was_lone(want_rid: str, retail: str) -> bool:
    try:
        import txdiscs
        return want_rid in txdiscs.lone_ids(retail)
    except Exception:                                       # noqa: BLE001
        return False


# free font cells of the USA executable without an unlock (USA Disc 1: 123
# proportional + 51 wide; glyphs-slots). Past this, txtarget.scan_fitting opens
# the kanji rows. A hint only: shaped scripts can need more cells than letters.
FREE_CELLS_HINT = 174

def preflight(project: dict, retail_iso: str) -> dict:
    """The checks a build makes before it writes anything, over the WHOLE project
    (the editor's per-line checker sees one line at a time): the disc set, the
    target, ids this set does not have, locks, keywords that follow their
    line's <k...> tag, and (retail letters) every family's own rules with the
    touched objects rebuilt in memory. Nothing is written.
    -> {"ok", "errors": {id: [..]}, "warnings": {id: [..]}, "notes": [..],
        "edits": n, "drafts": n, "script": bool}"""
    import txdiscs
    import txfam_core as core
    out: dict = {"ok": False, "errors": {}, "warnings": {}, "notes": [], "edits": 0, "drafts": 0,
                 "script": False}
    retail = str(Path(retail_iso).expanduser())
    try:
        isos = txdiscs.pair(retail)
    except txdiscs.DiscError as e:
        out["notes"].append(str(e)); return out
    rid, want = txproject.retail_id(retail), project.get("retail_id") or ""
    if want and want != rid:
        lone = _was_lone(want, retail)
        out["notes"].append("this project was made while only one disc of this set was found; both are found now. "
                            "Press \"Use both discs\" in the banner to move it to the set (nothing is lost)" if lone else
                            "this project was made for a different disc set than the one open")
        return out
    if len(isos) == 1:
        out["notes"].append(f"only {Path(isos[0]).name} is open: the build writes that disc alone")
    with tc.disc(isos[0]):                # this thread only: a server request must not change another's disc
        return _preflight_rest(project, retail, out)


def _preflight_rest(project: dict, retail: str, out: dict) -> dict:
    import txfam_core as core
    edits, drafts = load_edits(project)
    out["edits"], out["drafts"] = len(edits), drafts
    if not edits:
        out["notes"].append("the project has no translations yet; nothing to build")
        return out
    state = core.load(retail)            # (ids of no family / not on these discs: edit_errors names them)
    try:
        target = txtarget.resolve_target(project)
    except txtarget.TargetError as e:
        out["notes"].append(f"the project's target is not valid: {e}"); return out
    script = target["kind"] != "builtin" and txtarget.needs_glyphs(target, state.by_id, edits)
    out["script"] = bool(script)
    _eff, bad, kw_warn, _derived = core.edit_errors(state, edits)
    for k, v in bad.items():
        out["errors"].setdefault(k, []).extend(v)
    if not script:
        for k, v in core.validate(edits, retail).items():
            out["errors"].setdefault(k, []).extend(x for x in v if x not in out["errors"].get(k, []))
    else:
        ok, msg = txtarget.shaping_available()
        if not ok:
            out["notes"].append(f"{target.get('name') or 'this language'} needs new letters: {msg}")
        out["notes"].append("new letters are drawn and fitted into the font when you build; "
                            "that step is checked by the build itself")
        field = [t for rid, t in edits.items() if state.by_id.get(rid, {}).get("font") == tc.FIELD]
        n_new = len(set(txtarget.coverage(field, target)["glyph"]))
        if n_new > FREE_CELLS_HINT and tc.context(retail).addr.gate == "whitelist":
            out["notes"].append(
                f"{n_new} different new letters so far: more than the {FREE_CELLS_HINT} free cells of the "
                f"game's font, so the build will open the font's kanji rows (thousands of cells; the "
                f"executable is patched on both discs and English text with é, ä, ® and the like is "
                f"re-encoded for it)")
    for k, v in list(kw_warn.items()) + list(core.warnings(edits, retail).items()):
        out["warnings"].setdefault(k, []).extend(v)
    out["ok"] = not out["errors"] and not any("not valid" in n or "different disc set" in n or "needs new letters" in n
                                              for n in out["notes"])
    return out


def build(project_path: str, retail_iso: str, out, log: Callable[[str], None] = print,
          overwrite: bool = False, disc2: Optional[str] = None, identity_ok: bool = False,
          keep_work: Optional[str] = None) -> dict:
    """Build patched copies from the project. Raises BuildError (nothing left
    under the output names) when anything is wrong. ``identity_ok``: a project
    whose translations change nothing still writes (plain) copies; the
    selftest uses it to prove an unedited build is byte-identical."""
    import patch
    import txdiscs
    import txfam_core as core
    t0 = time.time()
    retail = Path(retail_iso).expanduser()
    if not retail.is_file():
        raise BuildError(f"no retail image at {retail}")
    try:
        if disc2:
            txdiscs.set_partner(str(retail), disc2)
        isos = txdiscs.pair(str(retail))
    except txdiscs.DiscError as e:
        raise BuildError(str(e)) from None
    outs = out_paths(isos, out)
    for o in outs:
        for s in isos:
            if Path(s).resolve() == o.resolve():
                raise BuildError("the output path is a retail image; pick another folder (the retail "
                                 "images are never written)")
        if o.exists() and not overwrite:
            raise BuildError(f"{o} already exists; pass --overwrite to replace it")
    if len(isos) == 2 and Path(out).expanduser().suffix.lower() == ".iso":
        raise BuildError(f"this project covers two discs ({', '.join(Path(p).name for p in isos)}): the "
                         f"output is a folder, not one .iso; both patched images are written into it")

    project = txproject.load(str(Path(project_path).expanduser()))
    rid = txproject.retail_id(str(retail))
    want_rid = project.get("retail_id") or ""
    if want_rid and want_rid != rid:
        raise BuildError(
            f"this project was made for a different disc set (retail id {want_rid[:12]}..., "
            f"these images {rid[:12]}...). Pick the untouched image(s) the project was started "
            f"from (a project started with both discs needs both; a patched copy cannot be the "
            f"base of a build)." + (" It was made while only one disc of this set was found: open it in the "
                                   "editor and press \"Use both discs\"." if _was_lone(want_rid, str(retail)) else ""))
    if not want_rid:
        log("note: the project has no retail id; building against these images anyway")
    log(txdiscs.describe(str(retail)))
    edits, drafts = load_edits(project)
    if not edits:
        raise BuildError("the project has no translations yet; nothing to build")
    per, unknown = split_edits(edits)
    if unknown:
        raise BuildError(f"{len(unknown)} id(s) belong to no family: " + ", ".join(unknown[:10]))
    state = core.load(str(retail))
    tc.use_disc(isos[0])
    try:
        target = txtarget.resolve_target(project)
    except txtarget.TargetError as e:
        raise BuildError(f"the project's target is not valid: {e}") from None
    log(f"project {Path(project_path).name}: language {project.get('language') or '?'} "
        f"(target {target['code'] or '?'}, {target['kind']}), "
        f"{len(edits)} translation(s) ({drafts} still draft): "
        + ", ".join(f"{fam} {len(per[fam])}" for fam, _ in FAMILIES if per[fam]))

    gone = [r for r in edits if r not in state.by_id]
    if gone:
        raise BuildError(f"{len(gone)} translation(s) are for strings this disc set does not have "
                         f"(the project was made with another set of discs?): " + ", ".join(gone[:6]))
    script = target["kind"] != "builtin" and txtarget.needs_glyphs(target, state.by_id, edits)

    def refuse(bad: Dict[str, List[str]]) -> None:
        lines = [f"{k}: {'; '.join(v)}" for k, v in list(bad.items())[:40]]
        raise BuildError(f"{len(bad)} translation(s) cannot be built; nothing written:\n  "
                         + "\n  ".join(lines) + ("\n  ..." if len(bad) > 40 else ""))

    # the rules about the edits themselves hold on BOTH paths (retail letters or
    # new glyphs): known ids, locked strings, keywords that follow their <k...> tag
    user_edits = edits
    edits, bad, _kw, derived = core.edit_errors(state, user_edits)
    if bad:
        refuse(bad)
    if derived:
        log(f"{len(derived)} keyword(s) follow the <k...> word of their translated line: "
            + ", ".join(r.split(':', 1)[1] for r in sorted(derived)[:6]) + (" ..." if len(derived) > 6 else ""))
    if not script:
        bad = core.validate(user_edits, str(retail))
        if bad:
            refuse(bad)
    for rid_, ws in core.warnings(edits, str(retail)).items():
        for w in ws:
            log(f"warning: {rid_}: {w}")

    out_root = Path(out).expanduser()
    if not out_root.parent.is_dir():
        raise BuildError(f"no such folder: {out_root.parent}")
    lock = _take_lock(out_root)           # OUT.lock, next to the output folder (or .iso)
    work = Path(keep_work) if keep_work else Path(tempfile.mkdtemp(prefix="xs3tx-build-"))
    try:
        expected: Dict[str, bytes] = {}
        unlock = "none"
        if script:
            ok, msg = txtarget.shaping_available()
            if not ok:
                raise BuildError(f"{target['name']} needs new letters: {msg}")
            import textpack
            try:
                res = txtarget.build_script(isos, state, target, edits, str(Path(out).expanduser()), work,
                                            overwrite=overwrite, log=log)
            except (txtarget.TargetError, patch.PatchError) as e:
                raise BuildError(str(e)) from None
            # what the copies must hold: the encoded tree's objects and the pack's fonts
            import langpack
            import region as regionmod
            changes, _rows, _w = textpack.plan_import(list(isos), res["enc"], True, False, lambda *a: None)
            expected.update(changes)
            pk = langpack.Pack.load(res["pack"])
            with textpack.DiscSource(isos[0]) as d:
                for k in (0, 1):
                    p = regionmod.resolve(d.disc, f"mnu\\xx\\font{k}.bin", d.region)
                    new = pk.fonts[k].to_bytes()
                    if d.read(p) != new:
                        expected[p] = new
            report = _rows
            target = res.get("target", target)
            unlock = res.get("unlock", "none")
        else:
            changes, report = core.plan(user_edits, str(retail))
            bad_planned = core.planned_errors(state, changes, edits)
            if bad_planned:
                raise BuildError(f"{len(bad_planned)} problem(s) in the rebuilt objects; nothing written:\n  "
                                 + "\n  ".join(bad_planned[:20]))
            expected.update(changes)
            if not changes and not identity_ok:
                raise BuildError("every translation in the project equals the original text; there is "
                                 "nothing to write")
            if not changes:        # identity: hand patch_copy one object's own bytes -> plain copies
                first = next(iter(state.objs.values()))
                changes = {first.path: first.data}
            try:
                patch.patch_copy(list(isos), str(Path(out).expanduser()), changes, grow=True,
                                 verbose=False, overwrite=overwrite)
            except patch.PatchError as e:
                raise BuildError(str(e)) from None
        grew = [r for r in report if r.get("new_size", 0) > r.get("old_size", 0)]
        for r in report:
            log(f"  {r['path']}: {r['old_size']} -> {r['new_size']} bytes ({r['action']})")
        if grew:
            log(f"note: {len(grew)} object(s) are larger than on the retail disc. The loader reads a file "
                f"at the size the disc's index gives into a buffer its caller chose; which buffer each of "
                f"these files gets is not traced (docs/TRANSLATION-EDITOR.md, Limits), so look at these "
                f"screens in the emulator first")
        # 5. read the copies again
        try:
            n_changed, n_same, problems = verify_objects(isos, [str(o) for o in outs], expected)
            rows_checked = 0
            if unlock != "none":
                # the kanji rows were opened (txtarget.scan_fitting): the copies' executables
                # carry the unlock, and the editor's readers parse only the retail gate. The
                # objects were compared byte for byte above; their links and byte limits were
                # checked on the encoded objects before anything was written.
                import glyphs as glyphmod
                import region as regionmod
                from iso9660 import IsoImage
                for o in outs:
                    with IsoImage(str(o)) as im:
                        got = glyphmod.applied_unlock(regionmod.executable(im)[1])
                    if got != unlock:
                        problems.append(f"{o.name}: the executable carries unlock {got!r}, not {unlock!r}")
                raise _ReadBackDone
            back = core.load_set([str(o.resolve()) for o in outs], cache=False)
            # what holds on both paths, checked on the bytes as written: a keyword is
            # still the <k...> word of its line, and no page passes a proven byte limit
            problems += core.check_links(state, back)
            import textpack
            for rid_ in edits:
                slot = back.slots.get(rid_)
                if slot is None:
                    problems.append(f"{rid_}: the row is gone from the copy")
                elif not textpack.KINDS[slot.obj.kind].whole_file:
                    problems += [f"{rid_}: {m}" for m in core.limit_errors(state.by_id[rid_], slot.raw)]
            for key_, obj_ in back.objs.items():
                lim = core.OBJ_LIMITS.get(core._stem(obj_.path).lower())
                if lim and len(obj_.data) > lim[0]:
                    problems.append(f"{obj_.path}: {len(obj_.data):,} bytes, over the {lim[0]:,} the game has room for")
            if not script:
                for rid_, text in edits.items():
                    slot = back.slots.get(rid_)
                    row = state.by_id[rid_]
                    if slot is None:
                        continue
                    rows_checked += 1
                    if slot.raw:
                        if slot.raw != core.encode(state, row, text):
                            problems.append(f"{rid_}: reads back as other bytes than were written")
                    else:           # a file row: compare the display text
                        want = text.replace("\r\n", "\n").replace("\r", "\n")
                        if back.by_id[rid_]["src"] != tc.to_display(
                                tc.from_display(want, row["font"], row["ctl"], keep=want, ctx=state.ctx)[0], row["ctl"]):
                            problems.append(f"{rid_}: reads back as other text than was written")
        except _ReadBackDone:
            pass
        except Exception as exc:                                   # noqa: BLE001 - an unreadable copy is a failed build
            problems = [f"the copies could not be read back ({type(exc).__name__}: {exc})"]
            n_changed = n_same = rows_checked = 0
        if problems:
            for o in outs:
                try:
                    o.unlink()
                except OSError:
                    pass
            raise BuildError(f"the copies failed the read-back check and were deleted ({len(problems)} "
                             f"problem(s)):\n  " + "\n  ".join(problems[:20]))
        log(f"read back: {n_changed} changed object(s) hold the planned bytes, {n_same} other text "
            f"object(s) and fonts are untouched"
            + (f", {rows_checked} translated row(s) read back as written" if not script else ""))
        for o in outs:
            log(f"wrote {o} ({o.stat().st_size:,} bytes)")
        log(f"done in {time.time() - t0:.0f} s. Not checked in the game: boot the copies in an emulator "
            f"before sharing a patch")
        return {"out": [str(o) for o in outs], "changed": sorted(expected), "report": report,
                "script": script, "edits": len(edits), "drafts": drafts, "target": target,
                "derived": sorted(derived),
                "work": str(work) if keep_work else None}
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# selftest: builds on clones, read back, deleted
# ---------------------------------------------------------------------------

def _sha1_file(path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(8 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _pick(rows: List[dict], fam: str, n: int, pred=lambda r: True, skip=()) -> List[dict]:
    import txfam_core as core
    out = []
    for r in rows:
        if r["fam"] == fam and not r["hide"] and not r["lock"] and r["font"] == tc.FIELD \
                and core._LETTER.search(r["src"]) and r["id"] not in skip and pred(r):
            out.append(r)
            if len(out) >= n:
                break
    return out


def _sample_edits(state, text_fn, per_fam: int = 3) -> Dict[str, str]:
    """A few offered rows of every family (and of each kind inside it), edited."""
    rows = list(state.by_id.values())
    picks: List[dict] = []
    picks += _pick(rows, "sb", per_fam, lambda r: r["ctx"] and "\n" in r["src"],
                   skip=state.japanese)                      # dialogue with a speaker, 2+ lines
    picks += _pick(rows, "sb", 1, lambda r: r["cat"] in ("Battle messages", "Dialogue — battle scenes"),
                   skip=state.japanese)
    picks += _pick(rows, "mnu", per_fam, lambda r: r["cat"] == "Menu text", skip=state.japanese)
    picks += _pick(rows, "mnu", per_fam, lambda r: r["cat"] != "Menu text", skip=state.japanese)
    picks += _pick(rows, "bat", per_fam, lambda r: r["cat"].startswith("Battle"), skip=state.japanese)
    picks += _pick(rows, "bat", per_fam, lambda r: r["cat"].startswith("HaKox"), skip=state.japanese)
    for cat in ("Movie subtitles", "Event subtitles", "Battle voice subtitles", "Story recap messages"):
        picks += _pick(rows, "sub", 2, lambda r, c=cat: r["cat"] == c, skip=state.japanese)
    # one movie subtitle of each disc's own chain, so both discs get a disc-only edit
    for chain in (1, 2):
        picks += _pick(rows, "sub", 1, lambda r, c=chain: state.slots[r["id"]].obj.chain == c, skip=state.japanese)
    seen, out = set(), {}
    for r in picks:
        if r["id"] not in seen:
            seen.add(r["id"])
            out[r["id"]] = text_fn(r)
    return out


def selftest(iso: str, scratch: Optional[str] = None, script_case: bool = True, full_hash: bool = True) -> int:
    """Builds on clones in ``scratch`` (same volume as the images = APFS
    clones), every one read back and deleted."""
    import txdiscs
    import txfam_core as core
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what, flush=True)
        ok = ok and bool(cond)

    work = Path(tempfile.mkdtemp(prefix="xs3tx-selftest-", dir=scratch))
    logs: List[str] = []
    try:
        isos = txdiscs.pair(iso)
        state = core.load(iso)
        rid = txproject.retail_id(iso)
        display = state.region.codec
        print(f"     {txdiscs.describe(iso)}")

        def project(name, edits, language, target=None):
            p = txproject.new_project(language, rid)
            p["translations"] = {k: {"text": v, "state": "done"} for k, v in edits.items()}
            if target:
                p["target"] = target
            fp = work / name
            txproject.save(str(fp), p)
            return str(fp)

        def outdir(name):
            return str(work / name) if len(isos) == 2 else str(work / (name + ".iso"))

        # 1. an unedited project: every translation is the original text
        same = _sample_edits(state, lambda r: r["src"])
        t = time.time()
        try:
            build(project("same.json", same, "en"), iso, outdir("same"), log=logs.append)
            check(False, "a project that changes nothing is refused unless asked")
        except BuildError as e:
            check("nothing to write" in str(e), "a project that changes nothing is refused (nothing to write)")
        res = build(project("same.json", same, "en"), iso, outdir("same"), log=logs.append, identity_ok=True)
        if full_hash:
            eq = [_sha1_file(a) == _sha1_file(b) for a, b in zip(isos, res["out"])]
            check(all(eq), f"unedited project ({len(same)} rows, every family): the {len(isos)} cop"
                           f"{'ies are' if len(isos) > 1 else 'y is'} byte-identical to the retail image(s), "
                           f"whole-image sha1 ({time.time() - t:.0f} s)")
        else:
            check(not res["changed"], f"unedited project ({len(same)} rows): no object changes")
        for o in res["out"]:
            os.unlink(o)

        # 2. a builtin-language project: letters the disc's own fonts draw
        mark = " ¿Sí? ñ" if display == "us" else "　テスト済"
        edits = _sample_edits(state, lambda r: (r["src"] + mark) if "\n" not in r["src"] or r["id"].startswith("sub:")
                              else r["src"] + "\n" + mark.strip())
        fams = sorted({k.split(":")[0] for k in edits})
        # a townsperson's line whose <k...> keyword a KeyWait waits for: translate the tag only
        kw = next((k for k, found in sorted(state.links.items()) if len(found) == 1 and len(found[0][1]) == 1
                   and found[0][0] not in state.japanese and not state.by_id[found[0][0]]["hide"]), None)
        kline = state.links[kw][0][0] if kw else None
        kword = ("clave ñ" if display == "us" else "合言葉")
        if kw:
            ksrc = state.by_id[kw]["src"]
            edits[kline] = state.by_id[kline]["src"].replace(f"<k{ksrc}>", f"<k{kword}>")
        t = time.time()
        res = build(project("es.json", edits, "es" if display == "us" else "ja"), iso, outdir("es"),
                    log=logs.append)
        back = core.load_set([str(Path(o).resolve()) for o in res["out"]], cache=False)
        good = sum(1 for k, v in edits.items()
                   if k in back.by_id and back.by_id[k]["src"] ==
                   (tc.fix_line_count(state.by_id[k]["src"], v) if k.startswith("sb:") else v))
        check(good == len(edits) and fams == ["bat", "mnu", "sb", "sub"],
              f"builtin build: {good}/{len(edits)} edited rows of {fams} decode back to the edited text "
              f"({len(res['changed'])} objects, {time.time() - t:.0f} s)")
        if kw:
            want_raw = tc.from_display(kword, tc.FIELD, display, ctx=state.ctx)[0]
            check(res["derived"] == [kw] and back.slots[kw].raw == want_raw
                  and want_raw in core._KTAG_RAW.findall(back.slots[kline].raw) and not core.check_links(state, back),
                  f"a translated <k...> tag carries its keyword: {kw.split(':', 1)[1]} now holds the bytes of "
                  f"the tag in {kline.split('#')[1]} ({kword!r}); every keyword of the copy still matches its tag")
        import textpack
        _n, n_same, problems = verify_objects(isos, res["out"], {})     # {}: every difference is listed
        touched = {textpack._norm(p) for p in res["changed"]}
        other = [p for p in problems if p.split(": ")[0] not in touched]
        check(not other and len(problems) == len(touched),
              f"only the {len(touched)} planned objects differ from retail; {n_same - len(touched)} others identical"
              + (f" ({other[:2]})" if other else ""))
        if len(isos) == 2:
            chains = sorted({state.objs[textpack._norm(p)].chain for p in res["changed"]})
            check(chains == [0, 1, 2], f"the build wrote chain 0 (both discs) and each disc's own chain {chains}")
        lrow = next((k for k in edits if k.startswith("sb:") and "<l" in state.by_id[k]["src"]), None)
        if lrow:
            check(back.by_id[lrow]["src"].count("\n") + 1 ==
                  int(tc._LTAG_RE.search(back.by_id[lrow]["src"]).group(1)),
                  "<lN> of a dialogue line follows its new line count")
        for o in res["out"]:
            os.unlink(o)

        # 3. refusals: nothing written
        bad_letter = "Ж" if display == "us" else "é"
        any_id = next(k for k in edits if k != kline)
        nat = "es" if display == "us" else "ja"
        cases = [("a letter the disc cannot draw (builtin language)", {any_id: "x" + bad_letter}, nat, "cannot be built", None),
                 ("an unknown row id", {"sb:nope#0000": "x"}, "es", "does not have", None),
                 ("an id of no family", {"zz:1": "x"}, "es", "no family", None)]
        if kw:
            lsrc = state.by_id[kline]["src"]
            no_tag = lsrc.replace(f"<k{state.by_id[kw]['src']}>", state.by_id[kw]["src"])
            cases += [("a keyword row changed by hand (it follows its line's <k...> tag)", {kw: "x"}, nat, "locked", None),
                      ("a line whose <k...> keyword tag was removed", {kline: no_tag}, nat, "keyword tag", None)]
            hyb = ("fr", "œ") if display == "us" else ("es", "ñ")      # a letter this disc lacks: the new-letter path
            if txtarget.shaping_available()[0]:
                other = next(k for k in edits if k.startswith("mnu:"))
                cases += [("the same removed tag when another row needs new letters (the new-letter build path)",
                           {kline: no_tag, other: state.by_id[other]["src"] + " " + hyb[1]}, hyb[0], "keyword tag", None)]
        for name, e2, lang, want, _x in cases:
            try:
                build(project("bad.json", e2, lang), iso, outdir("bad"), log=logs.append)
                check(False, f"refused: {name}")
            except BuildError as e:
                check(want in str(e) and not any(Path(p).exists() for p in out_paths(isos, outdir("bad"))),
                      f"refused, nothing written: {name}")
        p = txproject.load(project("rid.json", edits, "es"))
        p["retail_id"] = "0" * 40
        txproject.save(str(work / "rid.json"), p)
        try:
            build(str(work / "rid.json"), iso, outdir("rid"), log=logs.append)
            check(False, "refused: a project made for another disc set")
        except BuildError as e:
            check("different disc set" in str(e), "refused: a project made for another disc set")

        # 4. a language whose letters are drawn from a font (langpack)
        ttf = txtarget._find_font("Arial.ttf", "DejaVuSans.ttf", "NotoSans-Regular.ttf")
        if script_case and ttf and txtarget.shaping_available()[0]:
            if display == "us":
                lang, word, tgt = "ru", "Проверка", {"code": "ru", "font": ttf}
            else:
                lang, word, tgt = "fr", "Élève à côté", {"code": "fr", "font": ttf}
            edits = _sample_edits(state, lambda r: (tc.speaker_of(r["src"]) and f"[{tc.speaker_of(r['src'])}]" or "")
                                  + word + ("<f>" if "<f>" in r["src"] else ""), per_fam=2)
            t = time.time()
            res = build(project("script.json", edits, lang, tgt), iso, outdir("script"), log=logs.append,
                        keep_work=str(work / "script-work"))
            check(res["script"] and any("font0.bin" in p.lower() for p in res["changed"]),
                  f"new-letter build ({lang}, {Path(ttf).name}): {len(edits)} rows, {len(res['changed'])} objects "
                  f"incl. both fonts, read back ({time.time() - t:.0f} s)")
            import langpack
            rid0 = next(k for k in edits if k.startswith("sb:"))
            slot = state.slots[rid0]
            data, addr, fonts = langpack.read_back(res["out"][0], slot.obj.path, slot.key)
            png = work / "script-readback.png"
            widths = langpack.preview_png(addr, fonts[0], data, str(png), 2)
            keep = Path(scratch or tempfile.gettempdir()) / f"txbuild-selftest-{lang}.png"
            shutil.copyfile(png, keep)
            check(sum(widths) > 0 and data != slot.raw,
                  f"the patched disc's own font draws the written line ({widths} px; picture: {keep})")
            for o in res["out"]:
                os.unlink(o)
        else:
            print("skip  new-letter build (no Arial / DejaVu / Noto Sans font, or shaping unavailable)")

        # 5. a language that lacks only a few letters, with NO font in the project: the
        # build takes them from the kit's own font (French on the USA discs: œ Œ Ÿ)
        if script_case and txtarget.shaping_available()[0] and txtarget.BUNDLED_FONT.is_file():
            with tc.disc(state.ctx):
                prof = txtarget.profile("fr" if display == "us" else "es")
            lack = prof["lacking"]
            lang = prof["code"]
            three = "".join(c for c in ("œŒŸ" if display == "us" else "ñ¿é") if c in lack)
            sentence = ("Œuvre, cœur, L'Haÿ, Ÿ" if display == "us" else "¿Señor? ¡Sí, café!")
            rows = [r for r in state.rows["sb"] if r["use"] in ("event", "box") and r["ctx"] and not r["hide"]
                    and r["id"] not in state.japanese][:2]
            e5 = {r["id"]: f"[{r['ctx']}]{sentence}" + ("<f>" if "<f>" in r["src"] else "") for r in rows}
            if kw:                              # and a keyword with one of the new letters in it
                e5[kline] = state.by_id[kline]["src"].replace(f"<k{state.by_id[kw]['src']}>", f"<k{three[0]}uf>")
            t = time.time()
            logs5: List[str] = []
            res = build(project("auto.json", e5, lang), iso, outdir("auto"), log=logs5.append)
            fa = (res["target"] or {}).get("font_auto") or {}
            check(prof["kind"] == "script-hybrid" and prof["ready"] == "auto" and res["script"]
                  and fa.get("source") == "bundled" and any("DejaVu Sans" in ln for ln in logs5),
                  f"{prof['name']} with no font chosen: the language list says ready, the build takes "
                  f"{' '.join(three)} from {fa.get('label')} and says so ({time.time() - t:.0f} s)")
            import langpack
            slot = state.slots[rows[0]["id"]]
            data, addr, fonts = langpack.read_back(res["out"][0], slot.obj.path, slot.key)
            retail_fonts = state.ctx.fonts
            body = tc._SPEAKER_RAW_RE.sub(b"", tc._TAG_RAW_RE.sub(b"", data))
            new_codes, inks, seen, i = [], [], set(), 0
            while i < len(body):                # every character code of the line, drawn by both fonts
                g = addr.glyph(body, i, True, 0)
                code = body[i:i + g.length]
                i += g.length
                if code in seen:
                    continue
                seen.add(code)
                img, w = langpack.render_bytes(addr, fonts[0], code, True, True, 0)
                img0, _w0 = langpack.render_bytes(state.ctx.addr, retail_fonts[0], code, True, True, 0)
                if img != img0:                 # a cell the build drew
                    new_codes.append(code)
                    inks.append((sum(1 for row in img for v in row if v), w, True))
            want_n = len({c for c in sentence if c in lack})
            check(want_n <= len(new_codes) <= 2 * want_n and all(n > 0 and w > 0 and diff for n, w, diff in inks),
                  f"the patched disc's own font draws the line back: the {want_n} new letters took {len(new_codes)} "
                  f"cell(s) ({', '.join(c.hex() for c in new_codes)}; a wide letter such as Œ takes two), each with "
                  f"ink and a width ({[(n, w) for n, w, _d in inks]}: px of ink, advance), each a cell retail "
                  f"draws otherwise")
            png = work / "auto-readback.png"
            widths = langpack.preview_png(addr, fonts[0], data, str(png), 2)
            keep = Path(scratch or tempfile.gettempdir()) / f"txbuild-selftest-{lang}-auto.png"
            shutil.copyfile(png, keep)
            print(f"     the line as the patched disc draws it ({widths} px): {keep}")
            if kw:
                back = core.load_set([str(Path(o).resolve()) for o in res["out"]], cache=False)
                tags = core._KTAG_RAW.findall(back.slots[kline].raw)
                check(back.slots[kw].raw in tags and back.slots[kw].raw != state.slots[kw].raw
                      and not core.check_links(state, back),
                      f"new-letter build: the keyword's bytes on the disc ({back.slots[kw].raw.hex()}) are the "
                      f"bytes of its line's <k...> tag, new letter code included")
            for o in res["out"]:
                os.unlink(o)
        else:
            print("skip  the no-font build (shaping unavailable or fonts/DejaVuSans.ttf missing)")
    except BuildError as e:
        check(False, f"build failed: {e}")
        print("\n".join(logs[-30:]))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# cli.py integration (COMMAND_MODULES / SELF_TESTS)
# ---------------------------------------------------------------------------

def _cmd_tx_build(a) -> int:
    try:
        build(a.project, a.retail, a.out, overwrite=a.overwrite, disc2=a.disc2)
    except (BuildError, tc.TxBuildError, txproject.ProjectError, ValueError) as e:
        print(f"tx-build: {e}", file=sys.stderr)
        return 1
    return 0


def _cmd_tx_catalog(a) -> int:
    import json
    import txcatalog
    import txdiscs
    if a.disc2:
        txdiscs.set_partner(a.iso, a.disc2)
    cat = txcatalog.build_catalog(a.iso)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    shown = sum(1 for r in cat["rows"] if not r.get("hide"))
    print(f"{len(cat['rows'])} strings ({shown} offered for translation, {len(cat['cats'])} categories) -> {out}")
    for n in cat.get("notes", []):
        print("  " + n)
    return 0


def _cmd_tx_selftest(a) -> int:
    return selftest_all(a.iso, a.scratch, a.jp)


def _cmd_tx_cache(a) -> int:
    import txcache
    if a.clear:
        r = txcache.clear()
        print(f"removed {r['removed']} file(s), {r['bytes'] / 1e6:.1f} MB, from {r['path']}")
    else:
        print(txcache.describe())
    return 0


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("tx-build", help="translation editor: build patched disc COPIES from a project "
                                               "(.json); Disc 1 + Disc 2 together, nothing written on any error")
    p.add_argument("--project", required=True, help="translation-editor project (.json)")
    p.add_argument("--retail", required=True, help="untouched disc image, either disc (never written)")
    p.add_argument("--disc2", help="the other disc of the set, when it is not next to --retail")
    p.add_argument("--out", required=True, help="output folder (OUT/<source name> per disc); one .iso path "
                                                "for a single-disc set")
    p.add_argument("--overwrite", action="store_true", help="replace output images that already exist")
    p.set_defaults(func=_cmd_tx_build)
    p = subparsers.add_parser("tx-catalog", help="translation editor: every translatable string of a disc set "
                                                 "as one JSON catalog")
    p.add_argument("--iso", required=True, help="disc image, either disc")
    p.add_argument("--disc2", help="the other disc of the set, when it is not next to --iso")
    p.add_argument("--out", required=True, help="JSON file to write")
    p.set_defaults(func=_cmd_tx_catalog)
    p = subparsers.add_parser("tx-selftest", help="translation editor: every check against a real disc set, "
                                                  "including builds on clones (read back, then deleted)")
    p.add_argument("--iso", required=True, help="disc image, either disc")
    p.add_argument("--jp", help="a Japanese disc: also check the Japanese-original pairing")
    p.add_argument("--scratch", help="folder for the clones (same volume as the images)")
    p.set_defaults(func=_cmd_tx_selftest)
    p = subparsers.add_parser("tx-cache", help="translation editor: where its cache is and how big; --clear "
                                               "deletes it (set XS3_TX_CACHE to keep it elsewhere)")
    p.add_argument("--clear", action="store_true", help="delete the cache's entries (projects are never in it)")
    p.set_defaults(func=_cmd_tx_cache)


def _quiet(fn) -> Tuple[int, str]:
    """Run a selftest, keep its output; -> (rc, text)."""
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = fn() or 0
    except Exception as exc:                                       # noqa: BLE001
        import traceback
        buf.write(traceback.format_exc())
        buf.write(f"raised {type(exc).__name__}: {exc}\n")
        rc = 1
    return rc, buf.getvalue()


def _steps(steps) -> int:
    bad = 0
    for name, fn in steps:
        t = time.time()
        rc, text = _quiet(fn)
        n_ok = sum(1 for ln in text.splitlines() if ln.startswith("ok   "))
        print(f"{'ok   ' if not rc else 'FAIL '}{name} ({n_ok} checks, {time.time() - t:.1f} s)", flush=True)
        if rc:
            bad += 1
            for ln in text.splitlines():
                if not ln.startswith("ok   "):
                    print("     | " + ln)
    return bad


def selftest_all(iso: str, scratch: Optional[str] = None, jp: Optional[str] = None) -> int:
    """Every editor module against a real disc set (``tx-selftest``)."""
    import txbackup
    import txcatalog
    import txdiscs
    import txfam_core
    import txserver
    import txsource
    import txcache
    steps = [
        ("backups (txbackup)", txbackup.selftest),
        ("the cache: where, how much, what it deletes (txcache)", txcache.self_test),
        ("script strings by what the code does with them; keywords (txfam_core)", txfam_core.selftest_roles),
        ("disc set (txdiscs)", lambda: txdiscs.selftest(iso)),
        ("project files (txproject)", lambda: txproject.selftest(iso)),
        ("codec against the disc's fonts (txcodec)", lambda: tc.selftest(iso)),
        ("the four families: read, encode back, plan (txfam_core)", lambda: txfam_core.selftest(iso)),
        ("catalog from the discs (txcatalog)", lambda: txcatalog.selftest(iso)),
        ("languages, coverage, a new-letter preview (txtarget)", lambda: txtarget.selftest(iso)),
        ("every server route on a socket, real catalog (txserver)", lambda: txserver.selftest(iso)),
        ("builds on clones: unedited, builtin, refusals, new letters (txbuild)", lambda: selftest(iso, scratch)),
    ]
    if jp:
        steps.insert(-1, ("the Japanese original paired with the rows (txsource)", lambda: txsource.selftest(iso, jp)))
        steps.insert(-1, ("two disc sets in one server, requests interleaved (txserver)",
                          lambda: txserver.selftest_two(iso, jp)))
    bad = _steps(steps)
    print("tx-selftest", "passed" if not bad else f"FAILED ({bad} step(s))")
    return 1 if bad else 0


def self_test() -> int:
    """cli.py ``self-test``: the editor's synthetic checks (no disc), then the
    disc checks for the images named by XS3_D1 / XS3_JP1 (read-only: the
    builds on clones run under ``tx-selftest``)."""
    import txbackup
    import txcatalog
    import txdiscs
    import txfam_core
    import txserver
    import txsource
    import txcache
    steps = [
        ("translation editor: the cache (txcache)", txcache.self_test),
        ("translation editor: script strings by code use, keywords (txfam_core)", txfam_core.selftest_roles),
        ("translation editor: backups (txbackup)", txbackup.selftest),
        ("translation editor: disc-set rules (txdiscs)", lambda: txdiscs.selftest(None)),
        ("translation editor: project files (txproject)", lambda: txproject.selftest(None)),
        ("translation editor: catalog shape (txcatalog)", lambda: txcatalog.selftest(None)),
        ("translation editor: display form and checks (txcodec)", lambda: tc.selftest(None)),
        ("translation editor: languages and coverage (txtarget)", lambda: txtarget.selftest(None)),
        ("translation editor: every server route on a socket, sample catalog (txserver)",
         lambda: txserver.selftest(None)),
    ]
    d1, j1 = os.environ.get("XS3_D1"), os.environ.get("XS3_JP1")
    for label, iso in (("USA", d1), ("Japan", j1)):
        if not iso or not Path(iso).is_file():
            print(f"SKIP  translation editor disc checks, {label} (set {'XS3_D1' if label == 'USA' else 'XS3_JP1'})")
            continue
        steps += [
            (f"translation editor, {label}: disc set (txdiscs)", lambda i=iso: txdiscs.selftest(i)),
            (f"translation editor, {label}: codec against the disc's fonts (txcodec)", lambda i=iso: tc.selftest(i)),
            (f"translation editor, {label}: the four families (txfam_core)", lambda i=iso: txfam_core.selftest(i)),
            (f"translation editor, {label}: catalog (txcatalog)", lambda i=iso: txcatalog.selftest(i)),
            (f"translation editor, {label}: server routes, real catalog (txserver)", lambda i=iso: txserver.selftest(i)),
        ]
    if d1 and j1 and Path(d1).is_file() and Path(j1).is_file():
        steps.append(("translation editor: the Japanese original paired with the USA rows (txsource)",
                      lambda: txsource.selftest(d1, j1)))
        steps.append(("translation editor: two disc sets in one server, requests interleaved (txserver)",
                      lambda: txserver.selftest_two(d1, j1)))
    bad = _steps(steps)
    print("txbuild self-test", "OK" if not bad else f"FAILED ({bad})")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build translated disc image(s) from a project")
    b.add_argument("--project", required=True)
    b.add_argument("--retail", required=True, help="either disc of the untouched set")
    b.add_argument("--disc2", help="the other disc, when it is not next to --retail")
    b.add_argument("--out", required=True, help="output folder (two discs) or .iso (one disc)")
    b.add_argument("--overwrite", action="store_true")
    s = sub.add_parser("selftest")
    s.add_argument("--iso", required=True)
    s.add_argument("--scratch", help="folder for the clones (same volume as the images)")
    s.add_argument("--no-script", action="store_true", help="skip the new-letter (langpack) build")
    s.add_argument("--no-hash", action="store_true", help="skip the whole-image sha1 of the unedited build")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest(a.iso, a.scratch, not a.no_script, not a.no_hash)
    try:
        build(a.project, a.retail, a.out, overwrite=a.overwrite, disc2=a.disc2)
    except (BuildError, tc.TxBuildError, txproject.ProjectError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
