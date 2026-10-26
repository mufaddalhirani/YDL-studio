"""Generate the YDL Studio app icon (PNG and multi-size ICO).

Run from the project root:
    python scripts/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 2048
OUTPUT = Path(__file__).resolve().parent.parent / "ydl_studio" / "assets"


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (1, size))
    for y in range(size):
        ratio = y / max(1, size - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        image.putpixel((0, y), color)
    return image.resize((size, size), Image.Resampling.BILINEAR)


def _rounded_mask(size: int, margin: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=radius,
        fill=255,
    )
    return mask


def build_icon(size: int = SIZE) -> Image.Image:
    scale = size / 1024
    margin = round(34 * scale)
    radius = round(230 * scale)

    background = _vertical_gradient(size, (61, 130, 246), (29, 64, 175))
    mask = _rounded_mask(size, margin, radius)
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.paste(background.convert("RGBA"), (0, 0), mask)

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (
            round(-180 * scale),
            round(-260 * scale),
            round(760 * scale),
            round(640 * scale),
        ),
        fill=(255, 255, 255, 26),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(round(140 * scale)))
    icon = Image.alpha_composite(icon, Image.composite(glow, Image.new("RGBA", icon.size, (0, 0, 0, 0)), mask))

    shade = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    shade_draw.ellipse(
        (
            round(250 * scale),
            round(880 * scale),
            round(1400 * scale),
            round(1300 * scale),
        ),
        fill=(6, 20, 58, 60),
    )
    shade = shade.filter(ImageFilter.GaussianBlur(round(120 * scale)))
    icon = Image.alpha_composite(icon, Image.composite(shade, Image.new("RGBA", icon.size, (0, 0, 0, 0)), mask))

    glyph = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glyph)
    white = (255, 255, 255, 255)

    draw.polygon(
        [
            (round(392 * scale), round(292 * scale)),
            (round(392 * scale), round(590 * scale)),
            (round(668 * scale), round(441 * scale)),
        ],
        fill=white,
    )

    stroke = round(46 * scale)
    draw.line(
        [(round(530 * scale), round(650 * scale)), (round(530 * scale), round(770 * scale))],
        fill=white,
        width=stroke,
    )
    draw.line(
        [
            (round(454 * scale), round(704 * scale)),
            (round(530 * scale), round(780 * scale)),
            (round(606 * scale), round(704 * scale)),
        ],
        fill=white,
        width=stroke,
        joint="curve",
    )
    draw.line(
        [(round(378 * scale), round(868 * scale)), (round(646 * scale), round(868 * scale))],
        fill=white,
        width=stroke,
    )

    glyph_shadow = glyph.filter(ImageFilter.GaussianBlur(round(18 * scale)))
    shadow_tint = Image.new("RGBA", glyph.size, (0, 0, 0, 0))
    shadow_tint.paste((8, 24, 64, 90), (0, round(14 * scale)), glyph_shadow.getchannel("A"))
    icon = Image.alpha_composite(icon, shadow_tint)
    icon = Image.alpha_composite(icon, glyph)

    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(highlight)
    inset = margin + round(3 * scale)
    highlight_draw.rounded_rectangle(
        (inset, inset, size - inset, size - inset),
        radius=radius,
        outline=(255, 255, 255, 34),
        width=round(4 * scale),
    )
    icon = Image.alpha_composite(icon, highlight)
    return icon


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    base = build_icon()
    png = base.resize((1024, 1024), Image.Resampling.LANCZOS)
    png.save(OUTPUT / "icon.png", optimize=True)

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(OUTPUT / "icon.ico", format="ICO", sizes=ico_sizes)

    print(f"Wrote {OUTPUT / 'icon.png'}")
    print(f"Wrote {OUTPUT / 'icon.ico'}")


if __name__ == "__main__":
    main()
