"""Regenerate assets/icon.ico and assets/icon.png (needs Pillow).

    python tools/make_icon.py

Every size is drawn separately (supersampled, then downscaled) instead of
shrinking one big image. Small sizes (taskbar, title bar: 16-40 px) use a
simplified, bolder design so they stay crisp; the desk only appears from 48 px.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SS = 8  # supersampling factor

TILE = (24, 32, 44, 255)
WHITE = (245, 245, 245, 255)
WOOD = (222, 170, 98, 255)
RED = (232, 76, 61, 255)


def draw(size):
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = S / 100  # design units: 0..100
    small = size <= 40

    def box(x0, y0, x1, y1):
        return [round(x0 * u), round(y0 * u), round(x1 * u), round(y1 * u)]

    # tile: fills more of the canvas when small (no wasted pixels)
    m = 1 if small else 4
    d.rounded_rectangle(box(m, m, 100 - m, 100 - m), radius=round((18 if small else 21) * u), fill=TILE)

    if small:
        # bold beamed eighth notes, centred a bit up-left, no desk
        d.ellipse(box(17, 55, 43, 75), fill=WHITE)
        d.ellipse(box(51, 47, 77, 67), fill=WHITE)
        d.rectangle(box(35, 20, 43, 66), fill=WHITE)
        d.rectangle(box(69, 12, 77, 58), fill=WHITE)
        d.polygon([(35 * u, 20 * u), (77 * u, 12 * u), (77 * u, 26 * u), (35 * u, 34 * u)], fill=WHITE)
        # big download badge
        d.ellipse(box(55, 55, 98, 98), fill=RED, outline=TILE, width=round(3 * u))
        d.rectangle(box(73, 63, 80, 80), fill=WHITE)
        d.polygon([(64 * u, 77 * u), (89 * u, 77 * u), (76.5 * u, 91 * u)], fill=WHITE)
    else:
        # desk
        d.rounded_rectangle(box(17, 67, 83, 73), radius=round(2.5 * u), fill=WOOD)
        d.rectangle(box(22.5, 72, 27, 84), fill=WOOD)
        d.rectangle(box(73, 72, 77.5, 84), fill=WOOD)
        # notes
        d.ellipse(box(29, 49, 46, 62), fill=WHITE)
        d.ellipse(box(55, 44, 72, 57), fill=WHITE)
        d.rectangle(box(41.5, 22, 46, 56), fill=WHITE)
        d.rectangle(box(67.5, 17, 72, 51), fill=WHITE)
        d.polygon([(41.5 * u, 22 * u), (72 * u, 17 * u), (72 * u, 26 * u), (41.5 * u, 31 * u)], fill=WHITE)
        # download badge
        d.ellipse(box(63, 58, 92, 87), fill=RED, outline=TILE, width=round(1.5 * u))
        d.rectangle(box(75.5, 63, 79.5, 75), fill=WHITE)
        d.polygon([(70 * u, 74 * u), (85 * u, 74 * u), (77.5 * u, 82 * u)], fill=WHITE)

    out = img.resize((size, size), Image.LANCZOS)
    if size <= 32:  # restore edge contrast lost in downscaling
        out = out.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=0))
    return out


def main():
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(exist_ok=True)
    imgs = [draw(s) for s in SIZES]
    big = imgs[-1]
    big.save(assets / "icon.ico", format="ICO", sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
    big.save(assets / "icon.png")
    # preview sheet for checking small sizes by eye
    sheet = Image.new("RGBA", (sum(SIZES) + 10 * len(SIZES), 256), (240, 240, 240, 255))
    x = 0
    for im in imgs:
        sheet.paste(im, (x, 256 - im.height), im)
        x += im.width + 10
    sheet.save(assets.parent / "build" / "icon-preview.png") if (assets.parent / "build").is_dir() else None
    print("wrote", assets / "icon.ico", "sizes:", SIZES)


if __name__ == "__main__":
    main()
