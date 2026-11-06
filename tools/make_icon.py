"""Regenerate assets/icon.ico (needs Pillow). Run: python tools/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024  # draw large, downscale for clean edges
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# background tile
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=(24, 32, 44, 255))
# desk
d.rounded_rectangle((170, 690, S - 170, 745), radius=26, fill=(222, 170, 98, 255))
d.rectangle((230, 745, 275, 860), fill=(222, 170, 98, 255))
d.rectangle((S - 275, 745, S - 230, 860), fill=(222, 170, 98, 255))
# music note on the desk
white = (245, 245, 245, 255)
d.ellipse((300, 500, 470, 630), fill=white)
d.ellipse((560, 450, 730, 580), fill=white)
d.rectangle((425, 230, 470, 570), fill=white)
d.rectangle((685, 180, 730, 520), fill=white)
d.polygon([(425, 230), (730, 180), (730, 270), (425, 320)], fill=white)
# download badge
d.ellipse((650, 600, 930, 880), fill=(232, 76, 61, 255))
d.rectangle((770, 650, 810, 770), fill=white)
d.polygon([(720, 750), (860, 750), (790, 830)], fill=white)

out = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
out.parent.mkdir(exist_ok=True)
img.resize((256, 256), Image.LANCZOS).save(
    out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(out.with_suffix(".png"))
print("wrote", out)
