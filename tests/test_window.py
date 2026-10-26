"""Window sizing across the desktop sizes Windows actually reports.

The numbers below are what ``winfo_screenwidth()`` returns, which is the
physical resolution divided by the display scaling factor — the same units
CustomTkinter's ``geometry()`` and ``minsize()`` take.
"""

from __future__ import annotations

import pytest

from ydl_studio.app import plan_window

# (label, reported width, reported height)
SCREENS = [
    ("1080p at 100%", 1920, 1080),
    ("1080p at 125%", 1536, 864),
    ("1080p at 150%", 1280, 720),
    ("1080p at 200%", 960, 540),
    ("720p at 100%", 1280, 720),
    ("laptop 1366x768 at 125%", 1093, 614),
    ("laptop 1280x800 at 150%", 853, 533),
    ("4K at 150%", 2560, 1440),
    ("4K at 200%", 1920, 1080),
    ("netbook 1024x600", 1024, 600),
    ("projector 800x600", 800, 600),
    ("Surface 2880x1920 at 250%", 1152, 768),
]


@pytest.mark.parametrize(("label", "sw", "sh"), SCREENS)
def test_the_window_fits_the_desktop(label, sw, sh) -> None:
    width, height, *_rest = plan_window(sw, sh)
    assert width <= sw, f"{label}: {width}px wide on a {sw}px desktop"
    assert height <= sh, f"{label}: {height}px tall on a {sh}px desktop"


@pytest.mark.parametrize(("label", "sw", "sh"), SCREENS)
def test_the_minimum_size_never_exceeds_the_desktop(label, sw, sh) -> None:
    # A fixed floor is the failure mode here: Windows reserves part of the
    # height for the taskbar, and a minimum taller than the desktop strands the
    # title bar out of reach.
    *_, min_width, min_height = plan_window(sw, sh)
    assert min_width <= sw
    assert min_height <= sh


@pytest.mark.parametrize(("label", "sw", "sh"), SCREENS)
def test_the_whole_window_lands_on_screen(label, sw, sh) -> None:
    width, height, x, y, min_width, min_height = plan_window(sw, sh)
    assert x >= 0 and y >= 0
    assert x + width <= sw
    assert y + height <= sh
    assert min_width <= width
    assert min_height <= height


def test_a_desktop_gets_the_comfortable_size() -> None:
    assert plan_window(1920, 1080)[:2] == (1200, 820)


def test_the_window_stays_centred() -> None:
    width, height, x, y, *_ = plan_window(1920, 1080)
    assert x == (1920 - width) // 2
    assert y == (1080 - height) // 2 - 20


def test_a_small_screen_keeps_the_sidebar_and_content_readable() -> None:
    width, height, *_rest = plan_window(1024, 600)
    assert width >= 620, "the sidebar is 228 wide; anything less crowds the composer"
    assert height <= 600


def test_an_absurd_desktop_still_returns_a_window() -> None:
    width, height, x, y, min_width, min_height = plan_window(400, 300)
    assert (width, height) == (340, 280)
    assert (x, y) == (30, 0), "the offset clamps to the top-left rather than going negative"
    assert min_width <= width and min_height <= height
