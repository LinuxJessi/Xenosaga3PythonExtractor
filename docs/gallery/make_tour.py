#!/usr/bin/env python3
"""Builds the "Movies, fonts and menus" images in docs/images/tour/ from Disc 1.

    python3 docs/gallery/make_tour.py "Disc 1.iso" [work-dir]

Steps (all with this kit's own commands, then Pillow/ffmpeg to lay them out):

  cli.py dump --match 'mnu\\'          the menu folder (UI sheets, synopsis pictures)
  cli.py dump --match s000300          the first movie, mov\\s000300.sfd
  cli.py dump --match C3kosmos00.chr   KOS-MOS's field model package
  cli.py browse --kinds images,movies,textures_png
  cli.py font-extract                  font0/font1 sheets
  cli.py chr-decode                    KOS-MOS's texture pages

Outputs:
  movie_s000300.jpg       frame at 0:40 of s000300.sfd.mp4
  ui_sheets.jpg           item icons, battle-window portraits, controller, a menu background
  font_sheet.png          font0 sheet 0
  synopsis_pictures.jpg   four of the 71 mnu\\syno pictures behind the synopsis screen
  textures_kosmos.png     KOS-MOS's texture pages from C3kosmos00.chr, 2x nearest

The idea (one picture per tour row, built from the kit's own exports) follows
the Episode II kit's docs/images/tour/; the code is this kit's own.
"""
import os
import subprocess
import sys

from PIL import Image

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(KIT, "docs", "images", "tour")
BG = (40, 42, 48, 255)


def cli(*a):
    subprocess.run([sys.executable, os.path.join(KIT, "cli.py"), *a], check=True)


def flat(im):
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, BG)
    bg.alpha_composite(im)
    return bg


def row(ims, h, gap=10):
    ims = [i.resize((round(i.width * h / i.height), h), Image.LANCZOS) for i in ims]
    w = sum(i.width for i in ims) + gap * (len(ims) + 1)
    canvas = Image.new("RGBA", (w, h + 2 * gap), BG)
    x = gap
    for i in ims:
        canvas.alpha_composite(i, (x, gap))
        x += i.width + gap
    return canvas


def main():
    iso = sys.argv[1]
    work = sys.argv[2] if len(sys.argv) > 2 else os.path.join("out", "tour")
    os.makedirs(OUT, exist_ok=True)
    d = os.path.join(work, "d")
    b = os.path.join(work, "b")
    for m in ("mnu\\", "s000300", "C3kosmos00.chr"):
        cli("dump", "--iso", iso, "--out", d, "--match", m)
    cli("browse", "--dump", os.path.join(d, "dump"), "--stage", b,
        "--kinds", "images,movies,textures_png")
    cli("font-extract", "--iso", iso, "--out", os.path.join(work, "font"))
    ktex = os.path.join(work, "ktex")
    cli("chr-decode", "--chr", os.path.join(d, "dump", "chain0", "mdl", "chr", "pc", "C3kosmos00.chr"),
        "--out", ktex)

    # 1. movie frame
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "40", "-i",
                    os.path.join(b, "movies", "chain1", "mov", "s000300.mp4"),
                    "-frames:v", "1", "-q:v", "3", os.path.join(OUT, "movie_s000300.jpg")], check=True)

    # 2. UI sheets
    t = os.path.join(b, "textures_png", "chain0", "mnu")
    items = flat(Image.open(os.path.join(t, "itemcap.png"))).crop((0, 0, 640, 384))
    w0 = flat(Image.open(os.path.join(t, "us", "window0.png"))).crop((256, 0, 512, 96))
    w0 = w0.resize((w0.width * 2, w0.height * 2), Image.NEAREST)
    ctrl = flat(Image.open(os.path.join(t, "ctrl.png"))).crop((0, 0, 256, 192))
    haikei = flat(Image.open(os.path.join(t, "pse", "haikei.png")))
    row([haikei, items, ctrl], 300).convert("RGB").save(os.path.join(OUT, "ui_sheets.jpg"), quality=88)
    row([w0], 192).convert("RGB").save(os.path.join(OUT, "ui_portraits.jpg"), quality=90)

    # 3. font sheet
    Image.open(os.path.join(work, "font", "font0_sheet0.png")).save(os.path.join(OUT, "font_sheet.png"), optimize=True)

    # 4. synopsis pictures, 2 x 2
    s = os.path.join(b, "images", "chain0", "mnu", "syno")
    # the pictures sit in rows 56-372 of a 512x448 page between flat bands; keep the picture
    pics = [Image.open(os.path.join(s, f"{n}.jpg")).convert("RGBA").crop((0, 56, 512, 373))
            for n in ("010", "040", "170", "220")]
    top, bot = row(pics[:2], 256), row(pics[2:], 256)
    sheet = Image.new("RGBA", (top.width, top.height + bot.height - 10), BG)
    sheet.alpha_composite(top, (0, 0))
    sheet.alpha_composite(bot, (0, top.height - 10))
    sheet.convert("RGB").save(os.path.join(OUT, "synopsis_pictures.jpg"), quality=86)

    # 5. KOS-MOS texture pages: the larger named pages, 2x nearest, packed in rows
    names = ["00_C3kosmos01_face_S", "13_kosmos_eye2", "04_hair_longL02", "03_hair_longL03",
             "05_kosmos_tiara_02", "07_kosmos_gold", "22_kosmos_kata00", "27_kosmos_kata03",
             "25_kosmos_siro00", "47_kosmos_siro03", "41_kosmos01_kuro00", "42_kosmos_kubi00",
             "26_kosmos_arm01", "33_kosmos_asi07", "50_kosmos_asi01",
             "37_kosmos_asi14", "53_kosmos_senaka00", "45_kosmos_hada00", "40_kosmos_mayuge2"]
    tiles = []
    for n in names:
        im = flat(Image.open(os.path.join(ktex, n + ".png")))
        tiles.append(im.resize((im.width * 2, im.height * 2), Image.NEAREST))
    tiles.sort(key=lambda im: -im.height)
    W, gap = 1200, 8
    rows, cur, cw = [], [], gap
    for im in tiles:
        if cw + im.width + gap > W and cur:
            rows.append(cur); cur, cw = [], gap
        cur.append(im); cw += im.width + gap
    rows.append(cur)
    H = sum(max(i.height for i in r) + gap for r in rows) + gap
    canvas = Image.new("RGBA", (W, H), BG)
    y = gap
    for r in rows:
        x = gap
        for im in r:
            canvas.alpha_composite(im, (x, y)); x += im.width + gap
        y += max(i.height for i in r) + gap
    canvas.convert("RGB").save(os.path.join(OUT, "textures_kosmos.png"), optimize=True)


if __name__ == "__main__":
    main()
