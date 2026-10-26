"""Render docs/images/banner.png — the wordmark banner used on the GitHub page."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "ydl_studio" / "assets" / "icon.png"
OUTPUT = ROOT / "docs" / "images" / "banner.png"

WIDTH = 1600
HEIGHT = 380
TOP = (13, 16, 23)
BOTTOM = (21, 26, 35)
ACCENT = (59, 130, 246)
TEXT = (232, 237, 246)
MUTED = (151, 163, 182)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "segoeuib" if bold else "segoeui"
    for candidate in (
        Path("C:/Windows/Fonts") / f"{name}.ttf",
        Path("/usr/share/fonts/truetype/dejavu") / "DejaVuSans.ttf",
    ):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size)


def paint_background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), TOP)
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / (HEIGHT - 1)
        color = tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * ratio) for i in range(3))
        draw.line((0, y, WIDTH, y), fill=color)

    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [WIDTH - 720, -260, WIDTH + 260, 620],
        fill=(37, 99, 235, 70),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    image = Image.alpha_composite(image.convert("RGBA"), glow)

    hairline = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(hairline).line(
        [(0, HEIGHT - 2), (WIDTH, HEIGHT - 2)], fill=(*ACCENT, 130), width=2
    )
    return Image.alpha_composite(image, hairline)


def build_banner() -> Image.Image:
    canvas = paint_background()
    draw = ImageDraw.Draw(canvas)

    icon_size = 190
    icon = Image.open(ICON).convert("RGBA").resize(
        (icon_size, icon_size), Image.Resampling.LANCZOS
    )
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [70, 105, 70 + icon_size, 105 + icon_size],
        radius=44,
        fill=(0, 0, 0, 110),
    )
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(18)))
    canvas.alpha_composite(icon, (66, 92))
    draw = ImageDraw.Draw(canvas)

    title_font = load_font(84, bold=True)
    tag_font = load_font(30)
    chip_font = load_font(22, bold=True)
    left = 70 + icon_size + 56

    draw.text((left, 84), "YDL Studio", font=title_font, fill=TEXT)
    draw.text(
        (left + 3, 196),
        "A calm desktop front end for yt-dlp and FFmpeg.",
        font=tag_font,
        fill=MUTED,
    )

    chip_text = "WINDOWS  ·  QUEUE  ·  PLAYLISTS  ·  SUBTITLES  ·  SPONSORBLOCK"
    chip = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    chip_draw = ImageDraw.Draw(chip)
    chip_box = chip_draw.textbbox((left, 258), chip_text, font=chip_font)
    chip_draw.rounded_rectangle(
        [chip_box[0] - 20, chip_box[1] - 13, chip_box[2] + 20, chip_box[3] + 13],
        radius=999,
        fill=(59, 130, 246, 34),
        outline=(96, 165, 250, 90),
        width=1,
    )
    chip_draw.text((left, 258), chip_text, font=chip_font, fill=(147, 197, 253))
    canvas = Image.alpha_composite(canvas, chip)
    return canvas.convert("RGB")


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    build_banner().save(OUTPUT, optimize=True)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
