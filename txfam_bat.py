"""txfam_bat.py — translation-editor family "bat" of Episode III: battle names and descriptions (``bat\\xx\\batdat.bin``, 20 tables) and the HaKox
mini-game messages (``mg1\\xx\\Message.Dat``).

textpack kind(s): batdat, msgdat. The reading, the checks and the rebuild are shared
by the four families and live in ``txfam_core`` (row schema, ids, rules);
this module is the family's name in ``txcatalog.FAMILIES`` and its entry
points, the same ones the Episode I families have except ``apply``: Episode
III objects are written by ``txbuild`` in ONE ``patch.patch_copy`` over both
discs, so a family returns its change set (``plan``) instead of patching an
image on its own.

    rows(iso) -> [row]                       validate(edits, iso) -> {id: [errors]}
    warnings(edits, iso) -> {id: [warnings]}  plan(edits, iso) -> ({path: bytes}, report)
    read_back(out_isos, ids) -> {id: text}

    python txfam_bat.py selftest --iso DISC
"""
from __future__ import annotations

import sys
from typing import Dict, List, Optional

import txfam_core as core

FAM = "bat"
KINDS = core.FAM_KINDS[FAM]


def rows(iso_path: str) -> List[dict]:
    return core.rows(iso_path, FAM)


def validate(edits: Dict[str, str], iso_path: Optional[str] = None) -> Dict[str, List[str]]:
    return core.validate(edits, iso_path, FAM)


def warnings(edits: Dict[str, str], iso_path: Optional[str] = None) -> Dict[str, List[str]]:
    return core.warnings(edits, iso_path, FAM)


def check_row(rid: str, text: str, iso_path: str):
    """(errors, warnings) of one row checked on its own (the editor while typing)."""
    return core.check_row(rid, text, iso_path)


def plan(edits: Dict[str, str], iso_path: str):
    return core.plan(edits, iso_path, FAM)


def read_back(out_isos: List[str], ids: List[str]) -> Dict[str, Optional[str]]:
    return core.read_back(out_isos, ids)


def selftest(iso_path: str, scratch: Optional[str] = None) -> int:
    return core.selftest(iso_path, FAM)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest")
    s.add_argument("--iso", required=True)
    a = ap.parse_args(argv)
    return selftest(a.iso)


if __name__ == "__main__":
    sys.exit(main())
