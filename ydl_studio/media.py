"""URL normalization and lightweight media metadata probing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import yt_dlp

from .utils import cookie_options, friendly_ytdlp_error

_SEARCH_RE = re.compile(r"^ytsearch\d*:", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


class MediaProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    url: str
    title: str
    uploader: str = ""
    duration: int | None = None
    thumbnail: str = ""
    view_count: int | None = None
    is_playlist: bool = False
    entry_count: int | None = None
    live_status: str = ""
    extractor: str = ""

    @property
    def playlist_label(self) -> str:
        if not self.is_playlist:
            return ""
        if self.entry_count:
            return f"Playlist - {self.entry_count} items"
        return "Playlist"


def normalize_url(raw: str) -> str | None:
    text = (raw or "").strip().strip("<>\"'")
    if not text or len(text) > 4096:
        return None

    # A search query is the one accepted input that may contain spaces, so it is
    # checked before the whitespace rule that protects every other form.
    if _SEARCH_RE.match(text):
        query = text.split(":", 1)[1].strip()
        return text if query and "\n" not in text else None

    if any(char.isspace() for char in text):
        return None

    if _SCHEME_RE.match(text):
        parsed = urlsplit(text)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return None
        return text

    candidate = "https:" + text if text.startswith("//") else "https://" + text
    parsed = urlsplit(candidate)
    hostname = (parsed.hostname or "").lower()
    valid_host = (
        "." in hostname
        or hostname == "localhost"
        or bool(_IPV4_RE.fullmatch(hostname))
    )
    if parsed.scheme != "https" or not parsed.netloc or not valid_host:
        return None
    return candidate


def parse_urls(text: str) -> tuple[list[str], list[str]]:
    """Return (valid normalized URLs, rejected tokens) while preserving order.

    Input is read line by line because a ``ytsearch:`` query may contain spaces;
    several links separated by whitespace on one line are still split apart.
    """

    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        tokens = [line] if _SEARCH_RE.match(line) else line.split()
        for token in tokens:
            normalized = normalize_url(token)
            if not normalized:
                invalid.append(token)
                continue
            if normalized not in seen:
                seen.add(normalized)
                valid.append(normalized)
    return valid, invalid


def _thumbnail_for(info: dict) -> str:
    thumbnail = info.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail:
        return thumbnail
    thumbnails = info.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    entries = info.get("entries")
    if isinstance(entries, list) and entries and isinstance(entries[0], dict):
        return _thumbnail_for(entries[0])
    return ""


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def probe_media(
    url: str,
    *,
    cookies_browser: str = "None",
    cookies_file: str = "",
    socket_timeout: int = 20,
) -> MediaInfo:
    normalized = normalize_url(url)
    if not normalized:
        raise MediaProbeError("Enter a valid http(s) URL.")

    options: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "socket_timeout": socket_timeout,
        "retries": 2,
        "extractor_retries": 1,
        "noplaylist": False,
    }
    try:
        options.update(cookie_options(cookies_browser, cookies_file))
    except ValueError as exc:
        raise MediaProbeError(str(exc)) from exc

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(normalized, download=False)
    except Exception as exc:
        raise MediaProbeError(friendly_ytdlp_error(exc)) from exc

    if not isinstance(info, dict):
        raise MediaProbeError("The site did not return any media information.")

    entries = info.get("entries")
    is_playlist = info.get("_type") == "playlist" or entries is not None
    entry_count = _int_or_none(info.get("n_entries") or info.get("playlist_count"))
    if entry_count is None and isinstance(entries, list):
        entry_count = len(entries)

    title = str(info.get("title") or info.get("id") or normalized)
    uploader = str(
        info.get("uploader")
        or info.get("channel")
        or info.get("uploader_id")
        or ""
    )
    return MediaInfo(
        url=str(info.get("webpage_url") or normalized),
        title=title,
        uploader=uploader,
        duration=_int_or_none(info.get("duration")),
        thumbnail=_thumbnail_for(info),
        view_count=_int_or_none(info.get("view_count")),
        is_playlist=is_playlist,
        entry_count=entry_count,
        live_status=str(info.get("live_status") or ""),
        extractor=str(info.get("extractor_key") or info.get("extractor") or ""),
    )
