"""sbnatives.py — the natives the Xenosaga III script VM registers, as read from the
executables (data; ``sbvm.read_vm_tables`` is the reader that produced it).

The engine registers a class with ``register(name, table)`` (USA SLUS FUN_001d1868,
prototype 0x1d17e0, Japan 0x1d0970); a table is ``{char *name, handler, int min_args}``
records of 12 bytes, closed by a zero name. 22 classes and 327 functions, the same
names and minimum argument counts in all five builds read (USA Disc 1 and 2, the
May 2006 prototype, Japan Disc 1 and 2; 2026-11-21). ``bat`` and ``robo`` live in
OV02.OVL, the rest in the boot executable.

Each entry is ``(function, min_args, handler)``; the handler and table addresses are
those of USA Disc 1 (SLUS_213.89, OV02.OVL) and differ in the other builds. A script
import resolves to ``class index << 16 | function index`` at load, so the ORDER here
is the engine's. The ``mm`` table has no closing zero in the executable: the
registration loop reads one more record whose name pointer is 0x10204 (not a string)
before it meets a zero; that record is left out here.

Names are the game's own strings. Nothing here is invented.
"""

# class -> (table address on USA Disc 1, ((function, min_args, handler), ...))
CLASSES = {
    "bcam": (0x3e32a8, (
        ("AB", 2, 0x25db88), ("Start", 1, 0x25dbd8), ("Pos", 4, 0x25dce0), ("Look", 4, 0x25de40),
        ("Cvr", 2, 0x25dfa0), ("RotZ", 1, 0x25e028), ("Wait", 1, 0x25e0c8), ("Over", 6, 0x25e130),
        ("Overcam", 0, 0x25e320), ("Def", 2, 0x25e340), ("SoroMode", 0, 0x25e3d8),
    )),
    "effcam": (0x3e3460, (
        ("Look", 5, 0x2616c8), ("LookAct", 3, 0x261808), ("AngXY", 4, 0x261890), ("AngZ", 3, 0x2619c0),
        ("Pos", 5, 0x261a78), ("PosCircle", 5, 0x261bb8), ("Pers", 3, 0x261cf8),
    )),
    "cam": (0x3e35c0, (
        ("DefMov", 2, 0x2631d0), ("Mov", 4, 0x263220), ("Start", 2, 0x2632a8), ("Exit", 0, 0x2632f8),
        ("Line", 1, 0x263318), ("CamID", 1, 0x263340), ("Pos", 3, 0x263368), ("AngYZ", 2, 0x263478),
        ("AngXYZ", 3, 0x263538), ("Len", 1, 0x263648), ("LockX", 1, 0x2636a8), ("LockY", 1, 0x263708),
        ("LockZ", 1, 0x263768), ("Act", 3, 0x2637c8), ("Limit", 4, 0x2638d8), ("Pers", 1, 0x263a30),
        ("Front", 1, 0x263a90), ("Mode", 1, 0x263af0), ("FocusA", 5, 0x263b18), ("FocusB", 5, 0x263c30),
        ("Chgid", 1, 0x263d48), ("RotZ", 1, 0x263d70), ("Cfcam", 0, 0x263dd8), ("MovSignal", 0, 0x263eb0),
        ("MovBlur", 2, 0x263ed0), ("Focus", 0, 0x263ed8),
    )),
    "inv": (0x3e3f00, (
        ("Rat", 2, 0x265cb0),
    )),
    "extalk": (0x3e4120, (
        ("Msg", 0, 0x26bac8), ("Exit", 1, 0x26bbd8), ("MsgWait", 1, 0x26bc08), ("KeyWait", 1, 0x26bc50),
        ("NpclenGet", 1, 0x26bcd8), ("HearReserve", 1, 0x26bda0), ("ScaleReserve", 1, 0x26be00),
    )),
    "talk": (0x3e4180, (
        ("Msg", 0, 0x26be60), ("Think", 0, 0x26bf60), ("Sys", 0, 0x26c018), ("Sel", 1, 0x26c0d0),
        ("SelResult", 0, 0x26c110), ("PosReserve", 2, 0x26c148), ("EvtMsg", 0, 0x26c1a8),
        ("EvtScr", 1, 0x26c300), ("EvtEnd", 0, 0x26c340), ("DebSlot", 0, 0x26c378), ("Slot", 1, 0x26c588),
    )),
    "cfmap": (0x3e6450, (
        ("setGravity", 0, 0x1c7f68), ("setFloorLightID", 0, 0x1c8068), ("setFloorLightRatio", 0, 0x1c80f8),
        ("setFloorLightRatio2", 2, 0x1c8100), ("setLight", 1, 0x1c8268), ("setPointLight", 8, 0x1c85c8),
        ("unsetPointLight", 1, 0x1c8750), ("setFootEffect", 2, 0x1c87b0), ("setAnimFlg", 2, 0x1c8850),
        ("setAnimFrame", 2, 0x1c8998), ("setAnimSpeed", 2, 0x1c8a48), ("visibleMapParts", 2, 0x1c8af8),
        ("transparentMapParts", 2, 0x1c8bc0), ("setShootParams", 0, 0x1c8cd0),
    )),
    "deb": (0x3e6508, (
        ("put", 1, 0x1c8db8),
    )),
    "math": (0x3e6520, (
        ("atan", 2, 0x1c8dc0), ("cos", 1, 0x1c8e68), ("sin", 1, 0x1c8f00), ("random", 2, 0x1c8f98),
    )),
    "objx": (0x3e6560, (
        ("setSize", 1, 0x1c9020), ("setOffsetPivot", 1, 0x1c91f0), ("setAttr", 2, 0x1c9370),
        ("setAttr2", 2, 0x1c94f0), ("setUnduID", 1, 0x1c95d0), ("setFootID", 2, 0x1c96c8),
        ("setParent", 2, 0x1c9778), ("setCollision", 2, 0x1c9850), ("getParam", 2, 0x1c98d8),
        ("setParam", 3, 0x1c99f8), ("setRGB", 4, 0x1c9d28), ("delete", 1, 0x1c9e50), ("move", 2, 0x1c9f68),
        ("moveOffset", 2, 0x1ca0d8), ("rotate", 2, 0x1ca260), ("scale", 2, 0x1ca3e8),
        ("transparent", 3, 0x1ca560), ("progress", 2, 0x1ca618), ("pause", 2, 0x1ca758),
        ("isModelPC", 1, 0x1ca7f0), ("setTargetOffset", 1, 0x1ca880), ("sendSignal", 2, 0x1ca998),
        ("trapEffect", 1, 0x1caa48), ("sikomi", 2, 0x1caac0),
    )),
    "runtime": (0x3e6690, (
        ("setNumber", 2, 0x1cac00), ("setPos", 1, 0x1cb238), ("setLocator", 8, 0x1cb410),
        ("setPcSpeed", 1, 0x1cb638), ("setFog", 8, 0x1cb6c8), ("setColorFilter", 1, 0x1cb8e0),
        ("setMapAlphaInvert", 1, 0x1cba20), ("setMapColor", 3, 0x1cbaa8), ("setFadeColor", 3, 0x1cbb90),
        ("setBattleMap", 1, 0x1cbc20), ("setDoorAttr", 3, 0x1cbc98), ("setDoorParam", 2, 0x1cbd90),
        ("openDoor", 1, 0x1cc2b8), ("closeDoor", 1, 0x1cc390), ("loadEnemy", 1, 0x1cc418),
        ("encount", 1, 0x1cc420), ("encountBoss", 1, 0x1cc4d0), ("message", 2, 0x1cc600),
        ("jumpPos", 3, 0x1cc678), ("jumpLocator", 1, 0x1cc7d8), ("mapPreload", 1, 0x1cc880),
        ("mapJump", 1, 0x1cc928), ("getSceneFlag", 0, 0x1cc9e8), ("setSceneFlag", 1, 0x1cca38),
        ("getFlag", 1, 0x1cca98), ("setFlag", 2, 0x1ccb10), ("getSysParam", 1, 0x1ccba8),
        ("setSysParam", 2, 0x1ccc70), ("event", 1, 0x1cce00), ("openingNarr", 0, 0x1cce98),
        ("mpeg2", 1, 0x1ccea0), ("padRead", 1, 0x1ccf28), ("analogRead", 1, 0x1ccff0),
        ("setNextMap", 1, 0x1cd0d0), ("jumpToNext", 0, 0x1cd190), ("getItem", 2, 0x1cd1c8),
        ("setItem", 3, 0x1cd248), ("kisekae", 2, 0x1cd398), ("chgTarget", 1, 0x1cd410),
        ("setTrap", 3, 0x1cd490), ("shootTrap", 0, 0x1cd550), ("clearTrap", 0, 0x1cd570),
        ("minigame", 0, 0x1cd590), ("setIntermis", 1, 0x1cd5b0), ("vibration", 0, 0x1cd610),
        ("abort", 0, 0x1cd710), ("exist", 0, 0x1cd730), ("shadowRange", 2, 0x1cd758),
        ("setKonishi", 0, 0x1cd808), ("dynamaki", 0, 0x1cda70), ("warningOff", 0, 0x1cdaf8),
        ("waitRead", 0, 0x1cdb60),
    )),
    "sound": (0x3e6910, (
        ("setBGM", 1, 0x1cdb90), ("changeBGM", 1, 0x1cdbb8), ("se", 1, 0x1cdc98), ("seStop", 1, 0x1cddb0),
        ("seFade", 3, 0x1cddd8), ("sePan", 3, 0x1cdeb0), ("sePos", 5, 0x1cdf68), ("seLine", 8, 0x1ce0a8),
        ("seID", 2, 0x1ce2a8), ("adxLoad", 1, 0x1ce390), ("adxPlay", 0, 0x1ce438), ("adxFade", 2, 0x1ce4e0),
        ("panMode", 1, 0x1ce548), ("panPos", 1, 0x1ce570), ("fx", 1, 0x1ce628), ("roboFoot", 1, 0x1ce650),
    )),
    "mm": (0x3e70b8, (
        ("ptInit", 0, 0x237168), ("ptIn", 1, 0x237188), ("ptInTo", 2, 0x237248), ("ptOut", 0, 0x237360),
        ("ptSetAtk", 3, 0x237428), ("ptSetLeader", 1, 0x2375f0), ("ptGetLeader", 0, 0x2376c8),
        ("ptChangeMode", 0, 0x237550), ("ptGetNum", 0, 0x237718), ("ptGetMember", 1, 0x237768),
        ("ptGetMode", 0, 0x2375e0), ("ptIn_Load", 1, 0x2371f8), ("ptInTo_Load", 2, 0x237310),
        ("ptOut_Load", 0, 0x2373e8), ("ptSetAtk_Load", 3, 0x237510), ("ptSetLeader_Load", 1, 0x237688),
        ("ptChangeMode_Load", 0, 0x2375b0), ("ptSaveUMNParty", 0, 0x237808), ("ptSetGuest", 2, 0x237870),
        ("EnSeg", 0, 0x2378c0), ("OpenMenu", 0, 0x237930), ("OpenShop", 1, 0x2379b8),
    )),
    "enepc": (0x3ec1f0, (
        ("setAlgoType", 0, 0x283c98), ("setParams", 0, 0x283dd0), ("talkAlgoType", 0, 0x283f18),
        ("talkStart", 0, 0x283fd0), ("talkEnd", 0, 0x284080), ("pause", 0, 0x284130), ("action", 0, 0x2841f8),
        ("motion", 0, 0x284338), ("ExMotion", 0, 0x284820), ("defaultMotion", 0, 0x284930),
        ("lookat", 0, 0x284508), ("move", 0, 0x284630),
    )),
    "seg": (0x403a38, (
        ("addrOn", 2, 0x2d3900), ("getAddrOn", 1, 0x2d3a70), ("getComplete", 0, 0x2d3a90),
    )),
    "database": (0x403a68, (
        ("setFlag", 2, 0x2d3aa8), ("getComplete", 0, 0x2d3b00),
    )),
    "modelviewer": (0x403a90, (
        ("setFlag", 2, 0x2d3b28),
    )),
    "fade": (0x407d00, (
        ("Wipe", 2, 0x1d4520), ("Cross", 1, 0x1d4580), ("In", 4, 0x1d45c0), ("Out", 4, 0x1d4650),
        ("Clear", 0, 0x1d46e0),
    )),
    "filter": (0x407d48, (
        ("Monochrome", 5, 0x1d4708), ("Negaposi", 3, 0x1d47a0), ("Correct", 4, 0x1d4890),
        ("Gradation", 6, 0x1d4928), ("GradFrame", 9, 0x1d49e8), ("Fog", 4, 0x1d4b58), ("Clear", 0, 0x1d4bd8),
    )),
    "id": (0x4cab20, (
        ("elvActive", 0, 0x2aabc8), ("elvNoOut", 0, 0x2aac60), ("elvMove", 0, 0x2aacf8),
        ("elvSetBox", 0, 0x2aae38), ("slopeSet", 0, 0x2aaee0), ("slopeSpeed", 0, 0x2aaf90),
        ("slopeoff", 0, 0x2ab040), ("keepoff", 0, 0x2ab0d0), ("camxid", 0, 0x2ab168), ("seid", 0, 0x2ab200),
    )),
    "bat": (0xab7b00, (
        ("thinkG", 1, 0xa8c5e8), ("thinkDmgG", 1, 0xa8c618), ("thinkSet", 4, 0xa8c648), ("tgtGet", 2, 0xa8c720),
        ("tgtBicGet", 3, 0xa8c850), ("tgtBicOnlyChk", 2, 0xa8c9a8), ("unitParaGet", 2, 0xa8ca50),
        ("unitParaSet", 3, 0xa8ca98), ("tecParaGet", 2, 0xa8cb08), ("partyParaGet", 2, 0xa8cb50),
        ("partyParaSet", 3, 0xa8cb98), ("thinkChk", 3, 0xa8cc08), ("statGet", 2, 0xa8cc70),
        ("statSet", 3, 0xa8ccc0), ("statClr", 3, 0xa8cd38), ("boost", 2, 0xa8cdb0), ("boostChk", 2, 0xa8ce30),
        ("boostAct", 1, 0xa8ce80), ("statBadProtect", 3, 0xa8ceb0), ("spAdd", 2, 0xa8cf40),
        ("rnd", 1, 0xa8cf90), ("VPadEnable", 0, 0xa8cfb0), ("VPadDisable", 0, 0xa8cfd0),
        ("VPadSet", 1, 0xa8cff0), ("msgOn", 1, 0xa8d018), ("msgOff", 0, 0xa8d058), ("msgOpen", 3, 0xa8d078),
        ("msgWait", 0, 0xa8d0f8), ("msgClose", 0, 0xa8d140), ("tutorial", 0, 0xa8d160),
        ("showCursor", 2, 0xa8d188), ("hideCursor", 0, 0xa8d200), ("setFog", 8, 0xa8d218),
        ("initLight", 0, 0xa8d498), ("setLight", 1, 0xa8d4e8), ("mapAngle", 2, 0xa8d7b8),
        ("mapColor", 3, 0xa8d858), ("learnSPset", 1, 0xa8d900), ("learnElset", 1, 0xa8da50),
        ("mapFieldType", 1, 0xa8db28), ("sndMode", 1, 0xa8db60), ("bgm", 1, 0xa8db88), ("adxPlay", 1, 0xa8dbe0),
        ("adxWait", 0, 0xa8dc38), ("caption", 1, 0xa8dc78), ("captionWait", 0, 0xa8dce0),
        ("scale", 2, 0xa8dd30), ("rainLoad", 0, 0xa8ddb8), ("rainLoadWait", 0, 0xa8de20), ("rain", 0, 0xa8de58),
        ("rainOff", 0, 0xa8dec0), ("faceSet", 2, 0xa8dee8), ("eneSet", 0, 0xa8df40), ("partsHide", 2, 0xa8df60),
        ("partsShow", 2, 0xa8dfc8), ("cinemaOn", 0, 0xa8e030), ("cinemaOff", 0, 0xa8e058),
        ("motSet", 2, 0xa8e080), ("motGet", 1, 0xa8e0d8), ("liveGet", 1, 0xa8e100),
    )),
    "robo": (0xab81f8, (
        ("addCmd", 2, 0xab1ef8), ("terminateCmd", 1, 0xab1f88), ("dispTecList", 1, 0xab2000),
        ("setTarget", 2, 0xab2970), ("setTargetBIC", 2, 0xab2a18), ("addAnimaPoint", 2, 0xab2078),
        ("eventStart", 1, 0xab2148), ("eventEnd", 0, 0xab2188), ("kaoOpen", 4, 0xab21d8),
        ("kaoOpen2", 4, 0xab2280), ("kaoWait", 0, 0xab2338), ("searchBIC", 2, 0xab2370),
        ("search", 2, 0xab2450), ("getInstance", 1, 0xab2af0), ("checkAnima", 2, 0xab2b60),
        ("checkSpecial", 2, 0xab2bf0), ("flagOn", 2, 0xab2c80), ("dispSkillName", 1, 0xab2d18),
        ("msgOpen", 4, 0xab2da0), ("msgWait", 0, 0xab2e38), ("msgClose", 0, 0xab2e70),
        ("checkLeader", 0, 0xab2e90), ("menuCtrl", 2, 0xab2f40), ("tutorial", 0, 0xab2f98),
        ("showCursor", 2, 0xab2fc0), ("hideCursor", 0, 0xab3038), ("mapRotXY", 2, 0xab3050),
        ("specialFlag", 1, 0xab3118), ("isManual", 1, 0xab3138), ("setAlpha", 2, 0xab3168),
        ("damageKind", 0, 0xab3200),
    )),
}


def lookup(cls: str, fn: str):
    """(min_args, USA handler address) of ``cls.fn``, or None."""
    hit = CLASSES.get(cls)
    if hit:
        for name, argc, handler in hit[1]:
            if name == fn:
                return argc, handler
    return None


def count():
    return len(CLASSES), sum(len(t[1]) for t in CLASSES.values())
