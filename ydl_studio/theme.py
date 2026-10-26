"""Theme tokens, fonts, icons, and cross-platform file opening."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageOps

Color = str | tuple[str, str]

BG: Color = ("#f3f5fa", "#0d1017")
PANEL: Color = ("#ffffff", "#151a23")
PANEL_ALT: Color = ("#f7f9fc", "#1a202b")
PANEL_SOFT: Color = ("#eef2f8", "#11151d")
BORDER: Color = ("#d9e0ec", "#283040")
TEXT: Color = ("#0f172a", "#e8edf6")
MUTED: Color = ("#5c6779", "#97a3b6")
SUBTLE: Color = ("#7c8799", "#6f7b90")
ACCENT: Color = ("#2563eb", "#3b82f6")
ACCENT_HOVER: Color = ("#1d4ed8", "#2563eb")
ACCENT_SOFT: Color = ("#dbeafe", "#12243f")
ACCENT_TEXT: Color = ("#1d4ed8", "#60a5fa")
SUCCESS: Color = ("#16a34a", "#22c55e")
SUCCESS_HOVER: Color = ("#15803d", "#16a34a")
SUCCESS_SOFT: Color = ("#dcfce7", "#14351f")
SUCCESS_TEXT: Color = ("#166534", "#4ade80")
DANGER: Color = ("#dc2626", "#ef4444")
DANGER_HOVER: Color = ("#b91c1c", "#dc2626")
DANGER_SOFT: Color = ("#fee2e2", "#3a1616")
DANGER_TEXT: Color = ("#b91c1c", "#f87171")
WARNING: Color = ("#d97706", "#f59e0b")
WARNING_SOFT: Color = ("#fef3c7", "#3a2e12")
WARNING_TEXT: Color = ("#b45309", "#fbbf24")
NEUTRAL_CHIP: Color = ("#e5e7eb", "#1f2733")

FONT_FAMILY = (
    "Segoe UI"
    if os.name == "nt"
    else ("Helvetica Neue" if sys.platform == "darwin" else "DejaVu Sans")
)
MONO_FAMILY = (
    "Consolas"
    if os.name == "nt"
    else ("Menlo" if sys.platform == "darwin" else "DejaVu Sans Mono")
)


def font(size: int = 12, weight: str = "normal", *, mono: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO_FAMILY if mono else FONT_FAMILY, size=size, weight=weight)


def resolve(color: Color) -> str:
    """Return the concrete color for plain Tk widgets that do not accept tuples."""

    if isinstance(color, tuple):
        return color[1] if ctk.get_appearance_mode().lower() == "dark" else color[0]
    return color


def _draw_nav_icon(kind: str, color: str, size: int = 18) -> Image.Image:
    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    unit = canvas / 24
    width = max(2, round(1.7 * unit))

    def point(x: float, y: float) -> tuple[float, float]:
        return (x * unit, y * unit)

    def line(*coords: float) -> None:
        draw.line([point(coords[index], coords[index + 1]) for index in range(0, len(coords), 2)],
                  fill=color, width=width, joint="curve")

    if kind == "download":
        line(12, 3.5, 12, 15)
        line(7, 10, 12, 15, 17, 10)
        line(5, 20, 19, 20)
    elif kind == "history":
        draw.ellipse(
            [point(4, 4), point(20, 20)],
            outline=color,
            width=width,
        )
        line(12, 8, 12, 12.5, 15.5, 14.5)
    elif kind == "console":
        draw.rounded_rectangle(
            [point(3, 5), point(21, 19)],
            radius=round(3 * unit),
            outline=color,
            width=width,
        )
        line(8, 9.5, 11, 12, 8, 14.5)
        line(13, 14.5, 17, 14.5)
    elif kind == "settings":
        for y, knob in ((6, 15), (12, 9), (18, 17)):
            line(4, y, 20, y)
            draw.ellipse(
                [point(knob - 2.2, y - 2.2), point(knob + 2.2, y + 2.2)],
                fill=color,
            )

    return image.resize((size, size), Image.Resampling.LANCZOS)


def nav_icon(kind: str, *, active: bool = False, size: int = 18) -> ctk.CTkImage:
    palette = ACCENT_TEXT if active else MUTED
    return ctk.CTkImage(
        light_image=_draw_nav_icon(kind, palette[0], size),
        dark_image=_draw_nav_icon(kind, palette[1], size),
        size=(size, size),
    )


def resource_path(*parts: str) -> Path:
    return Path(__file__).resolve().parent.joinpath(*parts)


def load_icon(size: int | None = None) -> Image.Image:
    path = resource_path("assets", "icon.png")
    if path.is_file():
        try:
            image = Image.open(path).convert("RGBA")
            if size:
                image = ImageOps.contain(image, (size, size), Image.Resampling.LANCZOS)
            return image
        except OSError:
            pass
    return _fallback_icon(size or 64)


def _fallback_icon(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(2, size // 12)
    radius = max(6, size // 5)
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=radius,
        fill=(37, 99, 235, 255),
    )
    triangle = [
        (size * 0.36, size * 0.28),
        (size * 0.36, size * 0.62),
        (size * 0.62, size * 0.45),
    ]
    draw.polygon(triangle, fill=(255, 255, 255, 255))
    stroke = max(2, size // 18)
    draw.line(
        [(size * 0.5, size * 0.56), (size * 0.5, size * 0.76)],
        fill=(255, 255, 255, 255),
        width=stroke,
    )
    draw.line(
        [
            (size * 0.40, size * 0.68),
            (size * 0.50, size * 0.78),
            (size * 0.60, size * 0.68),
        ],
        fill=(255, 255, 255, 255),
        width=stroke,
    )
    return image


def apply_window_icon(window: tk.Misc) -> None:
    ico = resource_path("assets", "icon.ico")
    if os.name == "nt" and ico.is_file():
        try:
            window.iconbitmap(str(ico))
        except tk.TclError:
            pass
    png = resource_path("assets", "icon.png")
    if png.is_file():
        try:
            photo = tk.PhotoImage(file=str(png))
            window.iconphoto(True, photo)
            window._ydl_icon_photo = photo  # type: ignore[attr-defined]
        except tk.TclError:
            pass


def open_path(path: str | Path) -> None:
    target = str(path)
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def reveal_path(path: str | Path) -> None:
    target = Path(path)
    if not target.exists():
        parent = target.parent
        if parent.exists():
            open_path(parent)
        return
    if os.name == "nt":
        if target.is_file():
            subprocess.Popen(["explorer", f"/select,{target}"])
        else:
            open_path(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
    else:
        open_path(target.parent if target.is_file() else target)


def open_url(url: str) -> None:
    webbrowser.open(url, new=2)
