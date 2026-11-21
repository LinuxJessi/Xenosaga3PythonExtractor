"""engine_palettes.py — which CLUT the game itself binds to each part of a PSMT8 sheet.

New for this kit (2026-11-20, fifth pass). The XTX file does not record which of
its parked palettes colours which pixel: the engine sets the GS CLUT pointer
(CBP) per draw. This module holds the draw rectangles and CBPs read out of the
game code and data, so ``xtx_decode.plan_palettes`` can colour every drawn part
of a sheet exactly instead of ranking palettes. Everything here comes from
SLUS_213.89 (USA), its overlays OV01.OVL / OV04.OVL, and their Japanese
counterparts; ``xtx_decode.self_test`` re-reads the tables from the discs.

How a sheet reaches VRAM (FUN_001997d0): the XTX header is the upload
descriptor. +0x10 is the width, +0x12 (the "format" field) is the destination
buffer width DBW, +0x14 the height; the image goes to page DAT_004c83a2 (0x1c0
in the menus, set in FUN_0019a6f0; absolute block 0x3800). Every draw then
loads its CLUT from ``base * 32 + K`` (TEX2 ``(base*0x20 + K) << 37 |
0x2000000001300000``: PSMT8, CSM1, CLD 1), so K is a block offset inside the
sheet's own canvas, ``xtx_encode.cbp_xy(K)`` (TBW 8). Rectangles are in pixels
of the sheet's PSMT8 picture, ``(u0, v0, u1, v1)`` with u1/v1 exclusive.

Sources per sheet:

* window0/1/2 (``mnu\\xx\\window*.xtx``, 512 x 128 words US, 384 x 128 JP):
  - the sprite table at VA 0x402c38 (140 entries of u, v, w, h, CBP; read by
    FUN_002cfff0 / FUN_002d0828 through PTR_DAT_004039f8[0]) — portraits,
    item and status icons, HUD words, gauges. JP (SLPS_256.40, VA 0x4016b8)
    has the same table without entries 89-114 (the lowercase block at
    x >= 768, which the 768-px JP sheets do not have); the May 2006
    prototype (VA 0x4029f8) differs in one entry by one pixel;
  - draw functions with the CBP and the CLAMP region as immediates (listed in
    WINDOW_CODE with their addresses: the letter/digit printers of statfont.py,
    the gauges, tabs, frames, arrows);
* titleobj (``mnu\\xx\\titleobj.xtx``): FUN_00a810a0 in OV01.OVL (title menu)
  uploads the sheet to the same page and draws with TEX0 CBP 0x3b08 / 0x3b0c /
  0x3b18 (= base + 0x308 / 0x30c / 0x318): the menu words (v 0..108) with
  0x308, the selected-item glow (v 112..129) with 0x30c and the unselected
  bar (v 129..146) with 0x318. Those three tiles are in titleobj itself at
  canvas (0, 112), (16, 112), (32, 112): one colour each (grey 42/42/42,
  cyan 137/254/224, white) with an alpha ramp, which is why the CLUT
  detector (it wants >= 26 fully opaque entries) never found them. Same code
  and file on all five discs;
* the minigame sheet (``mg1\\xx\\Picture.xtx``): the sprite table of OV04.OVL
  (VA 0xaa54b8 US, 0xaa5098 JP, 79 entries, read by the sprite loop that sets
  TEX2 from entry +0x10). US and JP lay the sheet out differently;
* itemcap / segcap: the tables at VA 0x403728 / 0x403890 (PTR_DAT_004039f8[1]
  and [2]); they agree pixel for pixel with the picture-grid assignment that
  xtx_decode already made, so these two sheets render exactly as before.

What is not covered: parts of the window sheets that no table entry or draw
function found here reaches (some portrait cells, a few frames and pieces;
about a third of the non-zero pixels of window0) keep the ranked palette of
xtx_decode, and ``coverage()`` reports the share. ctrl.xtx has one palette.
"""
from __future__ import annotations

import hashlib
import struct
from typing import Dict, List, Optional, Sequence, Tuple

Rect = Tuple[int, int, int, int, int]          # u0, v0, u1, v1 (exclusive), CBP offset

# ---------------------------------------------------------------- the tables
# (u, v, w, h, CBP) exactly as stored (s32 x 5), entry order kept.

# SLUS_213.89 VA 0x402c38 (window sheets)
WINDOW_SPRITES = (
    (0, 9, 0, 0, 0x0), (259, 9, 26, 45, 0x348), (291, 9, 26, 45, 0x348),
    (323, 9, 26, 45, 0x34c), (355, 9, 26, 45, 0x34c), (387, 9, 26, 45, 0x358),
    (419, 9, 26, 45, 0x358), (451, 9, 26, 45, 0x35c), (483, 9, 26, 45, 0x35c),
    (259, 73, 26, 45, 0x368), (291, 73, 26, 45, 0x368), (323, 73, 26, 45, 0x36c),
    (355, 73, 26, 45, 0x36c), (387, 73, 26, 45, 0x378), (419, 73, 26, 45, 0x378),
    (321, 129, 25, 44, 0x370), (347, 129, 25, 44, 0x370), (373, 129, 25, 44, 0x370),
    (513, 54, 87, 17, 0x3b8), (600, 54, 67, 17, 0x3b8), (667, 54, 101, 17, 0x3b8),
    (513, 71, 61, 17, 0x3b8), (574, 71, 67, 17, 0x3b8), (581, 162, 63, 10, 0x398),
    (581, 173, 63, 10, 0x398), (581, 184, 63, 10, 0x398), (644, 154, 34, 22, 0x38c),
    (398, 128, 92, 10, 0x364), (398, 138, 92, 10, 0x364), (204, 119, 19, 6, 0x330),
    (204, 125, 19, 6, 0x330), (227, 54, 29, 32, 0x32c), (513, 114, 67, 15, 0x39c),
    (513, 130, 67, 15, 0x39c), (513, 146, 67, 15, 0x39c), (513, 162, 67, 15, 0x39c),
    (513, 178, 67, 15, 0x39c), (645, 114, 39, 39, 0x388), (724, 114, 40, 39, 0x388),
    (685, 114, 39, 39, 0x388), (223, 119, 9, 8, 0x330), (223, 127, 9, 8, 0x330),
    (322, 175, 59, 15, 0x370), (728, 89, 24, 24, 0x3ac), (513, 89, 23, 24, 0x3ac),
    (536, 89, 24, 24, 0x3ac), (560, 89, 24, 24, 0x3ac), (584, 89, 24, 24, 0x3ac),
    (608, 89, 24, 24, 0x3ac), (632, 89, 24, 24, 0x3ac), (656, 89, 24, 24, 0x3ac),
    (680, 89, 24, 24, 0x3ac), (704, 89, 24, 24, 0x3ac), (674, 0, 18, 18, 0x3bc),
    (513, 0, 17, 18, 0x3bc), (530, 0, 18, 18, 0x3bc), (548, 0, 18, 18, 0x3bc),
    (566, 0, 18, 18, 0x3bc), (584, 0, 18, 18, 0x3bc), (602, 0, 18, 18, 0x3bc),
    (620, 0, 18, 18, 0x3bc), (638, 0, 18, 18, 0x3bc), (656, 0, 18, 18, 0x3bc),
    (513, 18, 17, 18, 0x3bc), (530, 18, 18, 18, 0x3bc), (548, 18, 18, 18, 0x3bc),
    (566, 18, 18, 18, 0x3bc), (584, 18, 18, 18, 0x3bc), (602, 18, 18, 18, 0x3bc),
    (620, 18, 18, 18, 0x3bc), (638, 18, 18, 18, 0x3bc), (656, 18, 18, 18, 0x3bc),
    (674, 18, 18, 18, 0x3bc), (692, 18, 18, 18, 0x3bc), (710, 18, 18, 18, 0x3bc),
    (728, 19, 18, 17, 0x3bc), (746, 18, 18, 18, 0x3bc), (513, 36, 17, 18, 0x3bc),
    (530, 36, 18, 18, 0x3bc), (548, 36, 18, 18, 0x3bc), (567, 36, 17, 18, 0x3bc),
    (584, 36, 18, 18, 0x3bc), (602, 36, 18, 18, 0x3bc), (620, 36, 18, 18, 0x3bc),
    (638, 36, 18, 18, 0x3bc), (656, 36, 18, 18, 0x3bc), (674, 36, 18, 18, 0x3bc),
    (692, 36, 18, 18, 0x3bc), (710, 36, 18, 18, 0x3bc), (768, 33, 18, 17, 0x3cc),
    (786, 32, 18, 18, 0x3cc), (804, 32, 18, 18, 0x3cc), (822, 32, 18, 18, 0x3cc),
    (840, 32, 18, 18, 0x3cc), (858, 32, 18, 18, 0x3cc), (876, 32, 18, 18, 0x3cc),
    (894, 32, 18, 18, 0x3cc), (912, 32, 18, 18, 0x3cc), (930, 32, 18, 18, 0x3cc),
    (948, 32, 18, 18, 0x3cc), (966, 32, 18, 18, 0x3cc), (984, 32, 18, 17, 0x3cc),
    (1002, 32, 18, 18, 0x3cc), (769, 50, 17, 18, 0x3cc), (786, 50, 18, 18, 0x3cc),
    (804, 50, 18, 18, 0x3cc), (822, 50, 17, 18, 0x3cc), (840, 50, 18, 18, 0x3cc),
    (858, 50, 18, 18, 0x3cc), (876, 50, 18, 18, 0x3cc), (894, 50, 18, 18, 0x3cc),
    (912, 50, 18, 18, 0x3cc), (930, 50, 18, 18, 0x3cc), (948, 50, 18, 18, 0x3cc),
    (966, 50, 18, 18, 0x3cc), (692, 0, 18, 18, 0x3bc), (710, 0, 18, 18, 0x3bc),
    (728, 0, 18, 18, 0x3bc), (136, 135, 16, 15, 0x31c), (152, 119, 16, 15, 0x31c),
    (152, 135, 16, 15, 0x31c), (136, 119, 16, 15, 0x31c), (399, 148, 30, 41, 0x360),
    (678, 154, 17, 22, 0x38c), (696, 154, 12, 11, 0x38c), (696, 165, 12, 11, 0x38c),
    (709, 154, 17, 22, 0x38c), (644, 176, 44, 15, 0x38c), (430, 149, 20, 17, 0x360),
    (449, 149, 20, 17, 0x360), (430, 168, 20, 17, 0x360), (451, 169, 18, 17, 0x360),
    (483, 149, 1, 24, 0x360), (472, 149, 13, 24, 0x360), (487, 149, 16, 24, 0x360),
    (181, 135, 15, 16, 0x330), (197, 135, 15, 16, 0x330), (237, 146, 18, 4, 0x330),
    (165, 151, 24, 25, 0x320), (189, 151, 22, 22, 0x320),
)

# SLUS_213.89 VA 0x403728 (itemcap)
ITEMCAP_SPRITES = (
    (0, 0, 124, 140, 0x708), (0, 140, 124, 140, 0x70c), (0, 280, 124, 140, 0x718),
    (124, 0, 124, 140, 0x71c), (124, 140, 124, 140, 0x728), (124, 280, 124, 140, 0x72c),
    (256, 0, 124, 140, 0x748), (256, 140, 124, 140, 0x74c), (256, 280, 124, 140, 0x758),
    (380, 0, 124, 140, 0x75c), (380, 140, 124, 140, 0x768), (380, 280, 124, 140, 0x76c),
    (512, 0, 124, 140, 0x788), (512, 140, 124, 140, 0x78c), (512, 280, 124, 140, 0x798),
    (512, 280, 124, 140, 0x798), (512, 280, 124, 140, 0x798), (512, 280, 124, 140, 0x798),
)

# SLUS_213.89 VA 0x403890 (segcap)
SEGCAP_SPRITES = (
    (0, 0, 75, 65, 0x308), (75, 0, 75, 65, 0x30c), (150, 0, 75, 65, 0x318),
    (0, 65, 75, 65, 0x31c), (75, 65, 75, 65, 0x328), (150, 65, 75, 65, 0x32c),
    (0, 130, 75, 65, 0x338), (75, 130, 75, 65, 0x33c), (256, 0, 75, 65, 0x348),
    (331, 0, 75, 65, 0x34c), (406, 0, 75, 65, 0x358), (256, 65, 75, 65, 0x35c),
    (331, 65, 75, 65, 0x368), (406, 65, 75, 65, 0x36c), (256, 130, 75, 65, 0x378),
    (256, 130, 75, 65, 0x378), (256, 130, 75, 65, 0x378), (256, 130, 75, 65, 0x378),
)

# OV04.OVL (USA) VA 0xaa54b8 (minigame sheet)
MINIGAME_SPRITES_US = (
    (0, 0, 76, 48, 0x308), (125, 48, 58, 42, 0x308), (77, 0, 70, 48, 0x308),
    (0, 48, 60, 42, 0x308), (0, 48, 60, 42, 0x308), (61, 48, 63, 42, 0x308),
    (148, 0, 16, 48, 0x308), (165, 0, 52, 48, 0x308), (0, 210, 256, 10, 0x328),
    (0, 98, 95, 96, 0x31c), (256, 0, 32, 32, 0x348), (288, 0, 32, 32, 0x348),
    (320, 0, 32, 32, 0x348), (352, 0, 32, 32, 0x348), (384, 0, 32, 32, 0x348),
    (416, 0, 32, 32, 0x348), (448, 0, 32, 32, 0x348), (480, 0, 32, 32, 0x348),
    (256, 32, 32, 32, 0x348), (288, 32, 32, 32, 0x348), (320, 32, 32, 32, 0x348),
    (352, 32, 32, 32, 0x348), (384, 32, 32, 32, 0x348), (416, 32, 32, 32, 0x348),
    (448, 32, 32, 32, 0x348), (480, 32, 32, 32, 0x348), (256, 64, 32, 32, 0x348),
    (288, 64, 32, 32, 0x348), (320, 64, 32, 32, 0x348), (352, 64, 32, 32, 0x348),
    (384, 64, 32, 32, 0x348), (416, 64, 32, 32, 0x348), (448, 64, 32, 32, 0x348),
    (480, 64, 32, 32, 0x348), (256, 96, 32, 32, 0x348), (288, 96, 32, 32, 0x348),
    (352, 128, 32, 32, 0x348), (320, 96, 32, 32, 0x348), (352, 96, 32, 32, 0x348),
    (384, 96, 32, 32, 0x348), (416, 96, 32, 32, 0x348), (448, 96, 32, 32, 0x348),
    (480, 96, 32, 32, 0x348), (256, 128, 32, 32, 0x348), (288, 128, 32, 32, 0x348),
    (320, 128, 32, 32, 0x348), (384, 128, 32, 32, 0x348), (384, 160, 32, 32, 0x348),
    (416, 160, 32, 32, 0x348), (448, 160, 32, 32, 0x348), (480, 128, 32, 32, 0x348),
    (256, 160, 32, 32, 0x348), (288, 160, 32, 32, 0x348), (320, 160, 32, 32, 0x348),
    (480, 160, 32, 32, 0x348), (0, 194, 14, 16, 0x30c), (14, 194, 14, 16, 0x30c),
    (28, 194, 14, 16, 0x30c), (42, 194, 14, 16, 0x30c), (56, 194, 14, 16, 0x30c),
    (70, 194, 14, 16, 0x30c), (84, 194, 14, 16, 0x30c), (98, 194, 14, 16, 0x30c),
    (112, 194, 14, 16, 0x30c), (126, 194, 14, 16, 0x30c), (140, 194, 14, 16, 0x30c),
    (154, 194, 14, 16, 0x30c), (256, 192, 26, 26, 0x34c), (282, 192, 26, 26, 0x34c),
    (334, 192, 26, 26, 0x34c), (360, 192, 26, 26, 0x34c), (386, 192, 26, 26, 0x34c),
    (411, 192, 26, 26, 0x34c), (308, 192, 26, 26, 0x34c), (436, 192, 52, 26, 0x34c),
    (96, 98, 37, 36, 0x32c), (167, 98, 32, 31, 0x32c), (134, 98, 32, 31, 0x32c),
    (0, 0, 256, 187, 0x308),
)

# OV04.OVL (Japan) VA 0xaa5098
MINIGAME_SPRITES_JP = (
    (0, 0, 76, 42, 0x308), (76, 0, 73, 42, 0x308), (149, 0, 76, 42, 0x308),
    (0, 42, 34, 42, 0x318), (34, 42, 34, 42, 0x318), (68, 42, 73, 42, 0x318),
    (141, 42, 18, 42, 0x318), (169, 42, 53, 42, 0x318), (0, 184, 256, 10, 0x328),
    (0, 88, 95, 96, 0x31c), (256, 0, 32, 32, 0x348), (288, 0, 32, 32, 0x348),
    (320, 0, 32, 32, 0x348), (352, 0, 32, 32, 0x348), (384, 0, 32, 32, 0x348),
    (416, 0, 32, 32, 0x348), (448, 0, 32, 32, 0x348), (480, 0, 32, 32, 0x348),
    (256, 32, 32, 32, 0x348), (288, 32, 32, 32, 0x348), (320, 32, 32, 32, 0x348),
    (352, 32, 32, 32, 0x348), (384, 32, 32, 32, 0x348), (416, 32, 32, 32, 0x348),
    (448, 32, 32, 32, 0x348), (480, 32, 32, 32, 0x348), (256, 64, 32, 32, 0x348),
    (288, 64, 32, 32, 0x348), (320, 64, 32, 32, 0x348), (352, 64, 32, 32, 0x348),
    (384, 64, 32, 32, 0x348), (416, 64, 32, 32, 0x348), (448, 64, 32, 32, 0x348),
    (480, 64, 32, 32, 0x348), (256, 96, 32, 32, 0x348), (288, 96, 32, 32, 0x348),
    (352, 128, 32, 32, 0x348), (320, 96, 32, 32, 0x348), (352, 96, 32, 32, 0x348),
    (384, 96, 32, 32, 0x348), (416, 96, 32, 32, 0x348), (448, 96, 32, 32, 0x348),
    (480, 96, 32, 32, 0x348), (256, 128, 32, 32, 0x348), (288, 128, 32, 32, 0x348),
    (320, 128, 32, 32, 0x348), (384, 128, 32, 32, 0x348), (384, 160, 32, 32, 0x348),
    (416, 160, 32, 32, 0x348), (448, 160, 32, 32, 0x348), (480, 128, 32, 32, 0x348),
    (256, 160, 32, 32, 0x348), (288, 160, 32, 32, 0x348), (320, 160, 32, 32, 0x348),
    (480, 160, 32, 32, 0x348), (0, 194, 14, 16, 0x30c), (14, 194, 14, 16, 0x30c),
    (28, 194, 14, 16, 0x30c), (42, 194, 14, 16, 0x30c), (56, 194, 14, 16, 0x30c),
    (70, 194, 14, 16, 0x30c), (84, 194, 14, 16, 0x30c), (98, 194, 14, 16, 0x30c),
    (112, 194, 14, 16, 0x30c), (126, 194, 14, 16, 0x30c), (140, 194, 14, 16, 0x30c),
    (154, 194, 14, 16, 0x30c), (256, 192, 26, 26, 0x34c), (282, 192, 26, 26, 0x34c),
    (334, 192, 26, 26, 0x34c), (360, 192, 26, 26, 0x34c), (386, 192, 26, 26, 0x34c),
    (411, 192, 26, 26, 0x34c), (308, 192, 26, 26, 0x34c), (436, 192, 52, 26, 0x34c),
    (96, 89, 37, 36, 0x32c), (167, 89, 32, 31, 0x32c), (134, 89, 32, 31, 0x32c),
    (0, 0, 256, 187, 0x308),
)

# ------------------------------------------------- draws coded in functions
# (u0, v0, u1, v1, CBP, function): the CLAMP_1 region (REGION_CLAMP, MINU..MAXU
# x MINV..MAXV inclusive) or the UV corners of each sprite, ranges taken over
# the arguments the callers pass.

WINDOW_CODE = (
    (0, 0, 256, 32, 0x308, "FUN_0023c2c0"),      # letters A-Z and symbols (statfont.py)
    (768, 0, 1024, 32, 0x3c8, "FUN_0023c2c0"),   # letters a-z (US sheets only)
    (0, 32, 130, 49, 0x30c, "FUN_0023c6f8"),     # digits 13 x 17
    (130, 32, 143, 49, 0x30c, "FUN_0023ce40"),
    (143, 32, 160, 49, 0x30c, "FUN_0023e2f0"),
    (160, 32, 173, 49, 0x30c, "FUN_0023e5d8"),
    (173, 32, 256, 43, 0x318, "FUN_0023d248"),
    (173, 43, 256, 54, 0x318, "FUN_0023d428"),
    (180, 54, 226, 87, 0x328, "FUN_0023cfc8"),     # gauge bar and its two caps
    (226, 54, 256, 86, 0x32c, "FUN_0023d8b8"),
    (0, 54, 180, 118, 0x31c, "FUN_0023eba8"),      # icons 0-11 (30 x 32, row of 6)
    (0, 118, 136, 139, 0x31c, "FUN_0023eba8"),     # icons 12-16 (21 px high)
    (0, 150, 165, 169, 0x334, "FUN_0023bf30"),     # tabs (also FUN_00271280)
    (0, 169, 130, 187, 0x324, "FUN_0023ca38"),     # large digits 13 x 18
    (212, 103, 228, 119, 0x338, "FUN_0023e128"),   # every caller passes 5
    (228, 87, 234, 109, 0x33c, "FUN_0023da40"),
    (234, 87, 242, 109, 0x33c, "FUN_0021b518"),    # through FUN_0023bd60
    (242, 87, 256, 100, 0x33c, "FUN_00220618"),    # through FUN_0023bd60
    (232, 119, 256, 138, 0x330, "FUN_0023e8c0"),
    (212, 135, 228, 151, 0x330, "FUN_0023ee28"),
    (180, 119, 196, 135, 0x330, "FUN_0023f0e8"),
    (180, 135, 212, 151, 0x330, "FUN_002705e0"),   # GIF template at DAT_003e3b70
    (644, 113, 764, 153, 0x388, "FUN_0023f860"),
    (727, 154, 744, 171, 0x38c, "FUN_0023ef88"),
    (580, 113, 628, 161, 0x3a8, "FUN_0026fad0"),   # 9-slice frame, entry 0 of DAT_003e3b50
    (629, 121, 644, 122, 0x3a8, "FUN_00270028"),
)

# OV01.OVL FUN_00a810a0 (all five discs)
TITLEOBJ_CODE = (
    (0, 0, 120, 108, 0x308, "FUN_00a810a0"),      # menu words: V = row * 18 (+54 for DISC n), U 0..120
    (0, 112, 140, 129, 0x30c, "FUN_00a810a0"),    # selected item: V 0x700..0x810, U 0..0x8c0
    (0, 129, 140, 146, 0x318, "FUN_00a810a0"),    # other items: V 0x810..0x920
)

# CLUT block (canvas rows 96..127) of the retail minigame sheets: tells US from JP
# when the file name does not
_MINIGAME_CLUTS = {"ae6251d1c108308ee38813d335250618721fc7af": "us",
                   "9027d27ed36495d0968a8b9e22428e36561a6130": "jp"}


def _from_table(table: Sequence[Tuple[int, int, int, int, int]], src: str) -> List[Tuple]:
    return [(u, v, u + w, v + h, c, f"{src}[{k}]") for k, (u, v, w, h, c) in enumerate(table) if w and h]


def _region(name: str) -> Optional[str]:
    parts = name.replace("\\", "/").lower().split("/")
    return "jp" if "jp" in parts else "us" if "us" in parts else None


def sheet_kind(canvas_w: int, canvas_h: int, canvas: bytes = b"", name: str = "") -> Optional[str]:
    """Which sheet this canvas is, by its size (unique among the eight PSMT8 files
    of a disc) and, for the minigame sheet, its region (file name, else the CLUT
    block of the retail files). None = no engine binding known."""
    size = (canvas_w, canvas_h)
    if size in ((512, 128), (384, 128)):
        return "window"
    if size == (72, 128):
        return "titleobj"
    if size == (320, 256):
        return "itemcap"
    if size == (246, 128):
        return "segcap"
    if size == (256, 128):
        reg = _region(name)
        if reg is None and len(canvas) >= canvas_w * canvas_h * 4:
            reg = _MINIGAME_CLUTS.get(hashlib.sha1(canvas[96 * canvas_w * 4:canvas_w * canvas_h * 4]).hexdigest())
        return f"minigame-{reg}" if reg else None
    return None


def draws(kind: Optional[str]) -> List[Tuple]:
    """``[(u0, v0, u1, v1, cbp, source)]`` of a sheet kind."""
    if kind == "window":
        return _from_table(WINDOW_SPRITES, "VA 0x402c38") + list(WINDOW_CODE)
    if kind == "titleobj":
        return list(TITLEOBJ_CODE)
    if kind == "itemcap":
        return _from_table(ITEMCAP_SPRITES, "VA 0x403728")
    if kind == "segcap":
        return _from_table(SEGCAP_SPRITES, "VA 0x403890")
    if kind == "minigame-us":
        return _from_table(MINIGAME_SPRITES_US, "OV04 VA 0xaa54b8")
    if kind == "minigame-jp":
        return _from_table(MINIGAME_SPRITES_JP, "OV04 VA 0xaa5098")
    return []


def engine_rects(canvas_w: int, canvas_h: int, canvas: bytes = b"", name: str = ""
                 ) -> List[Tuple[int, int, int, int, Tuple[int, int]]]:
    """Palette rectangles ``(u0, v0, u1, v1, tile)`` for a sheet, clipped to its
    picture, largest first (a later, smaller draw wins where two overlap: the
    minigame's whole-panel sprite under its icons). [] when unknown."""
    from xtx_encode import cbp_xy
    W, H = canvas_w * 2, canvas_h * 2
    out = []
    for u0, v0, u1, v1, cbp, _src in draws(sheet_kind(canvas_w, canvas_h, canvas, name)):
        tx, ty = cbp_xy(cbp)
        if u0 >= W or v0 >= H or tx + 16 > canvas_w or ty + 16 > canvas_h:
            continue
        out.append((u0, v0, min(u1, W), min(v1, H), (tx, ty)))
    out.sort(key=lambda r: -(r[2] - r[0]) * (r[3] - r[1]))
    return out


def coverage(canvas_w: int, canvas_h: int, idx: bytes, canvas: bytes = b"", name: str = "") -> float:
    """Share of the non-zero indices that an engine rectangle covers."""
    import numpy as np
    W, H = canvas_w * 2, canvas_h * 2
    im = np.frombuffer(idx, np.uint8).reshape(H, W)
    m = np.zeros((H, W), bool)
    for u0, v0, u1, v1, _t in engine_rects(canvas_w, canvas_h, canvas, name):
        m[v0:v1, u0:u1] = True
    nz = im > 0
    return float((nz & m).sum() / max(1, nz.sum()))


# ---------------------------------------------------- re-reading the discs

def find_table(image: bytes, table: Sequence[Tuple[int, int, int, int, int]], first: int = 1
               ) -> Optional[int]:
    """File offset of ``table`` in an executable image, found by entries
    ``first``..``first + 2`` (s32 x 5 each); None when absent."""
    pat = b"".join(struct.pack("<5i", *e) for e in table[first:first + 3])
    i = image.find(pat)
    return None if i < 0 else i - 20 * first


def read_table(image: bytes, off: int, n: int) -> List[Tuple[int, int, int, int, int]]:
    return [struct.unpack_from("<5i", image, off + 20 * k) for k in range(n)]


def title_cbps(ov01: bytes) -> List[int]:
    """CBP offsets of the TEX0 values OV01 builds with lui 0x2007 / ori K / dsll /
    ori 0x6934 / dsll / ori 0x3800 (TBP 0x3800 = the sheet page), in code order."""
    n = len(ov01) // 4
    w = struct.unpack(f"<{n}I", ov01[:n * 4])
    out = []
    for i in range(n - 5):
        a, b, _c, d, _e, f = w[i:i + 6]
        if (a >> 26 == 0x0F and a & 0xFFFF == 0x2007 and b >> 26 == 0x0D
                and d >> 26 == 0x0D and d & 0xFFFF == 0x6934 and f >> 26 == 0x0D and f & 0xFFFF == 0x3800):
            v = ((0x2007 << 16 | b & 0xFFFF) << 32) | (0x6934 << 16 | 0x3800)
            out.append((v >> 37 & 0x3FFF) - 0x3800)
    return out
