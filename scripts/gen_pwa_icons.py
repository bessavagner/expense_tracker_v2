"""Generate PWA icons for the 'ledger' theme. One-off; run with:
    uv run --with pillow python scripts/gen_pwa_icons.py
Outputs to src/backend/static/images/pwa/.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TEAL = (20, 120, 116)      # #147874 (theme primary)
PAPER = (252, 252, 249)    # #fcfcf9 (glyph ink)
OUT = Path(__file__).resolve().parent.parent / "src/backend/static/images/pwa"
OUT.mkdir(parents=True, exist_ok=True)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _font(size):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _draw(size, *, rounded, glyph_fraction):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        radius = int(size * 0.22)
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=TEAL)
    else:  # maskable: full-bleed background
        d.rectangle([0, 0, size, size], fill=TEAL)
    text = "R$"
    font = _font(int(size * glyph_fraction))
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), text, font=font, fill=PAPER)
    return img


def main():
    _draw(512, rounded=True, glyph_fraction=0.52).save(OUT / "icon-512.png")
    _draw(192, rounded=True, glyph_fraction=0.52).save(OUT / "icon-192.png")
    _draw(512, rounded=False, glyph_fraction=0.42).save(OUT / "icon-maskable-512.png")
    _draw(180, rounded=True, glyph_fraction=0.52).save(OUT / "apple-touch-icon.png")
    print("wrote icons to", OUT)


if __name__ == "__main__":
    main()
