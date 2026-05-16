"""Generate a placeholder icon.ico if none exists.

A generic-icon exe is one of the most reliable Defender false-positive
triggers. We'd rather ship an ugly "X3" glyph than nothing. If
``packaging/icon.ico`` is already present (Jessi dropped a real one in),
leave it alone.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "icon.ico"


def main() -> None:
    if OUT.exists():
        print(f"{OUT.name} already exists — keeping it.")
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not available; skipping icon generation.")
        return

    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    images = []
    for w, h in sizes:
        img = Image.new("RGBA", (w, h), (24, 28, 48, 255))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", size=int(h * 0.55))
        except OSError:
            font = ImageFont.load_default()
        text = "X3"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((w - tw) / 2 - bbox[0], (h - th) / 2 - bbox[1]),
            text,
            font=font,
            fill=(220, 220, 240, 255),
        )
        images.append(img)

    images[0].save(OUT, format="ICO", sizes=sizes, append_images=images[1:])
    print(f"Wrote placeholder {OUT.name}")


if __name__ == "__main__":
    main()
