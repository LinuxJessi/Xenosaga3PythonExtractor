"""Join frames rendered by render_motion.py into a looping GIF on the
front-page grey (244, 244, 246): every frame cropped to the union of the
figures' extent plus a margin, scaled to a target height, one shared
palette.

    python make_gif.py FRAMEDIR OUT.gif [--height 420] [--ms 33] [--colors 160]
"""
import argparse
import os

from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("frames")
ap.add_argument("out")
ap.add_argument("--height", type=int, default=420)
ap.add_argument("--ms", type=int, default=33, help="milliseconds per frame")
ap.add_argument("--colors", type=int, default=160)
ap.add_argument("--margin", type=int, default=12)
a = ap.parse_args()
names = sorted(f for f in os.listdir(a.frames) if f.endswith(".png"))
ims = [Image.open(os.path.join(a.frames, f)).convert("RGBA") for f in names]
box = None
for im in ims:
    b = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if b:
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                     max(box[2], b[2]), max(box[3], b[3]))
w, h = ims[0].size
m = a.margin
box = (max(0, box[0] - m), max(0, box[1] - m), min(w, box[2] + m),
       min(h, box[3] + m))
scale = min(1.0, a.height / float(box[3] - box[1]))
size = (int(round((box[2] - box[0]) * scale)),
        int(round((box[3] - box[1]) * scale)))
out = []
for im in ims:
    bg = Image.new("RGBA", im.size, (244, 244, 246, 255))
    bg.alpha_composite(im)
    out.append(bg.crop(box).convert("RGB").resize(size, Image.LANCZOS))
# one palette from a strip of every frame
strip = Image.new("RGB", (size[0], size[1] * len(out)))
for i, im in enumerate(out):
    strip.paste(im, (0, i * size[1]))
pal = strip.quantize(colors=a.colors, method=Image.MEDIANCUT)
frames = [im.quantize(palette=pal, dither=Image.FLOYDSTEINBERG) for im in out]
frames[0].save(a.out, save_all=True, append_images=frames[1:], loop=0,
               duration=a.ms, disposal=1, optimize=False)
print("%s: %d frames, %dx%d, %d bytes" % (a.out, len(frames), size[0],
                                          size[1], os.path.getsize(a.out)))
