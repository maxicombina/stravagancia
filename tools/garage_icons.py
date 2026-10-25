"""Generate Garage's installable-app icons (deterministic, no network).

Run from the repository root:

    .venv/bin/python -I tools/garage_icons.py

Writes PNG and SVG files to garage/static/garage/icons/: a white chainring on
Garage cobalt. The maskable icon keeps the drawing inside the central safe zone.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "garage" / "static" / "garage" / "icons"
BLUE = (36, 80, 214, 255)
WHITE = (255, 255, 255, 255)
SCALE = 4
TEETH = 24


def chainring_polygon(cx, cy, radius):
    """Tooth outline as (x, y) points: flat root, sloped flank, flat tip."""
    inner = radius * 0.88
    step = 2 * math.pi / TEETH
    points = []
    for tooth in range(TEETH):
        base = tooth * step - math.pi / 2
        for fraction, r in ((0.0, inner), (0.30, inner), (0.42, radius), (0.78, radius), (0.90, inner)):
            angle = base + fraction * step
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def draw_glyph(draw, cx, cy, radius, ink, ground):
    draw.polygon(chainring_polygon(cx, cy, radius), fill=ink)
    draw.ellipse((cx - radius * 0.66, cy - radius * 0.66, cx + radius * 0.66, cy + radius * 0.66), fill=ground)
    width = max(1, round(radius * 0.13))
    for arm in range(5):
        angle = arm * 2 * math.pi / 5 - math.pi / 2
        end = (cx + radius * 0.7 * math.cos(angle), cy + radius * 0.7 * math.sin(angle))
        draw.line((cx, cy, *end), fill=ink, width=width)
    hub = radius * 0.24
    draw.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=ink)
    axle = radius * 0.09
    draw.ellipse((cx - axle, cy - axle, cx + axle, cy + axle), fill=ground)


def render(size, *, glyph, rounded):
    big = size * SCALE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if rounded:
        draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * 0.22), fill=BLUE)
    else:
        draw.rectangle((0, 0, big, big), fill=BLUE)
    draw_glyph(draw, big / 2, big / 2, big * glyph, WHITE, BLUE)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def svg(glyph=0.34):
    size = 512
    c = size / 2
    r = size * glyph
    tooth = " ".join(f"{x:.1f},{y:.1f}" for x, y in chainring_polygon(c, c, r))
    arms = "".join(
        f'<line x1="{c}" y1="{c}" x2="{c + r * 0.7 * math.cos(a * 2 * math.pi / 5 - math.pi / 2):.1f}" '
        f'y2="{c + r * 0.7 * math.sin(a * 2 * math.pi / 5 - math.pi / 2):.1f}"/>' for a in range(5))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
            f'<rect width="{size}" height="{size}" rx="{size * 0.22:.0f}" fill="#2450d6"/>'
            f'<polygon points="{tooth}" fill="#fff"/>'
            f'<circle cx="{c}" cy="{c}" r="{r * 0.66:.1f}" fill="#2450d6"/>'
            f'<g stroke="#fff" stroke-width="{r * 0.13:.1f}" stroke-linecap="round">{arms}</g>'
            f'<circle cx="{c}" cy="{c}" r="{r * 0.24:.1f}" fill="#fff"/>'
            f'<circle cx="{c}" cy="{c}" r="{r * 0.09:.1f}" fill="#2450d6"/></svg>\n')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "icon-192.png": render(192, glyph=0.34, rounded=True),
        "icon-512.png": render(512, glyph=0.34, rounded=True),
        "icon-maskable-512.png": render(512, glyph=0.28, rounded=False),
        "apple-touch-icon.png": render(180, glyph=0.32, rounded=False),
        "favicon-32.png": render(32, glyph=0.40, rounded=True),
    }
    for name, image in files.items():
        image.save(OUT / name, format="PNG", optimize=True)
    (OUT / "icon.svg").write_text(svg(), encoding="utf-8")
    for path in sorted(OUT.iterdir()):
        print(path.relative_to(OUT.parents[2]), path.stat().st_size)


if __name__ == "__main__":
    main()
