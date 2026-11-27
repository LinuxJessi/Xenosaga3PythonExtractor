"""txtarget.py — the language a translation goes INTO, and how a build draws it (Episode III).

The profile table, the language registry (``txlangs``), ``normalise_target`` /
``resolve_target``, ``coverage`` and the installed-font index are the Episode I
editor's, unchanged in shape (see MODULES in docs/TRANSLATION-EDITOR.md for the
few lines that differ). What a build DOES with a target is Episode III's own,
because this kit already has the whole pipeline in ``langpack``:

* **builtin** — every letter is one the disc's fonts draw: on the USA discs
  Latin-1 (French, Spanish, German, Italian, Portuguese, the Nordic
  languages...) and a few symbol pairs; on the Japanese discs Japanese, and
  the Greek and Cyrillic of the JIS rows. ``txcodec`` writes the codes; no
  font is touched. ``txbuild`` hands the changed objects to
  ``patch.patch_copy``.
* **script-hybrid / script / japanese** — some or all letters are not in the
  disc's fonts (Polish ł, Russian on the USA discs, Arabic, Devanagari,
  Hangul, Japanese on the USA discs, French é on the Japanese discs...).
  ``build_script`` then runs the kit's new-script pipeline on the project:

      1. ``textpack.export_discs``: the text tree of the retail set;
      2. the project's translations are written into that tree (block files:
         the body under each ``### KEY``; whole files: the edited lines);
      3. ``langpack.scan``: every letter the disc cannot draw gets a font cell
         (the build's slot model, cells retail text draws reserved), shaped
         with HarfBuzz and drawn from the target's TrueType font into
         font0.bin and font1.bin;
      4. ``langpack.encode``: each translated string is shaped, ordered (UAX #9
         for right-to-left), wrapped when a width is set, and written with the
         new cells' codes; tags, ``$`` commands and control bytes pass through;
      5. ``langpack.import_pack``: text + fonts into verified copies of both
         discs.

  Nothing derived is stored in the project: the tree, the pack and the fonts
  are regenerated from the retail discs and the project on every build.

Kinds are decided against the disc that is open (``txcodec.active()``; the USA
rules when none is): the same language can be builtin on one base and need new
letters on another. ``TARGETS`` holds the USA answer; ``profile`` /
``languages`` / ``resolve_target`` re-decide for the active disc.

Not done here (Episode I has them, Episode III has no counterpart): a second
battle font (Episode III's battle HUD letters are pictures, ``statfont``), and
the capital-accent font fix.

    python3 txtarget.py list
    python3 txtarget.py fonts --script Cyrl
    python3 txtarget.py coverage --code pl --text "Zażółć gęślą jaźń"
    python3 txtarget.py selftest --iso DISC [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import txcodec as tc  # noqa: E402

KINDS = ("builtin", "script-hybrid", "japanese", "script")
# The font a build takes a FEW missing Latin letters from when the project names
# none (``auto_font``): DejaVu Sans 2.37, shipped in fonts/ with its licence
# (Bitstream Vera licence; DejaVu's changes are public domain).
BUNDLED_FONT = ROOT / "fonts" / "DejaVuSans.ttf"
BUNDLED_LABEL = "DejaVu Sans (comes with the kit)"


class TargetError(tc.TxBuildError):
    """A target the build cannot draw; the message says why (per row id)."""


# ---------------------------------------------------------------------------
# rendering defaults per script
# ---------------------------------------------------------------------------
# px = em size, baseline = the cell row langpack puts the baseline on. Episode III's
# retail Latin sits in the 20x24 cell with capitals on rows 6-18 and descenders
# to row 22 (measured from USA font0: H, x, p). langpack's defaults, px 20 on
# baseline 17, are the values the kit's in-game captures were made with
# (SCRIPTS.md); Devanagari uses 17 on 16 to keep stacked marks inside the cell.
# xscale is kept in the target for project compatibility with the Episode I
# editor; Episode III's langpack has no horizontal squeeze and ignores it.
# Han, kana and Hangul use 17 on 17: the ink then stays inside rows 2-18 and
# columns 1-17, close to the Japanese retail font's kanji (rows 4-18, columns
# 1-18, measured from JP Disc 1 font0). At px 20 they filled the cell edge to
# edge (rows 0-18, columns 0-19) and the game's filtered draw showed thin
# vertical lines between characters (seen in PCSX2, 2026-11-21).
_CJK_RENDER = {"px": 17.0, "baseline": 17, "xscale": 1.0}
RENDER: Dict[str, dict] = {
    "Deva": {"px": 17.0, "baseline": 16, "xscale": 1.0},
    "Hani": _CJK_RENDER, "Jpan": _CJK_RENDER, "Hang": _CJK_RENDER,
    "Kore": _CJK_RENDER, "Hira": _CJK_RENDER, "Kana": _CJK_RENDER, "Bopo": _CJK_RENDER,
}
BATTLE_RENDER = {"battle_px": 20.0, "battle_baseline": 17, "battle_xscale": 0.55}
_DEFAULT_RENDER = {"px": 20.0, "baseline": 17, "xscale": 1.0}

# Noto families that cover each script (free, SIL OFL)
NOTO: Dict[str, List[str]] = {
    "Latn": ["Noto Sans", "Noto Serif"], "Cyrl": ["Noto Sans", "Noto Serif"],
    "Grek": ["Noto Sans", "Noto Serif"], "Armn": ["Noto Sans Armenian"],
    "Geor": ["Noto Sans Georgian"], "Hebr": ["Noto Sans Hebrew"],
    "Arab": ["Noto Sans Arabic", "Noto Naskh Arabic"], "Deva": ["Noto Sans Devanagari"],
    "Thai": ["Noto Sans Thai"], "Ethi": ["Noto Sans Ethiopic"],
    "Hang": ["Noto Sans KR"], "Hani": ["Noto Sans SC", "Noto Sans TC"],
    "Jpan": ["Noto Sans JP"],
}

# Characters a font must have to count as covering a script (system_fonts).
_PROBE: Dict[str, str] = {
    "Latn": "ąćęłńśźżčďěňřšťůžőűășțğışđĉĝĥĵŝŭ",
    "Cyrl": "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯіїєґ",
    "Grek": "αβγδεζηθικλμνξοπρστυφχψωςάέήίόύώΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ",
    "Armn": "ԱԲԳԴԵԶԷԸԹԺԻԼԽԾԿՀՁՂՃՄՅՆՇՈՉՊՋՌՍՎՏՐՑՒՓՔՕՖաբգդեզէըթժիլխծկհձղճմյնշոչպջռսվտրցւփքօֆ",
    "Geor": "აბგდევზთიკლმნოპჟრსტუფქღყშჩცძწჭხჯჰ",
    "Hebr": "אבגדהוזחטיכךלמםנןסעפףצץקרשת",
    "Arab": "ءآأؤإئابةتثجحخدذرزسشصضطظعغفقكلمنهوىيپچژگکی،؟",
    "Deva": "अआइईउऊएऐओऔकखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहािीुूेैोौंः्।",
    "Thai": "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮะาำิีึืุูเแโใไ่้๊๋",
    "Ethi": "ሀለሐመሠረሰሸቀበተቸኀነኘአከኸወዐዘዠየደጀገጠጨጰጸፀፈፐ።",
    "Hang": "가나다라마바사아자차카타파하한국어안녕세요",
    "Hani": "的一是不了人我在有他这中大来上国个到说们为子和你地出道也时年",
    "Jpan": "あいうえおかきくけこアイウエオカキクケコ日本語漢字",
}


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------
# (code, English name, endonym, script, rtl, alphabet beyond ASCII, sample,
#  kind for non-Latin scripts). Latin kinds are computed from the alphabet.
_RAW = [
    ("fr", "French", "Français", "Latn", False, "àâæçéèêëîïôœùûüÿÀÂÆÇÉÈÊËÎÏÔŒÙÛÜŸ«»",
     "Portez ce vieux whisky au juge blond qui fume. « Où est KOS-MOS ? »"),
    ("es", "Spanish", "Español", "Latn", False, "áéíñóúüÁÉÍÑÓÚÜ¿¡«»",
     "El veloz murciélago hindú comía feliz cardillo y kiwi. ¿Dónde está?"),
    ("de", "German", "Deutsch", "Latn", False, "äöüßÄÖÜ„“",
     "Victor jagt zwölf Boxkämpfer quer über den großen Sylter Deich."),
    ("it", "Italian", "Italiano", "Latn", False, "àèéìíîòóùúÀÈÉÌÍÎÒÓÙÚ",
     "Ma la volpe col suo balzo ha raggiunto il quieto Fido. Perché è così?"),
    ("pt", "Portuguese", "Português", "Latn", False, "áâãàçéêíóôõúÁÂÃÀÇÉÊÍÓÔÕÚ",
     "Luís argüia à Júlia que «brações, fé, chá, óxido, pôr, zângão» eram palavras."),
    ("pt-BR", "Portuguese (Brazil)", "Português (Brasil)", "Latn", False,
     "áâãàçéêíóôõúÁÂÃÀÇÉÊÍÓÔÕÚ", "À noite, vovô Kowalsky vê o ímã cair no pé do pinguim."),
    ("nl", "Dutch", "Nederlands", "Latn", False, "éëïöüèáóúÉËÏÖÜ",
     "Pa's wijze lynx bezag vroom het fikse aquaduct. Één, twee, drieëntwintig."),
    ("ca", "Catalan", "Català", "Latn", False, "àçéèíïòóúüÀÇÉÈÍÏÒÓÚÜ·",
     "Jove xef, porti whisky amb quinze glaçons d'hidrogen, coi! Col·lega."),
    ("sv", "Swedish", "Svenska", "Latn", False, "åäöÅÄÖ",
     "Flygande bäckasiner söka hwila på mjuka tuvor."),
    ("da", "Danish", "Dansk", "Latn", False, "æøåÆØÅ",
     "Høj bly gom vandt fræk sexquiz på wc."),
    ("no", "Norwegian", "Norsk", "Latn", False, "æøåÆØÅ",
     "Vår sære Zulu fra badeøya spilte jo whist og quickstep i min taxi."),
    ("fi", "Finnish", "Suomi", "Latn", False, "äöåšžÄÖÅŠŽ",
     "Törkylempijävongahdus. Šakki ja žirafi."),
    ("is", "Icelandic", "Íslenska", "Latn", False, "áðéíóúýþæöÁÐÉÍÓÚÝÞÆÖ",
     "Kæmi ný öxi hér, ykist þjófum nú bæði víl og ádrepa."),
    ("ga", "Irish", "Gaeilge", "Latn", False, "áéíóúÁÉÍÓÚ",
     "D'fhuascail Íosa Úrmhac na hÓighe Beannaithe pór Éava agus Ádhaimh."),
    ("af", "Afrikaans", "Afrikaans", "Latn", False, "êëéèîïôûÊËÉÈÎÏÔÛ",
     "Sê vir die mense: môre is ’n nuwe dag."),
    ("sq", "Albanian", "Shqip", "Latn", False, "çëÇË",
     "Unë jam KOS-MOS. Çfarë dëshironi?"),
    ("id", "Indonesian", "Bahasa Indonesia", "Latn", False, "",
     "Saya KOS-MOS. Apa yang bisa saya bantu?"),
    ("eo", "Esperanto", "Esperanto", "Latn", False, "ĉĝĥĵŝŭĈĜĤĴŜŬ",
     "Eĥoŝanĝo ĉiuĵaŭde. Laŭ Ludoviko Zamenhof bongustas freŝa ĉeĥa manĝaĵo."),
    ("pl", "Polish", "Polski", "Latn", False, "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ",
     "Zażółć gęślą jaźń. Pchnąć w tę łódź jeża lub ośm skrzyń fig."),
    ("cs", "Czech", "Čeština", "Latn", False, "áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ",
     "Příliš žluťoučký kůň úpěl ďábelské ódy."),
    ("sk", "Slovak", "Slovenčina", "Latn", False, "áäčďéíĺľňóôŕšťúýžÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ",
     "Kŕdeľ šťastných ďatľov učí pri ústí Váhu mĺkveho koňa obhrýzať kôru."),
    ("sl", "Slovenian", "Slovenščina", "Latn", False, "čšžČŠŽ",
     "Hišničin bratec vzgaja polžke še čez zimo."),
    ("hr", "Croatian", "Hrvatski", "Latn", False, "čćđšžČĆĐŠŽ",
     "Gojazni đačić s biciklom drži hmelj i finu vatu u džepu nošnje."),
    ("hu", "Hungarian", "Magyar", "Latn", False, "áéíóöőúüűÁÉÍÓÖŐÚÜŰ",
     "Árvíztűrő tükörfúrógép."),
    ("ro", "Romanian", "Română", "Latn", False, "ăâîșțĂÂÎȘȚ",
     "Înjurând pițigăiat, zoofobul comandă vexat whisky și tequila."),
    ("tr", "Turkish", "Türkçe", "Latn", False, "çğıİöşüÇĞÖŞÜ",
     "Pijamalı hasta yağız şoföre çabucak güvendi."),
    ("et", "Estonian", "Eesti", "Latn", False, "äöõüšžÄÖÕÜŠŽ",
     "Põdur Zagrebi tšellomängija-följetonist Ciqo külmetas kehvas garaažis."),
    ("lt", "Lithuanian", "Lietuvių", "Latn", False, "ąčęėįšųūžĄČĘĖĮŠŲŪŽ",
     "Įlinkdama fechtuotojo špaga sublykčiojusi pragręžė apvalų arbūzą."),
    ("lv", "Latvian", "Latviešu", "Latn", False, "āčēģīķļņšūžĀČĒĢĪĶĻŅŠŪŽ",
     "Glāžšķūņa rūķīši dzērumā čiepj Baha koncertflīģeļu vākus."),
    ("vi", "Vietnamese", "Tiếng Việt", "Latn", False,
     "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđĐ",
     "Tôi là KOS-MOS. Bạn cần giúp gì không?"),
    ("ja", "Japanese", "日本語", "Jpan", False, "", "こんにちは、シオン。漢字と仮名、そして叡智。",
     "japanese"),
    ("ru", "Russian", "Русский", "Cyrl", False, _PROBE["Cyrl"][:66],
     "Съешь же ещё этих мягких французских булок, да выпей чаю.", "script"),
    ("uk", "Ukrainian", "Українська", "Cyrl", False,
     "абвгґдеєжзиіїйклмнопрстуфхцчшщьюяАБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ’",
     "Чуєш їх, доцю, га? Кумедна ж ти, прощайся без ґольфів!", "script"),
    ("bg", "Bulgarian", "Български", "Cyrl", False,
     "абвгдежзийклмнопрстуфхцчшщъьюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЬЮЯ",
     "Жълтата дюля беше щастлива, че пухът, който цъфна, замръзна като гьон.", "script"),
    ("sr", "Serbian (Cyrillic)", "Српски", "Cyrl", False,
     "абвгдђежзијклљмнњопрстћуфхцчџшАБВГДЂЕЖЗИЈКЛЉМНЊОПРСТЋУФХЦЧЏШ",
     "Фијуче ветар у шибљу, леди пасаже и куће иза њих и гунђа у оџацима.", "script"),
    ("el", "Greek", "Ελληνικά", "Grek", False, _PROBE["Grek"],
     "Ξεσκεπάζω την ψυχοφθόρα βδελυγμία.", "script"),
    ("hy", "Armenian", "Հայերեն", "Armn", False, _PROBE["Armn"],
     "Բարեւ, աշխարհ։", "script"),
    ("ka", "Georgian", "ქართული", "Geor", False, _PROBE["Geor"],
     "გამარჯობა, სამყარო!", "script"),
    ("ar", "Arabic", "العربية", "Arab", True, _PROBE["Arab"][:44],
     "مرحبا بالعالم! أنا KOS-MOS (3).", "script"),
    ("fa", "Persian", "فارسی", "Arab", True, _PROBE["Arab"],
     "سلام دنیا! من KOS-MOS هستم.", "script"),
    ("he", "Hebrew", "עברית", "Hebr", True, _PROBE["Hebr"],
     "שלום עולם! אני KOS-MOS.", "script"),
    ("hi", "Hindi", "हिन्दी", "Deva", False, _PROBE["Deva"],
     "नमस्ते दुनिया! मैं KOS-MOS हूँ।", "script"),
    ("th", "Thai", "ไทย", "Thai", False, _PROBE["Thai"],
     "สวัสดีชาวโลก", "script"),
    ("am", "Amharic", "አማርኛ", "Ethi", False, _PROBE["Ethi"],
     "ሰላም ዓለም።", "script"),
    ("ko", "Korean", "한국어", "Hang", False, "", "안녕하세요, 세계! 저는 KOS-MOS입니다.", "script"),
    ("zh-Hans", "Chinese (Simplified)", "简体中文", "Hani", False, "",
     "你好，世界！我是KOS-MOS。", "script"),
    ("zh-Hant", "Chinese (Traditional)", "繁體中文", "Hani", False, "",
     "你好，世界！我是KOS-MOS。", "script"),
]

# right-to-left scripts (used for custom "other" targets too)
RTL_SCRIPTS = {"Arab", "Hebr", "Syrc", "Thaa", "Nkoo", "Adlm", "Mand", "Samr", "Rohg"}


def _native_both(ch: str) -> bool:
    """The TABLE's answer, which is for the USA discs whatever disc a caller
    has open (this runs at import): can the USA codec write ``ch``?"""
    if ord(ch) < 0x80:
        return True
    import textcodec
    try:
        textcodec.codec_by_name("us").encode_char(ch)
        return True
    except textcodec.TextError:
        return False


def _kind_of(script: str, alphabet: str, given: Optional[str]) -> Tuple[str, str]:
    """(kind, letters the retail fonts lack) for a profile."""
    if script != "Latn":
        return given or "script", ""
    lacking = "".join(c for c in dict.fromkeys(alphabet) if not _native_both(c))
    return ("builtin" if not lacking else "script-hybrid"), lacking


def _make_targets() -> List[dict]:
    out = []
    for rec in _RAW:
        code, name, endo, script, rtl, alphabet, sample = rec[:7]
        given = rec[7] if len(rec) > 7 else None
        kind, lacking = _kind_of(script, alphabet, given)
        out.append({
            "code": code, "name": name, "endonym": endo, "kind": kind, "script": script,
            "rtl": rtl, "alphabet": alphabet, "lacking": lacking, "sample": sample,
            "fonts": list(NOTO.get(script, ["Noto Sans"])),
            "render": dict(RENDER.get(script, _DEFAULT_RENDER)),
        })
    out.append({
        "code": "other", "name": "Other (custom script)", "endonym": "", "kind": "script",
        "script": "", "rtl": False, "alphabet": "", "lacking": "", "sample": "",
        "fonts": [], "render": dict(_DEFAULT_RENDER),
    })
    return out


# ---------------------------------------------------------------------------
# the language registry (txlangs.py): every other language and written form
# ---------------------------------------------------------------------------
# The 47 profiles above are the long-tested ones; txlangs adds the rest (382
# lines: Cherokee, Inuktitut, Navajo, Hawaiian, Yoruba, Tifinagh, N'Ko, Adlam,
# ...). Each registry line becomes a profile of the same shape; its kind is
# computed from its letters exactly as above. A registry line for a language
# that already has a profile only adds its regions and note.
SCRIPT_NAMES: Dict[str, str] = {
    "Latn": "Latin", "Cyrl": "Cyrillic", "Grek": "Greek", "Armn": "Armenian", "Geor": "Georgian",
    "Hebr": "Hebrew", "Arab": "Arabic", "Syrc": "Syriac", "Thaa": "Thaana", "Nkoo": "N'Ko",
    "Deva": "Devanagari", "Beng": "Bengali", "Guru": "Gurmukhi", "Gujr": "Gujarati", "Orya": "Odia",
    "Taml": "Tamil", "Telu": "Telugu", "Knda": "Kannada", "Mlym": "Malayalam", "Sinh": "Sinhala",
    "Thai": "Thai", "Laoo": "Lao", "Tibt": "Tibetan", "Mymr": "Myanmar", "Ethi": "Ethiopic",
    "Cher": "Cherokee", "Cans": "Canadian syllabics", "Khmr": "Khmer", "Mong": "Mongolian",
    "Tglg": "Baybayin", "Bugi": "Lontara", "Bali": "Balinese", "Sund": "Sundanese", "Java": "Javanese",
    "Olck": "Ol Chiki", "Mtei": "Meitei Mayek", "Vaii": "Vai", "Tfng": "Tifinagh", "Adlm": "Adlam",
    "Yiii": "Yi", "Bamu": "Bamum", "Osge": "Osage", "Hmnp": "Nyiakeng Puachue Hmong", "Lisu": "Lisu",
    "Cakm": "Chakma", "Lana": "Tai Tham", "Tavt": "Tai Viet", "Sylo": "Syloti Nagri", "Limb": "Limbu",
    "Copt": "Coptic", "Osma": "Osmanya", "Rohg": "Hanifi Rohingya", "Hang": "Hangul", "Hani": "Han",
    "Jpan": "Japanese", "Kana": "Katakana",
}
for _sc, _nm in SCRIPT_NAMES.items():
    NOTO.setdefault(_sc, ["Noto Sans " + _nm.replace("'", "").replace(" syllabics", " Canadian Aboriginal")
                          if _sc != "Cans" else "Noto Sans Canadian Aboriginal"])


def _generated(name: str) -> str:
    """Letter sets too big to type: '@ko' (KS X 1001 Hangul), '@zh-Hans'
    (GB 2312 level 1), '@zh-Hant' (Big5 frequent), '@ja' (JIS level 1 kanji +
    kana), '@iu' / '@cr' / '@oj' (Canadian syllabics by Unicode name)."""
    import unicodedata

    def rows(codec, hi, lo=(0xA1, 0xFE)):
        out = []
        for a in range(hi[0], hi[1] + 1):
            for b in range(lo[0], lo[1] + 1):
                try:
                    out.append(bytes((a, b)).decode(codec))
                except UnicodeDecodeError:
                    pass
        return "".join(out)
    if name == "ko":
        return rows("euc_kr", (0xB0, 0xC8))
    if name == "zh-Hans":
        return rows("gb2312", (0xB0, 0xD7))
    if name == "zh-Hant":
        return rows("big5", (0xA4, 0xC6), (0x40, 0xFE))
    if name == "ja":
        kana = "".join(chr(c) for c in range(0x3041, 0x3097)) + "".join(chr(c) for c in range(0x30A1, 0x30FB))
        return kana + rows("euc_jp", (0xB0, 0xCF))
    sets = getattr(_txlangs(), "CANS_SETS", {}).get(name)
    if sets:
        out = []
        for c in sets["consonants"]:
            for v in sets["vowels"]:
                for nm in (f"CANADIAN SYLLABICS {c}{v}",):
                    try:
                        out.append(unicodedata.lookup(nm))
                    except KeyError:
                        pass
        for f in sets["finals"]:
            for nm in (f"CANADIAN SYLLABICS FINAL {f}", f"CANADIAN SYLLABICS {f}"):
                try:
                    out.append(unicodedata.lookup(nm))
                    break
                except KeyError:
                    pass
        return "".join(dict.fromkeys(out))
    return ""


def _txlangs():
    try:
        import txlangs
        return txlangs
    except ImportError:
        return None


def _core(script: str) -> str:
    import unicodedata
    core = getattr(_txlangs(), "SCRIPT_CORE", {}).get(script, "")
    if isinstance(core, str):
        return _generated(core[1:]) if core.startswith("@") else core
    out = []
    for lo, hi in core:
        for cp in range(lo, hi + 1):
            ch = chr(cp)
            if unicodedata.category(ch)[0] in "LM":
                out.append(ch)
    return "".join(out)


def _letters(script: str, field: str) -> str:
    """The registry's letters field -> the alphabet (see txlangs' docstring)."""
    field = field.strip()
    base = ""
    extra = []
    for tok in field.split(" ") if field else []:
        if tok.startswith("@"):
            base += _generated(tok[1:])
        elif tok.startswith("="):
            base += tok[1:]
        else:
            extra.append(tok)
    explicit = base != ""
    extra_s = "".join(extra)
    if script == "Latn":
        ups = "".join(c.upper() for c in extra_s if len(c.upper()) == 1 and c.upper() != c)
        return "".join(dict.fromkeys(extra_s + ups))
    if not explicit:
        base = _core(script)
    letters = base + extra_s
    ups = "".join(c.upper() for c in letters if len(c.upper()) == 1 and c.upper() != c)
    return "".join(dict.fromkeys(letters + ups))


def _registry_targets(have: Dict[str, dict]) -> List[dict]:
    L = _txlangs()
    if L is None:
        return []
    samples = getattr(L, "SAMPLES", {})
    vertical = getattr(L, "VERTICAL", {})
    out = []
    for line in L.DATA.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = (line.split("|", 6) + [""] * 7)[:7]
        code, name, endo, scripts, letters, regions, note = (x.strip() for x in f)
        sc = (scripts.split() or ["Latn"])[0]
        extra = {"regions": regions.split(), "scripts": scripts.split()}
        notes = " ".join(x for x in (note, vertical.get(sc, "")) if x)
        if notes:
            extra["notes"] = notes
        if code.lower() in have:
            have[code.lower()].update(extra)
            continue
        alphabet = _letters(sc, letters)
        if sc == "Latn":
            # letters of the language's own name belong to its alphabet too (Kɪsukuma)
            own = "".join(c for c in endo if c.isalpha() and ord(c) > 0x7F)
            alphabet = "".join(dict.fromkeys(alphabet + own + "".join(
                c.upper() for c in own if len(c.upper()) == 1)))
        given = "japanese" if sc == "Jpan" else None
        kind, lacking = _kind_of(sc, alphabet, given)
        sample = samples.get(code, "")
        if not sample:
            # no sample sentence on file: the language's own name and some of its letters
            show = "".join(c for c in alphabet if c.islower() or not c.isupper())[:24]
            sample = (endo + " · KOS-MOS · " + show).strip(" ·")
        out.append(dict({
            "code": code, "name": name, "endonym": endo, "kind": kind, "script": sc,
            "rtl": sc in RTL_SCRIPTS, "alphabet": alphabet, "lacking": lacking, "sample": sample,
            "fonts": list(NOTO.get(sc, ["Noto Sans"])),
            "render": dict(RENDER.get(sc, _DEFAULT_RENDER)), "registry": True,
        }, **extra))
    return out


def _all_targets() -> List[dict]:
    base = _make_targets()
    other = base.pop()                       # "other" stays last
    have = {t["code"].lower(): t for t in base}
    for t in base:
        t.setdefault("script_name", SCRIPT_NAMES.get(t["script"], t["script"]))
    reg = _registry_targets(have)
    for t in reg:
        t["script_name"] = SCRIPT_NAMES.get(t["script"], t["script"])
    reg.sort(key=lambda t: t["name"].lower())
    return base + reg + [other]


TARGETS: List[dict] = _all_targets()
_BY_CODE = {t["code"].lower(): t for t in TARGETS}


def _languages_usa(query: str = "") -> List[dict]:
    """Every target language (the 47 tested profiles first, then the registry
    A-Z), filtered by code, English name, own name, script or region."""
    q = (query or "").strip().lower()
    out = []
    for t in TARGETS:
        if t["code"] == "other":
            continue
        hay = " ".join([t["code"], t["name"], t.get("endonym", ""), t.get("script_name", ""),
                        " ".join(t.get("regions", []))]).lower()
        if not q or q in hay or t["code"].lower() == q:
            out.append(t)
    return out


def _profile_usa(code: str) -> Optional[dict]:
    """The TARGETS entry for a language code (case-insensitive; "pt_BR" and
    "pt-br" both find pt-BR; a region falls back to the base language)."""
    if not code:
        return None
    c = code.replace("_", "-").lower()
    return _BY_CODE.get(c) or _BY_CODE.get(c.split("-", 1)[0])


# ---------------------------------------------------------------------------
# project target
# ---------------------------------------------------------------------------
_TARGET_KEYS = {
    "code": str, "kind": str, "script": str, "language": str, "rtl": bool, "font": str,
    "face": int, "px": float, "baseline": int, "xscale": float, "align": str, "wrap": int,
    "battle_font": str, "battle_face": int, "battle_px": float, "battle_baseline": int,
    "battle_xscale": float,
}


def normalise_target(t: dict) -> dict:
    """Validate ``project["target"]``; returns a clean copy with only known keys:

    code      language code ("ru", "ar", "ja", "pl", "other", ...)
    kind      builtin | script-hybrid | japanese | script (default: the profile's)
    script    ISO 15924 code ("Cyrl"); required for kind script with code "other"
    language  BCP-47 tag for shaping (default: code)
    rtl       right-to-left paragraphs (default: the profile's)
    font      path of the TrueType/OpenType font new glyphs are drawn from
    face      face index inside a .ttc (default 0)
    px, baseline, xscale   glyph size, baseline row, horizontal squeeze
              (defaults: RENDER[script])
    align     "left" | "right" (right needs a wrap width; RTL dialogue)
    wrap      px to wrap translated lines at (0 = leave wrapping to the game;
              default: 0 for left-to-right, the row's guide / 370 px for RTL)
    battle_font, battle_face, battle_px, battle_baseline, battle_xscale
              the same for the battle HUD grid (default: font/face, 13 px)
    """
    if not isinstance(t, dict):
        raise TargetError("target must be an object")
    out: dict = {}
    for k, typ in _TARGET_KEYS.items():
        if k not in t or t[k] is None or t[k] == "":
            continue
        v = t[k]
        try:
            if typ is bool:
                if not isinstance(v, bool):
                    raise ValueError
            elif typ is int:
                if isinstance(v, bool) or int(v) != float(v):
                    raise ValueError
                v = int(v)
            elif typ is float:
                if isinstance(v, bool):
                    raise ValueError
                v = float(v)
            else:
                v = str(v)
        except (TypeError, ValueError):
            raise TargetError(f"{k}: expected {typ.__name__}, got {v!r}") from None
        out[k] = v
    if "kind" in out and out["kind"] not in KINDS:
        raise TargetError(f"kind must be one of {', '.join(KINDS)}, not {out['kind']!r}")
    if "align" in out and out["align"] not in ("left", "right"):
        raise TargetError("align must be 'left' or 'right'")
    for k in ("face", "battle_face", "wrap"):
        if out.get(k, 0) < 0:
            raise TargetError(f"{k} must not be negative")
    for k in ("px", "battle_px"):
        if k in out and not (6.0 <= out[k] <= 40.0):
            raise TargetError(f"{k} must be between 6 and 40")
    for k in ("xscale", "battle_xscale"):
        if k in out and not (0.3 <= out[k] <= 1.5):
            raise TargetError(f"{k} must be between 0.3 and 1.5")
    if "baseline" in out and not (8 <= out["baseline"] <= 23):
        raise TargetError("baseline must be a cell row 8..23")
    if "battle_baseline" in out and not (6 <= out["battle_baseline"] <= 17):
        raise TargetError("battle_baseline must be a cell row 6..17")
    return out


def resolve_target(project: dict) -> dict:
    """The full target a build uses: the profile of ``target.code`` (or of
    ``project["language"]``) with the project's own settings on top. An
    unknown language code with no target is "builtin" (the editor's
    original behaviour: the codec decides what can be written)."""
    given = normalise_target(project.get("target") or {})
    code = given.get("code") or project.get("language") or ""
    prof = profile(code) or {}
    script = given.get("script") or prof.get("script") or ""
    kind = given.get("kind") or prof.get("kind") or ("script" if script and script != "Latn"
                                                     else "builtin")
    if kind == "builtin" and prof.get("kind") == "script-hybrid":
        # a project that says "builtin" for a language the open disc lacks a few
        # letters of (French on the USA discs: œ Œ Ÿ) was set up before that was
        # known, or on another build: the few letters are added, the rest is
        # written exactly as a builtin build writes it
        kind = "script-hybrid"
    render = dict(RENDER.get(script, _DEFAULT_RENDER))
    t = {"code": code, "kind": kind, "script": script,
         "language": given.get("language") or (code if code and code != "other" else ""),
         "rtl": given.get("rtl", prof.get("rtl", script in RTL_SCRIPTS)),
         "font": given.get("font", ""), "face": given.get("face", 0),
         "px": given.get("px", render["px"]), "baseline": given.get("baseline", render["baseline"]),
         "xscale": given.get("xscale", render["xscale"]),
         "align": given.get("align", "left"), "wrap": given.get("wrap"),
         "name": prof.get("name") or code or "?",
         "lacking": prof.get("lacking", "") if kind == "script-hybrid" else ""}
    t["battle_font"] = given.get("battle_font", t["font"])
    t["battle_face"] = given.get("battle_face", t["face"] if "battle_font" not in given else 0)
    for k, v in BATTLE_RENDER.items():
        t[k] = given.get(k, v)
    return t


# ---------------------------------------------------------------------------
# what the retail fonts draw
# ---------------------------------------------------------------------------

_KBODY_RE = re.compile(r"<k([^<>\n]*)>")


def _jis_row(ch: str) -> int:
    try:
        b = ch.encode("euc_jp")
    except UnicodeEncodeError:
        return 0
    return b[0] if len(b) == 2 else 0


def native_predicate(kind: str, font: str = tc.FIELD, face: str = tc.FONT1) -> Callable[[str], bool]:
    """``ch -> bool``: does the build leave ``ch`` to the retail font?

    builtin / japanese: everything ``txcodec.draws_natively`` accepts.
    script / script-hybrid: the same minus JIS rows A6/A7 (Greek, Cyrillic:
    the retail font has them as fixed 20 px full-width kanji-path cells, so
    a Greek or Russian translation gets proportional glyphs drawn instead)."""
    ctx = tc.active()                 # the disc of the scope this predicate is MADE in, not of whoever calls it

    def native(ch: str) -> bool:
        # Episode III: what the open disc's fonts draw is native for every kind
        # (the Japanese font's Greek and Cyrillic stay as typed, as in langpack)
        return tc.draws_natively(ch, font, face, ctx=ctx)
    return native


def coverage(texts, target, font: str = tc.FIELD, face: str = tc.FONT1,
             ttf: Optional[str] = None, ttf_face: int = 0) -> dict:
    """Which characters of ``texts`` (a string or an iterable of strings) the
    retail font draws, and which a build must draw from a TrueType font.

    ``target`` is a profile, a resolved target or just a kind string.
    -> {"native": str, "glyph": str, "folded": str, "impossible": str,
        "missing_in_font": str|None, "counts": {ch: n}}
    native     drawn by the retail font as is
    glyph      need a new glyph (kinds other than builtin; field and battle font)
    folded     builtin battle/tag text: written as the nearest ASCII (warning)
    impossible no build can draw them here (builtin kind; the tag font;
               raw control characters)
    missing_in_font   glyph characters ``ttf`` has no glyph for (None
               without a ttf); needs fonttools
    Protected tokens (⟦XX⟧, /[..] tags) are not counted."""
    kind = target if isinstance(target, str) else (target or {}).get("kind", "builtin")
    if isinstance(texts, str):
        texts = [texts]
    native = native_predicate(kind, font, face)
    counts: Counter = Counter()
    for t in texts:
        t = _KBODY_RE.sub(r" \1 ", t or "")       # a <kWORD> keyword is drawn: its letters count
        t = unicodedata.normalize("NFC", tc._TOKRUN_RE.sub("", tc._CMD_RE.sub("", tc._TAG_RE.sub("", t))))
        counts.update(c for c in t if c != "\n")
    out = {"native": [], "glyph": [], "folded": [], "impossible": []}
    for ch in sorted(counts):
        if native(ch):
            out["native"].append(ch)
        elif ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0 or tc.glyph_code(ch) is not None:
            out["impossible"].append(ch)
        elif font == tc.NOTE:
            out["native"].append(ch)        # never drawn: it only has to encode
        elif kind == "builtin":
            out["impossible"].append(ch)
        elif unicodedata.category(ch) in ("Zl", "Zp", "Cf", "Cc", "Co", "Cs", "Cn"):
            out["impossible"].append(ch)
        else:
            out["glyph"].append(ch)
    res = {k: "".join(v) for k, v in out.items()}
    res["counts"] = dict(counts)
    res["missing_in_font"] = None
    if ttf and res["glyph"]:
        cmap = font_cmap(ttf, ttf_face)
        if cmap is not None:
            res["missing_in_font"] = "".join(
                c for c in res["glyph"] if ord(c) not in cmap
                and unicodedata.category(c) not in ("Mn", "Me"))
    return res


# ---------------------------------------------------------------------------
# fonts on this machine
# ---------------------------------------------------------------------------

def shaping_available() -> Tuple[bool, str]:
    """(True, versions) when fonttools and uharfbuzz import, else (False, how to fix)."""
    try:
        import fontTools
        import uharfbuzz
    except ImportError as e:
        return False, (f"the kit's font packages are missing ({e.name}): new scripts are drawn "
                       f"from TrueType fonts with fonttools and uharfbuzz, which the kit "
                       f"requires (requirements.txt). The launcher installs them; or run "
                       f"python3 -m pip install --user -r requirements.txt")
    return True, f"fonttools {fontTools.version}, uharfbuzz {uharfbuzz.__version__}"


def font_dirs() -> List[Path]:
    """System and user font folders of this platform (existing ones)."""
    home = Path.home()
    if sys.platform == "darwin":
        c = [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
             Path("/Library/Fonts"), home / "Library/Fonts"]
    elif sys.platform == "win32":
        win = Path(os.environ.get("WINDIR", r"C:\Windows"))
        c = [win / "Fonts"]
        if os.environ.get("LOCALAPPDATA"):
            c.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts")
    else:
        c = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
             home / ".fonts", home / ".local/share/fonts"]
    return [d for d in c if d.is_dir()]


_FONT_EXT = (".ttf", ".otf", ".ttc", ".otc")
# fonts whose cmap claims everything but whose glyphs are placeholders
_FONT_SKIP = re.compile(r"lastresort|braille|emoji", re.I)


def _quiet_fonttools() -> None:
    import logging
    logging.getLogger("fontTools").setLevel(logging.ERROR)


def _open_faces(path: str):
    from fontTools.ttLib import TTCollection, TTFont
    _quiet_fonttools()
    if path.lower().endswith((".ttc", ".otc")):
        return list(TTCollection(path, lazy=True).fonts)
    return [TTFont(path, lazy=True)]


def font_cmap(path: str, face: int = 0) -> Optional[Set[int]]:
    """Code points ``path`` (face ``face``) maps, or None without fonttools."""
    try:
        faces = _open_faces(str(path))
    except ImportError:
        return None
    except Exception as e:
        raise TargetError(f"cannot read the font {path}: {e}") from None
    if face >= len(faces):
        raise TargetError(f"{path} has {len(faces)} face(s); face {face} does not exist")
    return set((faces[face].getBestCmap() or {}).keys())


def _name(ft, nid: int) -> str:
    try:
        n = ft["name"].getDebugName(nid)
        return n or ""
    except Exception:
        return ""


_FONT_INDEX: Optional[List[dict]] = None


def _font_index() -> List[dict]:
    """Every outline font face installed here, with the scripts it covers
    (cached by ``txcache`` as fonts-v1.json, by path, size and mtime)."""
    global _FONT_INDEX
    if _FONT_INDEX is not None:
        return _FONT_INDEX
    import txcache
    cache_path = txcache.plain_path("fonts-v1.json")
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    files = []
    for d in font_dirs():
        for root, _dirs, names in os.walk(d):
            for n in sorted(names):
                if n.lower().endswith(_FONT_EXT) and not _FONT_SKIP.search(n):
                    files.append(os.path.join(root, n))
    out: List[dict] = []
    fresh = {}
    for p in sorted(set(files)):
        try:
            st = os.stat(p)
        except OSError:
            continue
        stamp = f"{st.st_size}:{int(st.st_mtime)}"
        hit = cache.get(p)
        if hit and hit.get("stamp") == stamp:
            faces = hit["faces"]
        else:
            faces = []
            try:
                for i, ft in enumerate(_open_faces(p)):
                    if not any(t in ft for t in ("glyf", "CFF ", "CFF2")):
                        continue
                    cmap = ft.getBestCmap() or {}
                    scripts = [s for s, probe in _PROBE.items()
                               if all(ord(c) in cmap for c in probe)]
                    faces.append({"face": i, "family": _name(ft, 1), "style": _name(ft, 2),
                                  "scripts": scripts})
            except ImportError:
                return []
            except Exception:
                faces = []
        fresh[p] = {"stamp": stamp, "faces": faces}
        for f in faces:
            out.append({"path": p, **f, "noto": "noto" in (f["family"] + p).lower()})
    try:
        if fresh != cache:
            import tempfile
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(cache_path.parent), prefix="xs3tx-", suffix=".tmp")   # one per writer
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(fresh, fh, ensure_ascii=False)
            os.replace(tmp, cache_path)
    except OSError:
        pass
    _FONT_INDEX = out
    return out


def system_fonts(script: Optional[str] = None, chars: Optional[str] = None) -> List[dict]:
    """Installed outline fonts: [{path, face, family, style, noto, scripts}],
    Noto first, then by family. ``script`` keeps faces covering that script's
    probe letters (``_PROBE``); ``chars`` keeps faces that map every one of
    those characters (opens the candidate fonts again). Empty without
    fonttools."""
    fonts = _font_index()
    if script:
        fonts = [f for f in fonts if script in f["scripts"]]
    if chars:
        need = {ord(c) for c in chars if unicodedata.category(c) not in ("Mn", "Me")}
        keep = []
        for f in fonts:
            try:
                cmap = font_cmap(f["path"], f["face"])
            except TargetError:
                continue
            if cmap is not None and need <= cmap:
                keep.append(f)
        fonts = keep
    # system-internal faces (".SF ...") and calligraphic Nastaliq are poor
    # first choices for 20 px cells: list them last
    return sorted(fonts, key=lambda f: (f["family"].startswith(".") or "nastaliq" in f["family"].lower(),
                                        not f["noto"], f["style"].lower() not in ("regular", "w3"),
                                        f["family"].lower(), f["style"].lower(),
                                        f["path"], f["face"]))


def suggest_fonts(target: dict, chars: Optional[str] = None) -> dict:
    """{"noto": [family names to download], "installed": system_fonts(...)[:12]}."""
    script = target.get("script") or ""
    return {"noto": list(NOTO.get(script, ["Noto Sans"])),
            "installed": system_fonts(script or None, chars)[:12]}


# ---------------------------------------------------------------------------
# the font for a few missing letters, when the project names none
# ---------------------------------------------------------------------------
# French on the USA discs lacks three letters (œ Œ Ÿ), Polish nine, and so on:
# a Latin-script language whose other letters the disc already draws
# (kind script-hybrid). A translator should not have to know that a font file is
# involved, so a build that finds no font in the project takes one itself:
#
#   1. the kit's own DejaVu Sans, when it has every needed letter: the same
#      glyphs on every machine, so two people building one project get the same
#      disc;
#   2. else the best installed face that has every one of them (plain, common
#      sans families first; the order below is fixed, the check is exact).
#
# A font the project names always wins, and a named file that is missing is an
# error, never quietly replaced. Languages of another script (Russian, Arabic,
# Hindi...) are not given a font this way: every letter comes from the font
# there, so which one is the translator's choice (Language setup).

_CLEAR_FAMILIES = ("noto sans", "helvetica neue", "helvetica", "arial", "pt sans", "segoe ui", "dejavu sans",
                   "liberation sans", "open sans", "lucida grande", "verdana", "tahoma", "geneva")
_ODD_WORDS = ("mono", "typewriter", "courier", "black", "narrow", "condensed", "comic", "chalk", "marker",
              "papyrus", "script", "brush", "stencil", "impact", "trattatello", "herculanum", "zapfino",
              "unicode ms", "symbol", "dings", "webdings", "bodoni", "didot", "rounded")
_AUTO: Dict[str, Optional[dict]] = {}
_BUNDLED_CMAP: List[Optional[Set[int]]] = []


def _need(chars: str) -> str:
    return "".join(sorted({c for c in unicodedata.normalize("NFC", chars or "")
                           if not c.isspace() and unicodedata.category(c) not in ("Mn", "Me")}))


def bundled_cmap() -> Optional[Set[int]]:
    """Code points of the kit's own font (None when the file or fonttools is missing)."""
    if not _BUNDLED_CMAP:
        try:
            _BUNDLED_CMAP.append(font_cmap(str(BUNDLED_FONT)) if BUNDLED_FONT.is_file() else None)
        except TargetError:
            _BUNDLED_CMAP.append(None)
    return _BUNDLED_CMAP[0]


def auto_font(chars: str, installed: bool = True) -> Optional[dict]:
    """The font for ``chars`` when the project names none (rule above).
    -> {"path", "face", "label", "source": "bundled" | "installed"} or None
    when no font here has every one of them. ``installed`` off: the bundled
    font or nothing (the language list uses it: no scan of every font)."""
    need = _need(chars)
    if not need:
        return None
    key = need + ("|i" if installed else "")
    if key in _AUTO:
        return _AUTO[key]
    out = None
    cm = bundled_cmap()
    if cm is not None and all(ord(c) in cm for c in need):
        out = {"path": str(BUNDLED_FONT), "face": 0, "label": BUNDLED_LABEL, "source": "bundled"}
    elif installed:
        def rank(f):
            low = (f["family"] or "").lower()
            clear = next((i for i, c in enumerate(_CLEAR_FAMILIES) if low.startswith(c)), len(_CLEAR_FAMILIES))
            return (low.startswith(".") or not low, any(w in low for w in _ODD_WORDS),
                    (f.get("style") or "").lower() not in ("regular", "w3", "book", "roman", ""),
                    clear, low, f["path"], f["face"])
        for f in sorted(_font_index(), key=rank):
            try:
                fc = font_cmap(f["path"], f["face"])
            except TargetError:
                continue
            if fc is not None and all(ord(c) in fc for c in need):
                st = f.get("style") or ""
                out = {"path": f["path"], "face": int(f["face"]), "source": "installed",
                       "label": (f["family"] or Path(f["path"]).stem) + ("" if st.lower() in ("regular", "") else " " + st)}
                break
    _AUTO[key] = out
    return out


def with_font(target: dict, chars: str) -> dict:
    """``target``, with a font for ``chars`` when it needs one and names none:
    a copy with ``font`` / ``face`` set and ``font_auto`` = the label and
    source of the font taken. Unchanged for a builtin target, a target that
    names a font, or a language of another script. Raises TargetError when a
    hybrid target's letters are in no font here."""
    if (target.get("kind") != "script-hybrid") or target.get("font") or not _need(chars):
        return target
    ok, msg = shaping_available()
    if not ok:
        raise TargetError(msg)
    f = auto_font(chars)
    if f is None:
        raise TargetError(f"{target.get('name') or target.get('code')}: no font on this machine has "
                          f"{' '.join(_need(chars)[:12])}; choose a font file (Language setup, or \"font\" in "
                          f"the project's target)")
    out = dict(target)
    out["font"], out["face"] = f["path"], f["face"]
    out["font_auto"] = {"label": f["label"], "source": f["source"], "letters": _need(chars)}
    if not target.get("battle_font"):
        out["battle_font"], out["battle_face"] = f["path"], f["face"]
    return out


def readiness(profile_: Optional[dict]) -> dict:
    """What a language needs on the disc of this scope, in the words of the
    language list: {"ready": "ready" | "auto" | "font", "font_auto": label or None}.
    ``auto`` = a few letters the disc lacks, added from the kit's font by the
    build with nothing to choose; ``font`` = the translator chooses a font."""
    p = profile_ or {}
    kind = p.get("kind", "builtin")
    if kind == "builtin":
        return {"ready": "ready", "font_auto": None}
    if kind == "script-hybrid" and p.get("lacking"):
        f = auto_font(p["lacking"], installed=False)
        if f is not None and shaping_available()[0]:
            return {"ready": "auto", "font_auto": f["label"]}
    return {"ready": "font", "font_auto": None}


# ---------------------------------------------------------------------------
# kinds against the open disc
# ---------------------------------------------------------------------------

def _adapt(t: Optional[dict]) -> Optional[dict]:
    """``t`` with ``kind`` / ``lacking`` decided for the disc that is open. The
    table itself holds the answer for the USA discs (no disc open = USA)."""
    ctx = tc.active()
    if t is None or ctx is None or ctx.display == "us" or t.get("code") == "other":
        return t
    letters = "".join(c for c in dict.fromkeys((t.get("alphabet") or "") + (t.get("sample") or ""))
                      if not c.isspace() and ord(c) >= 0x80)
    lacking = "".join(c for c in letters if not tc.draws_natively(c))
    out = dict(t)
    if not lacking:
        out["kind"] = "builtin"
    elif t.get("script") == "Latn":
        out["kind"] = "script-hybrid"
    else:
        out["kind"] = "script"
    out["lacking"] = lacking if t.get("script") == "Latn" else ""
    return out


def _ready(t: Optional[dict]) -> Optional[dict]:
    if t is None or t.get("code") == "other":
        return t
    out = dict(t)
    out.update(readiness(out))
    return out


def languages(query: str = "") -> List[dict]:           # noqa: F811 - the disc-aware list
    return [_ready(_adapt(t)) for t in _languages_usa(query)]


def profile(code: str) -> Optional[dict]:               # noqa: F811
    return _ready(_adapt(_profile_usa(code)))


# ---------------------------------------------------------------------------
# building a project whose language needs new letters (langpack)
# ---------------------------------------------------------------------------

def needs_glyphs(target: dict, rows: Dict[str, dict], edits: Dict[str, str]) -> bool:
    """Does any edited, drawn row hold a letter the disc cannot draw?"""
    if target.get("kind", "builtin") == "builtin":
        return False
    for rid, text in edits.items():
        row = rows.get(rid)
        if row is None or row.get("font") != tc.FIELD:
            continue
        if coverage(text, target)["glyph"]:
            return True
    return False


def _check_font(path: str, face: int, chars: str, target: dict) -> None:
    if not path:
        raise TargetError(f"{target.get('name') or target.get('code')}: letters such as "
                          f"{' '.join(chars[:8])} are drawn from a font file and none is chosen "
                          f"(Language setup, or \"font\" in the project's target)")
    if not Path(path).is_file():
        raise TargetError(f"the font file {path} does not exist")
    ok, msg = shaping_available()
    if not ok:
        raise TargetError(msg)
    cmap = font_cmap(path, face)
    if cmap is not None:
        miss = "".join(c for c in chars if ord(c) not in cmap and unicodedata.category(c) not in ("Mn", "Me")
                       and not c.isspace())
        if miss:
            raise TargetError(f"the font {Path(path).name} has no letter for {' '.join(miss[:12])}"
                              f"{' ...' if len(miss) > 12 else ''}; choose a font that covers them")


def tree_body(text: str) -> str:
    """Display text -> the one-line body a text-export block holds."""
    body = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return "⟦23⟧" + body[1:] if body.startswith("#") else body


_K_OPEN, _K_CLOSE = "⟦3C⟧", "⟦3E⟧"


def open_keyword_tags(body: str, ctx) -> str:
    """``<kWORD>`` -> ``⟦3C⟧kWORD⟦3E⟧`` for every keyword tag whose word holds a
    letter the disc cannot draw.

    ``langpack`` passes a ``<...>`` tag through as one object, letters and all,
    so a keyword with a new letter in it (French ``<kcœur>``) would reach the
    disc unencoded and be refused. Written this way the two angle brackets are
    raw bytes and the word between them is ordinary text: it gets its glyph
    cells and its codes, and the bytes on the disc are again ``<k`` + the
    encoded word + ``>``. Only for text that is neither reordered nor wrapped
    by the encoder (``build_script`` checks)."""
    def one(m):
        word = m.group(1)
        if any(ord(c) >= 0x80 and not tc.draws_natively(c, ctx=ctx) for c in word):
            return _K_OPEN + "k" + word + _K_CLOSE
        return m.group(0)
    return _KBODY_RE.sub(one, body)


def write_edits_into_tree(tree: Path, state, edits: Dict[str, str], log=print, open_tags: bool = False) -> int:
    """Put a project's translations into a fresh text-export tree of the same
    discs (``state`` = ``txfam_core.load``'s). Returns the number of tree files
    changed. A string the disc holds in a Japanese codec but draws (left
    untranslated on the USA discs) is moved to the build's codec in the
    manifest, since its translation is written in that codec. ``open_tags``:
    keyword tags with new letters are written so the encoder encodes their
    word (``open_keyword_tags``)."""
    import textpack
    import txfam_core as core
    manifest = textpack.load_manifest(tree)
    display = state.region.codec
    per: Dict[str, Dict[str, str]] = {}
    for rid, text in edits.items():
        if rid not in state.slots:
            raise TargetError(f"{rid}: not a string of this disc set")
        per.setdefault(textpack._norm(state.slots[rid].obj.path), {})[rid] = text
    by_norm = {textpack._norm(p): (p, o) for p, o in manifest["objects"].items()}
    n = 0
    for opath, group in per.items():
        if opath not in by_norm:
            raise TargetError(f"{opath}: not in the exported tree")
        mpath, o = by_norm[opath]
        obj = state.objs[opath]
        f = tree / o["tree"]
        if textpack.KINDS[obj.kind].whole_file:
            new = core._file_text(state, obj, group, check=False)
        else:
            lines = f.read_bytes().decode("utf-8").split("\n")
            index: Dict[str, int] = {}
            order: List[str] = []
            for i, ln in enumerate(lines):
                if ln.startswith("### "):
                    key = ln[4:].split(" ", 1)[0]
                    index[key] = i
                    order.append(key)
            for rid, text in group.items():
                slot, row = state.slots[rid], state.by_id[rid]
                if slot.key not in index:
                    raise TargetError(f"{rid}: no block {slot.key} in {o['tree']}")
                if obj.kind == "sb":
                    text = tc.fix_line_count(row["src"], text)
                i = index[slot.key]
                lines[i + 1] = open_keyword_tags(tree_body(text), state.ctx) if open_tags else tree_body(text)
                codecs = o.get("codecs") or {}
                pos = order.index(slot.key)
                for cname, idxs in list(codecs.items()):
                    if cname != display and row["ctl"] == display and pos in idxs:
                        idxs.remove(pos)
                        lines[i] = "### " + slot.key          # the header's codec word no longer holds
            new = "\n".join(lines)
        old = f.read_bytes()
        data = new.encode("utf-8")
        if data != old:
            f.write_bytes(data)
            n += 1
    (tree / textpack.MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return n


def sync_keywords(enc: Path, state, edits: Dict[str, str]) -> int:
    """In an ENCODED tree, give every keyword of ``edits`` the encoded body of
    the ``<k...>`` tag it follows, copied from its line's encoded text.

    The game compares bytes: ``extalk.KeyWait``'s string must be the bytes
    inside the tag. ``langpack`` encodes a line as a whole (new letters become
    glyph codes; a right-to-left line is put in visual order) and leaves a
    string it takes for an identifier alone, so a keyword encoded on its own
    need not come out as its tag did. Copying the tag's encoded text makes the
    two equal by construction; the build's read-back then compares the bytes
    on the disc (``txfam_core.check_links``). Returns the number written."""
    import textpack
    import txfam_core as core
    manifest = textpack.load_manifest(enc)
    by_norm = {textpack._norm(p): o for p, o in manifest["objects"].items()}
    todo: Dict[str, List[str]] = {}
    for krid in state.links:
        if krid in edits:
            todo.setdefault(textpack._norm(state.slots[krid].obj.path), []).append(krid)
    n = 0
    for opath, krids in todo.items():
        o = by_norm.get(opath)
        if o is None:
            raise TargetError(f"{opath}: not in the encoded tree")
        f = Path(enc) / o["tree"]
        lines = f.read_bytes().decode("utf-8").split("\n")
        index = {ln[4:].split(" ", 1)[0]: i for i, ln in enumerate(lines) if ln.startswith("### ")}
        for krid in krids:
            want = None
            for lrid, positions in state.links[krid]:
                tags = core._KTAG.findall(lines[index[state.slots[lrid].key] + 1]
                                          .replace(_K_OPEN, "<").replace(_K_CLOSE, ">"))
                for p in positions:
                    if p >= len(tags) or (want is not None and tags[p] != want):
                        raise TargetError(f"{krid}: the keyword's <k...> tags do not agree after encoding "
                                          f"({lrid}); write the keyword the same way in each of its lines")
                    want = tags[p]
            if want is not None and lines[index[state.slots[krid].key] + 1] != want:
                lines[index[state.slots[krid].key] + 1] = want
                n += 1
        f.write_bytes("\n".join(lines).encode("utf-8"))
    return n


def scan_args(target: dict) -> dict:
    """``langpack.scan`` keyword arguments of a resolved target."""
    return {"ttf": target.get("font") or None, "px": float(target.get("px") or 20.0),
            "baseline": int(target.get("baseline") or 17), "face": int(target.get("face") or 0),
            "script": target.get("script") or None,
            "language": (target.get("language") or None), "rtl": bool(target.get("rtl"))}


def build_script(isos: List[str], state, target: dict, edits: Dict[str, str], out, work: Path,
                 overwrite: bool = False, dry_run: bool = False, log: Callable[[str], None] = print) -> dict:
    """Build a project whose language needs new letters: export, write the
    translations in, ``lang scan`` / ``encode`` / ``import`` (module docstring).
    Returns langpack.import_pack's result plus the tree and pack folders."""
    import langpack
    import textpack
    glyph = coverage([t for rid, t in edits.items() if state.by_id.get(rid, {}).get("font") == tc.FIELD],
                     target)["glyph"]
    target = with_font(target, glyph + (target.get("lacking") or ""))
    if target.get("font_auto"):
        fa = target["font_auto"]
        log(f"no font is chosen in the project: the {len(_need(glyph))} letter(s) the disc lacks "
            f"({' '.join(_need(glyph)[:16])}) are drawn from {fa['label']}"
            + ("" if fa["source"] == "bundled" else f" ({target['font']}; installed on this machine, so "
               f"another machine may pick another: name a font in the project to pin it)"))
    _check_font(target.get("font", ""), int(target.get("face") or 0), glyph, target)
    tree, pack, enc = work / "tree", work / "pack", work / "tree-enc"
    log(f"exporting the text of {len(isos)} disc(s)")
    textpack.export_discs(list(isos), tree, log=lambda *a: None)
    # a keyword tag with a new letter in its word: the encoder must encode the word
    # (open_keyword_tags), which it can only do for text it neither reorders nor wraps
    plain = not target.get("rtl") and not int(target.get("wrap") or 0)
    if not plain:
        for rid, text in edits.items():
            if rid in state.linked and any(
                    ord(c) >= 0x80 and not tc.draws_natively(c, ctx=state.ctx)
                    for w in _KBODY_RE.findall(text) for c in w):
                raise TargetError(
                    f"{rid}: the keyword in a <k...> tag has letters the disc cannot draw, and this language "
                    f"is {'right-to-left' if target.get('rtl') else 'wrapped by the build'}: the encoder places "
                    f"a tag as one object and cannot give its word new letters. Write the keyword in letters "
                    f"the disc has (the original word, or a transliteration)")
    n = write_edits_into_tree(tree, state, edits, log, open_tags=plain)
    log(f"{len(edits)} translation(s) written into {n} file(s) of the tree")
    try:
        log(f"drawing new letters from {Path(target['font']).name} ({target.get('script') or 'script'}, "
            f"{target.get('px')} px)")
        langpack.scan(isos[0], tree, pack, log=log, **scan_args(target))
        width = int(target.get("wrap") or 0)
        langpack.encode(tree, pack, enc, width=width, align=target.get("align") or "left",
                        rtl=bool(target.get("rtl")), log=log)
        n_kw = sync_keywords(enc, state, edits)
        if n_kw:
            log(f"{n_kw} keyword(s) written with the encoded <k...> word of their line")
        # the encoded objects, before anything is written: buffers, byte limits, keyword links
        import txfam_core as core
        planned, _rows, _warn = textpack.plan_import(list(isos), enc, True, False, lambda *a: None)
        bad = core.planned_errors(state, planned, edits)
        if bad:
            raise TargetError(f"{len(bad)} problem(s) in the encoded text; nothing written:\n  " + "\n  ".join(bad[:20]))
        res = langpack.import_pack(list(isos), enc, pack, out, grow=True, dry_run=dry_run, log=log,
                                   overwrite=overwrite)
    except (langpack.LangError, textpack.TextError) as exc:
        raise TargetError(str(exc)) from None
    res["tree"], res["pack"], res["enc"] = str(tree), str(pack), str(enc)
    res["target"] = target
    return res


# ---------------------------------------------------------------------------
# preview: one string drawn as a build would draw it
# ---------------------------------------------------------------------------
_PREVIEW_OBJ = "mnu\\xx\\discchg.txd"      # a small block file of every build: the scratch tree's one object
_PACKS: Dict[tuple, tuple] = {}


def _preview_pack(retail: str, target: dict, text: str):
    """A langpack Pack holding the glyphs of ``text`` (cached per disc, font
    settings and letter set). The cells are placed for this text alone, so the
    picture is right but the codes are not the ones a full build assigns."""
    import shutil
    import tempfile
    import langpack
    import region as regionmod
    import textpack
    args = scan_args(target)
    letters = "".join(sorted(set(coverage(text, target)["glyph"])))
    st = os.stat(retail)
    try:
        fstamp = os.stat(args["ttf"]).st_mtime_ns if args["ttf"] else 0
    except OSError:
        fstamp = 0
    # letters that take a different shape by their neighbours (Arabic joining, Indic
    # conjuncts, ligatures) need the glyphs of THIS text, not of any text with the same
    # letter set: only the scripts written one letter one glyph share a pack per set
    simple = (target.get("script") or "") in ("Latn", "Cyrl", "Grek", "Armn", "Geor", "Hang", "Hani", "Jpan", "Kana")
    key = (str(retail), st.st_mtime_ns, json.dumps(args, sort_keys=True), fstamp, letters if simple else text)
    if key in _PACKS:
        return _PACKS[key]
    _check_font(args["ttf"] or "", args["face"], letters, target)
    tmp = Path(tempfile.mkdtemp(prefix="xs3tx-preview-"))
    try:
        with textpack.DiscSource(retail) as d:
            p = regionmod.resolve(d.disc, _PREVIEW_OBJ, d.region)
            m = textpack.export(d.read, [p], tmp / "tree", d.build(), d.alloc, log=lambda *a: None,
                                region=d.region)
        o = next(iter(m["objects"].values()))
        f = tmp / "tree" / o["tree"]
        lines = f.read_text(encoding="utf-8").split("\n")
        lines[2] = tree_body(text)
        f.write_text("\n".join(lines), encoding="utf-8")
        try:
            pack = langpack.scan(retail, tmp / "tree", tmp / "pack", log=lambda *a: None, **args)
        except (langpack.LangError, textpack.TextError) as exc:
            raise TargetError(str(exc)) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if len(_PACKS) > 24:
        _PACKS.clear()
    _PACKS[key] = pack
    return pack


def preview(retail: str, target: dict, text: str, font: str = tc.FIELD, face: str = tc.FONT0,
            ctl: str = "us", scale: int = 2) -> Tuple[List[bytes], str]:
    """PNG(s) of ``text`` as the game would draw it after a build (one PNG per
    line; a speaker name is its own first line), and the encoded text."""
    import langpack
    k = 1 if face == tc.FONT1 else 0
    _name, file = tc.split_ctl(ctl)
    body = tree_body(text) if not file else unicodedata.normalize("NFC", text).replace("\n", "\\n")
    if target.get("kind", "builtin") != "builtin" and coverage(text, target)["glyph"]:
        target = with_font(target, coverage(text, target)["glyph"] + (target.get("lacking") or ""))
        if not target.get("rtl") and not int(target.get("wrap") or 0):
            body = open_keyword_tags(body, tc.context(retail))      # as build_script writes it
        pack = _preview_pack(retail, target, body)
        enc = langpack.Encoder(pack, pack.shaper(), bool(target.get("rtl")), width=int(target.get("wrap") or 0),
                               align=target.get("align") or "left", state=pack.cfg.get("state", "prop1han1"),
                               donor=pack.donor())
        try:
            enc_text = enc.string(body, prefix=body.startswith("["))
        except langpack.LangError as exc:
            raise TargetError(str(exc)) from None
        data = pack.codec.from_text(enc_text)
        addr, fnt = pack.addr, pack.fonts[k]
    else:
        ctx = tc.context(retail)
        enc_text = body
        data = tc.from_display(text, font, ctl, face, keep=text, ctx=ctx)[0]
        addr, fnt = ctx.addr, ctx.fonts[k]
    f = tc.Face.__new__(tc.Face)
    f.ctx, f.k, f.font, f.metrics = type("C", (), {"addr": addr})(), k, fnt, fnt.metrics
    return [tc.render_line(f, line, scale) for line in tc.preview_lines(data, "us")], enc_text


# ---------------------------------------------------------------------------
# selftest / CLI
# ---------------------------------------------------------------------------

def _find_font(*names: str) -> Optional[str]:
    for n in names:
        for d in font_dirs():
            for p in (d / n, d / "Supplemental" / n):
                if p.is_file():
                    return str(p)
    return None


def selftest(iso: Optional[str], out: Optional[str] = None) -> int:
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    tc.use_disc(None)
    check(len(TARGETS) > 300 and profile("es")["kind"] == "builtin" and profile("ru")["kind"] == "script"
          and profile("pl")["kind"] == "script-hybrid" and profile("ar")["rtl"]
          and profile("fr")["kind"] == "script-hybrid" and set(profile("fr")["lacking"]) == set("œŒŸ"),
          f"{len(TARGETS)} languages; USA rules: es builtin, fr lacks only œ Œ Ÿ (not in Latin-1), "
          f"pl script-hybrid, ru script, ar right-to-left")
    cov = coverage("Zażółć <f>$col707070;⟦0D⟧ é", profile("pl"))
    check(set(cov["glyph"]) == set("żłć") and "é" in cov["native"] and "ó" in cov["native"]
          and "<" not in cov["native"] + cov["glyph"],
          f"coverage: Polish letters need glyphs ({cov['glyph']}), tags are not counted")
    check(coverage("Ж", "builtin")["impossible"] == "Ж", "a builtin target cannot draw a foreign letter")
    t = resolve_target({"language": "ru", "target": {"code": "ru", "px": 19}})
    check(t["kind"] == "script" and t["script"] == "Cyrl" and t["px"] == 19.0, "resolve_target")
    check(tree_body("#a\nb") == "⟦23⟧a\\nb", "tree body form")
    ok_shape, msg = shaping_available()
    check(ok_shape, f"shaping: {msg}")
    f = auto_font("œŒŸ", installed=False)
    check(f is not None and f["source"] == "bundled" and readiness(profile("fr")) == {"ready": "auto", "font_auto": BUNDLED_LABEL}
          and readiness(profile("ru"))["ready"] == "font" and readiness(profile("es"))["ready"] == "ready",
          "a language that lacks a few letters is ready: the kit's own font has them (fr: auto; ru: a font you choose; es: ready)")
    t = resolve_target({"language": "fr", "target": {"code": "fr", "kind": "builtin"}})
    t2 = with_font(t, "œ" + t["lacking"])
    check(t["kind"] == "script-hybrid" and t["lacking"] and t2["font"] == str(BUNDLED_FONT) and t2["font_auto"]["source"] == "bundled"
          and "font_auto" not in with_font(dict(t, font="/my/own.ttf"), "œ")
          and with_font(resolve_target({"language": "ru"}), "я").get("font", "") == "",
          "a project that says builtin for French is treated as French is; a font the project names wins; "
          "a language of another script is not given one")
    check(set(coverage("a <kcœur> b <f>", profile("fr"))["glyph"]) == {"œ"}
          and open_keyword_tags("x <kcœur> <kok> <f>", None) == "x ⟦3C⟧kcœur⟦3E⟧ <kok> <f>",
          "the letters inside a <k...> keyword count; a keyword with a new letter is opened for the encoder")
    if iso:
        ctx = tc.use_disc(iso)
        if ctx.display == "jp":
            check(profile("ja")["kind"] == "builtin" and profile("ru")["kind"] == "builtin"
                  and profile("fr")["kind"] == "script-hybrid",
                  "Japanese disc: ja and ru builtin (JIS rows), fr needs é drawn")
        ttf = _find_font("Arial.ttf", "DejaVuSans.ttf", "NotoSans-Regular.ttf")
        if ttf and ok_shape:
            tgt = resolve_target({"language": "ru", "target": {"code": "ru", "font": ttf}}) if ctx.display == "us" \
                else resolve_target({"language": "fr", "target": {"code": "fr", "font": ttf}})
            sample = "[Шион]Привет, мир!\nВторая строка<f>" if ctx.display == "us" else "[シオン]Élan, café<f>"
            import time
            t0 = time.time()
            pngs, enc = preview(iso, tgt, sample)
            check(len(pngs) >= 2 and all(p[:4] == b"\x89PNG" for p in pngs) and "⟦" in enc,
                  f"preview with {Path(ttf).name}: {len(pngs)} line(s) in {time.time() - t0:.1f} s")
            if out:
                Path(out).mkdir(parents=True, exist_ok=True)
                for i, p in enumerate(pngs):
                    (Path(out) / f"txtarget-preview-{i}.png").write_bytes(p)
            if tgt["kind"] == "script-hybrid":      # a few missing letters: the kit's own font, nothing to choose
                pngs2, enc2 = preview(iso, dict(tgt, font=""), sample)
                check(len(pngs2) == len(pngs) and "⟦" in enc2,
                      "a language that lacks only a few letters previews with no font chosen")
            else:
                try:
                    preview(iso, dict(tgt, font=""), sample)
                    check(False, "a language of another script without a font is refused")
                except TargetError:
                    check(True, "a language of another script without a font is refused")
            kwl = "[A]x <kcœur> y<f>" if ctx.display == "us" else "[A]x <kcafé> y<f>"
            pngs3, enc3 = preview(iso, resolve_target({"language": "fr", "target": {"code": "fr"}}), kwl)
            check(len(pngs3) == 2 and "⟦3C⟧k" in enc3 and "⟦3E⟧" in enc3,
                  "a keyword with a new letter previews: its word is encoded, as in a build")
        else:
            print("skip  preview (no Arial / DejaVu / Noto Sans font found)")
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    f = sub.add_parser("fonts")
    f.add_argument("--script")
    c = sub.add_parser("coverage")
    c.add_argument("--code", default="fr")
    c.add_argument("--text", required=True)
    c.add_argument("--iso")
    s = sub.add_parser("selftest")
    s.add_argument("--iso")
    s.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for t in TARGETS:
            print(f"{t['code']:10} {t['kind']:14} {t.get('script', ''):5} {t['name']}")
        return 0
    if a.cmd == "fonts":
        for f_ in system_fonts(a.script):
            print(f_["path"], f_.get("family"), f_.get("style"))
        return 0
    if a.cmd == "coverage":
        if a.iso:
            tc.use_disc(a.iso)
        cov = coverage(a.text, profile(a.code) or "builtin")
        print(json.dumps({k: v for k, v in cov.items() if k != "counts"}, ensure_ascii=False, indent=1))
        return 0
    return selftest(a.iso, a.out)


if __name__ == "__main__":
    sys.exit(main())
