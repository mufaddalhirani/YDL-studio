"""Small formatting, error, and yt-dlp helpers shared across the app."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def human_size(size: float | int | None) -> str:
    if not size or size <= 0:
        return "0 B"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def human_duration(seconds: float | int | None) -> str:
    if not seconds or seconds <= 0:
        return "--:--"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def human_count(value: int | None) -> str:
    if value is None or value < 0:
        return ""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def cookie_options(browser: str, cookies_file: str) -> dict[str, Any]:
    """Build yt-dlp cookie options, preferring an explicit cookies.txt file."""

    file_text = (cookies_file or "").strip()
    if file_text:
        path = Path(file_text).expanduser()
        if not path.is_file():
            raise ValueError(f"Cookies file not found: {path}")
        return {"cookiefile": str(path)}

    browser_name = (browser or "").strip().lower()
    if browser_name and browser_name != "none":
        return {"cookiesfrombrowser": (browser_name,)}
    return {}


def friendly_ytdlp_error(error: object) -> str:
    message = strip_ansi(str(error)).strip()
    lower = message.lower()

    if "sign in to confirm" in lower or "not a bot" in lower:
        return (
            "The site asked for a signed-in session. In Settings > Cookies, choose your "
            "browser or load a cookies.txt file, then retry."
        )
    if "private video" in lower or "this video is private" in lower:
        return "This item is private. Sign in with cookies that have access to it."
    if "requested format is not available" in lower:
        return "That quality is not available for this URL. Try Best available, or choose MKV."
    if "video unavailable" in lower or "has been removed" in lower or "not available" in lower:
        return "This item is unavailable in your region, removed, or restricted."
    if "unsupported url" in lower or "no suitable extractor" in lower:
        return "This URL is not supported by yt-dlp."
    if "ffmpeg" in lower and ("not found" in lower or "not installed" in lower or "unable" in lower):
        return "FFmpeg is required for this task. Install it from Settings > FFmpeg."
    if "could not copy" in lower and "cookie" in lower:
        return (
            "Browser cookies could not be read. Close the browser completely and retry, "
            "or export a cookies.txt file and select it in Settings."
        )
    if "cookies" in lower and ("permission" in lower or "database" in lower or "locked" in lower):
        return (
            "The browser cookie database is locked. Close the browser and retry, "
            "or use a cookies.txt file instead."
        )
    if "http error 403" in lower:
        return "The site refused the request (403). Try browser cookies or a different format."
    if "http error 429" in lower or "too many requests" in lower:
        return "The site rate-limited this request. Wait a few minutes and retry."
    if "http error 404" in lower or "http error 410" in lower:
        # yt-dlp wraps this in "unable to download webpage", so it must be
        # matched before the generic connection advice below.
        return "That page or file no longer exists (404). Double-check the link."
    if "timed out" in lower or "timeout" in lower:
        return "The connection timed out. Check your network and retry."
    if "no space left" in lower or "disk is full" in lower:
        return "The destination drive is full. Choose another folder and retry."
    if "unable to download webpage" in lower or "connection" in lower:
        return "Could not reach the site. Check your network connection and retry."
    if len(message) > 600:
        return message[:597].rstrip() + "..."
    return message or "The download failed for an unknown reason."
