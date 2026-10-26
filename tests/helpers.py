"""Builders and constants shared by the test modules."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ydl_studio.config import AppSettings
from ydl_studio.ffmpeg import FFmpegInfo
from ydl_studio.options import DownloadOptions

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE_MP4 = FIXTURES / "sample.mp4"

NO_FFMPEG = FFmpegInfo(found=False)
WITH_FFMPEG = FFmpegInfo(
    found=True,
    path=str(Path(tempfile.gettempdir()) / "ffmpeg.exe"),
    version="ffmpeg version 7.1-full_build-www.gyan.dev",
    ffprobe_path=str(Path(tempfile.gettempdir()) / "ffprobe.exe"),
    source="test",
)


def make_options(**overrides) -> DownloadOptions:
    values = {
        "output_dir": tempfile.gettempdir(),
        "filename_template": "%(title)s [%(id)s].%(ext)s",
        "mode": "video",
        "resolution": "best",
        "container": "mp4",
        "prefer_h264": True,
        "audio_format": "mp3",
        "audio_bitrate": "320",
        "embed_metadata": True,
        "embed_thumbnail": True,
        "embed_chapters": True,
        "subtitle_mode": "off",
        "subtitle_languages": "en",
        "include_auto_subs": False,
        "sponsorblock_mode": "off",
        "sponsorblock_categories": "sponsor,selfpromo",
        "playlist": False,
        "playlist_items": "",
        "cookies_browser": "None",
        "cookies_file": "",
        "rate_limit_mbps": "",
        "custom_args": "",
    }
    values.update(overrides)
    return DownloadOptions(**values)


def make_settings(**overrides) -> AppSettings:
    values = {"download_dir": tempfile.gettempdir()}
    values.update(overrides)
    return AppSettings(**values)
