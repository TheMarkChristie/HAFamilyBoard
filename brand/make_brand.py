"""Draw the Family Board icon and logo for HACS and the integrations page (custom_components/family_board/brand/).

A rounded deep-blue square, a white board with two pinned rows, and three coloured discs for the people in front of
it. PNG only, drawn with Pillow: no fonts, so it renders the same on any machine.

    python brand/make_brand.py
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "custom_components", "family_board", "brand")

BLUE = (31, 58, 138, 255)
BOARD = (246, 248, 252, 255)
LINE = (174, 186, 214, 255)
PEOPLE = [(79, 140, 255, 255), (255, 107, 107, 255), (81, 207, 102, 255)]


def icon(size: int) -> Image.Image:
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(56 * s), fill=BLUE)
    # the board
    d.rounded_rectangle([int(44 * s), int(40 * s), int(212 * s), int(164 * s)], radius=int(14 * s), fill=BOARD)
    for i, y in enumerate((74, 102, 130)):
        d.rounded_rectangle([int(66 * s), int(y * s), int((112 + i * 26) * s), int((y + 10) * s)], radius=int(5 * s), fill=LINE)
    d.ellipse([int(120 * s), int(28 * s), int(136 * s), int(44 * s)], fill=(220, 60, 60, 255))   # the pin
    # the people, standing in front
    for i, (cx, colour) in enumerate(zip((84, 128, 172), PEOPLE)):
        r = int(22 * s)
        d.ellipse([int(cx * s) - r, int(178 * s) - r, int(cx * s) + r, int(178 * s) + r], fill=colour)
        d.rounded_rectangle([int(cx * s) - int(30 * s), int(198 * s), int(cx * s) + int(30 * s), int(236 * s)], radius=int(16 * s), fill=colour)
    return img


def logo(width: int, height: int) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ic = icon(height)
    img.alpha_composite(ic, (0, 0))
    d = ImageDraw.Draw(img)
    # a wordmark drawn as bars (no font): "Family Board" is in the manifest; the logo only has to be recognisable
    x0, y = int(height * 1.18), int(height * 0.30)
    d.rounded_rectangle([x0, y, x0 + int(height * 1.9), y + int(height * 0.16)], radius=int(height * 0.08), fill=BOARD)
    d.rounded_rectangle([x0, y + int(height * 0.28), x0 + int(height * 1.4), y + int(height * 0.44)], radius=int(height * 0.08), fill=LINE)
    return img


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    icon(256).save(os.path.join(OUT, "icon.png"))
    icon(512).save(os.path.join(OUT, "icon@2x.png"))
    logo(972, 256).save(os.path.join(OUT, "logo.png"))
    logo(1944, 512).save(os.path.join(OUT, "logo@2x.png"))
    logo(972, 256).save(os.path.join(OUT, "dark_logo.png"))
    logo(1944, 512).save(os.path.join(OUT, "dark_logo@2x.png"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
