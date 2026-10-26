"""Formatting helpers, cookie options and yt-dlp error translation."""

from __future__ import annotations

import pytest

from ydl_studio.utils import (
    cookie_options,
    friendly_ytdlp_error,
    human_count,
    human_duration,
    human_size,
    strip_ansi,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "0 B"),
        (0, "0 B"),
        (-5, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024**2, "1.0 MB"),
        (1024**3, "1.0 GB"),
        (1024**4, "1.0 TB"),
        (1024**5, "1024.0 TB"),
    ],
)
def test_human_size(value, expected: str) -> None:
    assert human_size(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "--:--"),
        (0, "--:--"),
        (-1, "--:--"),
        (5, "00:05"),
        (95, "01:35"),
        (3600, "1:00:00"),
        (7384, "2:03:04"),
    ],
)
def test_human_duration(value, expected: str) -> None:
    assert human_duration(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (-1, ""),
        (0, "0"),
        (999, "999"),
        (1000, "1.0K"),
        (12_500, "12.5K"),
        (2_400_000, "2.4M"),
        (1_500_000_000, "1.5B"),
    ],
)
def test_human_count(value, expected: str) -> None:
    assert human_count(value) == expected


def test_strip_ansi_removes_colour_and_progress_escapes() -> None:
    raw = "\x1b[0;31mERROR\x1b[0m \x1b[1A\x1b[Kdone"
    assert strip_ansi(raw) == "ERROR done"


def test_cookie_options_prefers_file(tmp_path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n")
    assert cookie_options("chrome", str(path)) == {"cookiefile": str(path)}


def test_cookie_options_reads_missing_file_as_error(tmp_path) -> None:
    with pytest.raises(ValueError, match="Cookies file not found"):
        cookie_options("None", str(tmp_path / "absent.txt"))


def test_cookie_options_accepts_existing_file(tmp_path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n")
    assert cookie_options("chrome", str(path)) == {"cookiefile": str(path)}


@pytest.mark.parametrize(
    ("browser", "expected"),
    [
        ("Chrome", {"cookiesfrombrowser": ("chrome",)}),
        ("  edge ", {"cookiesfrombrowser": ("edge",)}),
        ("None", {}),
        ("", {}),
    ],
)
def test_cookie_options_browser(browser: str, expected: dict) -> None:
    assert cookie_options(browser, "") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ERROR: [youtube] Sign in to confirm you're not a bot", "signed-in session"),
        ("Requested format is not available", "quality is not available"),
        ("ffmpeg not found", "FFmpeg is required"),
        ("HTTP Error 403: Forbidden", "refused the request (403)"),
        ("HTTP Error 429: Too Many Requests", "rate-limited"),
        ("HTTP Error 404: File not found", "no longer exists (404)"),
        ("Unsupported URL: https://example.com/x", "not supported by yt-dlp"),
        ("No space left on device", "destination drive is full"),
        ("Unable to download webpage: connection refused", "Could not reach the site"),
        ("", "download failed for an unknown reason"),
    ],
)
def test_friendly_ytdlp_error(raw: str, expected: str) -> None:
    assert expected in friendly_ytdlp_error(raw)


def test_a_wrapped_404_is_not_reported_as_a_network_problem() -> None:
    # This is the exact string yt-dlp raises, and it also contains
    # "unable to download webpage", so the 404 advice has to win.
    raw = (
        "ERROR: [generic] nope: Unable to download webpage: "
        "HTTP Error 404: File not found (caused by <HTTPError 404: File not found>)"
    )
    assert "404" in friendly_ytdlp_error(raw)


def test_friendly_ytdlp_error_trims_very_long_messages() -> None:
    message = friendly_ytdlp_error("x" * 5000)
    assert len(message) <= 600
    assert message.endswith("...")


def test_friendly_ytdlp_error_strips_ansi() -> None:
    assert friendly_ytdlp_error("\x1b[31mERROR: Video unavailable\x1b[0m") == (
        "This item is unavailable in your region, removed, or restricted."
    )


def test_format_error_is_not_reported_as_missing_video() -> None:
    # Both messages contain "not available"; the specific one has to win.
    assert friendly_ytdlp_error("ERROR: Requested format is not available") != (
        friendly_ytdlp_error("ERROR: Video unavailable")
    )
