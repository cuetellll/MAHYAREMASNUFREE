"""Generate the MahyarFree application icon (PNG + multi-size ICO).

    python3 tools/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 512
OUT_DIR = Path(__file__).resolve().parent.parent / "mahyarfree" / "ui" / "assets" / "img"

CYAN = (0, 240, 255)
MAGENTA = (255, 47, 214)
VIOLET = (139, 92, 255)
LIME = (125, 255, 90)


def shield_points(cx: float, cy: float, w: float, h: float) -> list[tuple[float, float]]:
    """A rounded heraldic shield outline."""
    hw = w / 2
    hh = h / 2
    top = cy - hh
    bottom = cy + hh
    left = cx - hw
    right = cx + hw
    radius = w * 0.20
    shoulder = cy + hh * 0.16
    steps = 46

    def quad(p0, p1, p2, t):
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        return (x, y)

    points: list[tuple[float, float]] = []

    # rounded top-left corner
    for i in range(10):
        angle = math.pi + (math.pi / 2) * (i / 9)
        points.append((left + radius + math.cos(angle) * radius, top + radius + math.sin(angle) * radius))
    # top edge
    points.append((right - radius, top))
    # rounded top-right corner
    for i in range(10):
        angle = -math.pi / 2 + (math.pi / 2) * (i / 9)
        points.append((right - radius + math.cos(angle) * radius, top + radius + math.sin(angle) * radius))
    # right side down to the shoulder
    for i in range(6):
        t = i / 5
        points.append((right, top + radius + (shoulder - top - radius) * t))
    # curve into the bottom tip
    for i in range(steps):
        t = i / steps
        points.append(quad((right, shoulder), (right - w * 0.10, bottom - h * 0.14), (cx, bottom), t))
    # mirrored back up the left side
    for i in range(steps, -1, -1):
        t = i / steps
        points.append(quad((left, shoulder), (left + w * 0.10, bottom - h * 0.14), (cx, bottom), t))
    for i in range(5, -1, -1):
        t = i / 5
        points.append((left, top + radius + (shoulder - top - radius) * t))
    return points


def bolt_points(cx: float, cy: float, scale: float) -> list[tuple[float, float]]:
    shape = [
        (0.16, -0.50), (-0.20, 0.04), (0.02, 0.04),
        (-0.14, 0.50), (0.22, -0.06), (-0.01, -0.06),
    ]
    return [(cx + x * scale, cy + y * scale) for x, y in shape]


def build() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)

    cx = cy = SIZE / 2
    points = shield_points(cx, cy, SIZE * 0.62, SIZE * 0.72)

    gd.polygon(points, fill=(*CYAN, 190))
    glow = glow.filter(ImageFilter.GaussianBlur(38))

    draw = ImageDraw.Draw(image)
    draw.bitmap((0, 0), glow, fill=None)

    # dark glass body
    body = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    bd.polygon(points, fill=(9, 14, 30, 255))
    image = Image.alpha_composite(image, body)
    draw = ImageDraw.Draw(image)

    # neon rim, drawn as a soft double stroke
    rim = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rd.line(points + [points[0]], fill=(*CYAN, 255), width=9, joint="curve")
    rim_glow = rim.filter(ImageFilter.GaussianBlur(16))
    image = Image.alpha_composite(image, rim_glow)
    image = Image.alpha_composite(image, rim)
    draw = ImageDraw.Draw(image)

    # inner gradient wash
    wash = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wash)
    for i in range(120):
        t = i / 119
        radius = SIZE * 0.30 * (1 - t)
        alpha = int(46 * (1 - t) ** 1.6)
        color = (
            int(CYAN[0] * (1 - t) + VIOLET[0] * t),
            int(CYAN[1] * (1 - t) + VIOLET[1] * t),
            int(CYAN[2] * (1 - t) + VIOLET[2] * t),
            alpha,
        )
        wd.ellipse([cx - radius, cy - radius * 0.9, cx + radius, cy + radius * 0.9], fill=color)
    wash = wash.filter(ImageFilter.GaussianBlur(20))
    image = Image.alpha_composite(image, wash)
    draw = ImageDraw.Draw(image)

    # lightning bolt
    bolt = bolt_points(cx, cy + SIZE * 0.01, SIZE * 0.62)
    bolt_glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(bolt_glow).polygon(bolt, fill=(*LIME, 230))
    image = Image.alpha_composite(image, bolt_glow.filter(ImageFilter.GaussianBlur(26)))
    draw = ImageDraw.Draw(image)
    draw.polygon(bolt, fill=(*LIME, 255))

    inner = bolt_points(cx, cy + SIZE * 0.01, SIZE * 0.62)
    shrunk = [(cx + (x - cx) * 0.72, cy + (y - cy) * 0.72) for x, y in inner]
    draw.polygon(shrunk, fill=(255, 255, 255, 235))

    return image


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icon = build()
    png = OUT_DIR / "icon.png"
    icon.save(png)
    print("wrote", png)

    ico = OUT_DIR / "icon.ico"
    icon.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", ico)


if __name__ == "__main__":
    main()
