"""Validation and construction of yt-dlp options for one download job."""

from __future__ import annotations

import contextlib
import io
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from .config import (
    AUDIO_BITRATES,
    AUDIO_FORMATS,
    CONTAINERS,
    MODES,
    RESOLUTIONS,
    SPONSORBLOCK_MODES,
    SUBTITLE_MODES,
    AppSettings,
)
from .ffmpeg import FFmpegInfo
from .utils import cookie_options


class OptionsError(ValueError):
    pass


SPONSORBLOCK_CATEGORIES = frozenset(
    {
        "sponsor",
        "selfpromo",
        "interaction",
        "intro",
        "outro",
        "preview",
        "music_offtopic",
        "poi_highlight",
        "filler",
    }
)

_LOSSY_AUDIO = frozenset({"mp3", "m4a", "opus"})
_BLOCKED_CUSTOM_FLAGS = ("-h", "--help", "--version", "-U", "--update", "--update-to")


@dataclass(frozen=True)
class DownloadOptions:
    output_dir: str
    filename_template: str
    mode: str
    resolution: str
    container: str
    prefer_h264: bool
    audio_format: str
    audio_bitrate: str
    embed_metadata: bool
    embed_thumbnail: bool
    embed_chapters: bool
    subtitle_mode: str
    subtitle_languages: str
    include_auto_subs: bool
    sponsorblock_mode: str
    sponsorblock_categories: str
    playlist: bool
    playlist_items: str
    cookies_browser: str
    cookies_file: str
    rate_limit_mbps: str
    custom_args: str

    @classmethod
    def from_settings(cls, settings: AppSettings) -> DownloadOptions:
        return cls(
            output_dir=settings.download_dir,
            filename_template=settings.filename_template,
            mode=settings.mode,
            resolution=settings.resolution,
            container=settings.container,
            prefer_h264=settings.prefer_h264,
            audio_format=settings.audio_format,
            audio_bitrate=settings.audio_bitrate,
            embed_metadata=settings.embed_metadata,
            embed_thumbnail=settings.embed_thumbnail,
            embed_chapters=settings.embed_chapters,
            subtitle_mode=settings.subtitle_mode,
            subtitle_languages=settings.subtitle_languages,
            include_auto_subs=settings.include_auto_subs,
            sponsorblock_mode=settings.sponsorblock_mode,
            sponsorblock_categories=settings.sponsorblock_categories,
            playlist=settings.playlist,
            playlist_items=settings.playlist_items,
            cookies_browser=settings.cookies_browser,
            cookies_file=settings.cookies_file,
            rate_limit_mbps=settings.rate_limit_mbps,
            custom_args=settings.custom_args,
        )


def validate_filename_template(template: str) -> None:
    if not template.strip():
        raise OptionsError("The filename template cannot be empty.")
    if "%(ext)s" not in template:
        raise OptionsError(
            'The filename template must include "%(ext)s" so yt-dlp can add the file extension.'
        )
    if Path(template).is_absolute() or os.path.splitdrive(template)[0]:
        raise OptionsError(
            "The filename template must be relative to the output folder."
        )
    # pathlib treats "/name" as relative to the current drive on Windows, which
    # would let a template escape the chosen output folder.
    if template.startswith(("/", "\\")):
        raise OptionsError(
            "The filename template must be relative to the output folder."
        )
    if ".." in Path(template).parts:
        raise OptionsError('The filename template cannot contain "..".')


def _validate(options: DownloadOptions) -> None:
    if options.mode not in MODES:
        raise OptionsError(f"Unknown download mode: {options.mode}")
    if options.resolution not in RESOLUTIONS:
        raise OptionsError(f"Unknown resolution: {options.resolution}")
    if options.container not in CONTAINERS:
        raise OptionsError(f"Unknown container: {options.container}")
    if options.audio_format not in AUDIO_FORMATS:
        raise OptionsError(f"Unknown audio format: {options.audio_format}")
    if options.audio_bitrate not in AUDIO_BITRATES:
        raise OptionsError(f"Unknown audio bitrate: {options.audio_bitrate}")
    if options.subtitle_mode not in SUBTITLE_MODES:
        raise OptionsError(f"Unknown subtitle mode: {options.subtitle_mode}")
    if options.sponsorblock_mode not in SPONSORBLOCK_MODES:
        raise OptionsError(f"Unknown SponsorBlock mode: {options.sponsorblock_mode}")
    if not options.output_dir.strip():
        raise OptionsError("Choose an output folder first.")
    validate_filename_template(options.filename_template)
    if options.playlist_items and not re.fullmatch(r"[\d,\-:\s]+", options.playlist_items):
        raise OptionsError(
            'Playlist items must look like "1-5", "1,3,7", or "1:10".'
        )


def parse_custom_arguments(text: str) -> dict[str, Any]:
    """Return only the yt-dlp options explicitly changed by the user's arguments."""

    if not (text or "").strip():
        return {}
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as exc:
        raise OptionsError(f"Could not parse advanced arguments: {exc}") from exc
    if not tokens:
        return {}
    for token in tokens:
        if token.split("=", 1)[0] in _BLOCKED_CUSTOM_FLAGS:
            raise OptionsError(f"{token} cannot be used in advanced arguments.")

    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            baseline = yt_dlp.parse_options(["--ignore-config"]).ydl_opts
            parsed = yt_dlp.parse_options(["--ignore-config", *tokens]).ydl_opts
    except SystemExit as exc:
        raise OptionsError(
            "These advanced arguments are not supported here (help/version/update flags)."
        ) from exc
    except Exception as exc:
        detail = output.getvalue().strip().splitlines()
        message = detail[-1] if detail else str(exc)
        raise OptionsError(f"Invalid advanced arguments: {message}") from exc

    changed = {
        key: value
        for key, value in parsed.items()
        if key not in baseline or value != baseline[key]
    }
    changed.pop("postprocessors", None)
    return changed


def _merge_postprocessors(base: list[dict], extra: list[dict]) -> list[dict]:
    merged = [dict(item) for item in base]
    by_key = {item.get("key"): index for index, item in enumerate(merged)}

    for item in extra:
        key = item.get("key")
        if not key or key == "FFmpegConcat":
            continue
        if key == "FFmpegMetadata" and key in by_key:
            existing = merged[by_key[key]]
            for name, value in item.items():
                if name in ("add_metadata", "add_chapters") and isinstance(value, bool):
                    existing[name] = bool(existing.get(name)) or value
                else:
                    existing.setdefault(name, value)
            continue
        if key in by_key:
            if key in ("SponsorBlock", "ModifyChapters"):
                merged[by_key[key]] = item
            continue
        by_key[key] = len(merged)
        merged.append(item)
    return merged


def _resolution_suffix(resolution: str) -> str:
    return "" if resolution == "best" else f"[height<={resolution}]"


def _video_format(options: DownloadOptions, has_ffmpeg: bool) -> str:
    cap = _resolution_suffix(options.resolution)
    if not has_ffmpeg:
        return f"best{cap}/best"
    if options.container == "mp4" and options.prefer_h264:
        return (
            f"bv*{cap}[ext=mp4]+ba[ext=m4a]"
            f"/b{cap}[ext=mp4]"
            f"/bv*{cap}+ba"
            f"/b{cap}/b"
        )
    return f"bv*{cap}+ba/b{cap}/b"


def _audio_languages(languages: str) -> list[str]:
    values = [item.strip() for item in languages.split(",") if item.strip()]
    return values or ["en"]


def _sponsorblock_categories(text: str, warnings: list[str]) -> set[str]:
    values = {item.strip() for item in text.split(",") if item.strip()}
    valid = values & SPONSORBLOCK_CATEGORIES
    unknown = sorted(values - SPONSORBLOCK_CATEGORIES)
    if unknown:
        warnings.append("Ignoring unknown SponsorBlock categories: " + ", ".join(unknown))
    return valid


def build_ydl_options(
    options: DownloadOptions,
    *,
    ffmpeg_info: FFmpegInfo,
    progress_hook=None,
    postprocessor_hook=None,
    logger=None,
) -> tuple[dict[str, Any], list[str]]:
    _validate(options)
    warnings: list[str] = []
    has_ffmpeg = ffmpeg_info.found and bool(ffmpeg_info.path)

    output_dir = Path(options.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts: dict[str, Any] = {
        "outtmpl": str(output_dir / options.filename_template),
        "quiet": True,
        "noprogress": True,
        "no_warnings": False,
        "consoletitle": False,
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "continuedl": True,
        "overwrites": False,
        "updatetime": False,
        "windowsfilenames": os.name == "nt",
    }
    if logger is not None:
        ydl_opts["logger"] = logger
    if progress_hook is not None:
        ydl_opts["progress_hooks"] = [progress_hook]
    if postprocessor_hook is not None:
        ydl_opts["postprocessor_hooks"] = [postprocessor_hook]
    if has_ffmpeg:
        ydl_opts["ffmpeg_location"] = ffmpeg_info.path
        if not ffmpeg_info.has_ffprobe:
            warnings.append("ffprobe was not found next to ffmpeg; some metadata tasks may fail.")
    else:
        warnings.append(
            "FFmpeg was not found. Video downloads will use a single-file format and "
            "audio conversion is unavailable. Install FFmpeg from Settings."
        )

    try:
        ydl_opts.update(cookie_options(options.cookies_browser, options.cookies_file))
    except ValueError as exc:
        raise OptionsError(str(exc)) from exc

    playlist_enabled = options.playlist or bool(options.playlist_items)
    ydl_opts["noplaylist"] = not playlist_enabled
    if options.playlist_items:
        ydl_opts["playlist_items"] = options.playlist_items

    if options.rate_limit_mbps:
        try:
            rate = float(options.rate_limit_mbps)
        except ValueError as exc:
            raise OptionsError("The speed limit must be a number in MB/s.") from exc
        if rate <= 0:
            raise OptionsError("The speed limit must be greater than zero.")
        ydl_opts["ratelimit"] = int(rate * 1024 * 1024)

    postprocessors: list[dict[str, Any]] = []

    if options.mode == "audio":
        if not has_ffmpeg:
            raise OptionsError(
                "Audio conversion requires FFmpeg. Install it from Settings > FFmpeg."
            )
        ydl_opts["format"] = "bestaudio/best"
        extractor: dict[str, Any] = {
            "key": "FFmpegExtractAudio",
            "preferredcodec": options.audio_format,
        }
        if options.audio_format in _LOSSY_AUDIO:
            extractor["preferredquality"] = options.audio_bitrate
        postprocessors.append(extractor)
        if options.subtitle_mode != "off":
            warnings.append("Subtitles are only applied to video downloads.")
        if options.sponsorblock_mode != "off":
            warnings.append("SponsorBlock is only applied to video downloads.")
    else:
        ydl_opts["format"] = _video_format(options, has_ffmpeg)
        if has_ffmpeg:
            ydl_opts["merge_output_format"] = (
                "mp4/mkv" if options.container == "mp4" else "mkv"
            )
            if options.container == "mp4":
                warnings.append(
                    "MP4 is preferred; sources that cannot be placed in MP4 will fall back to MKV."
                )

    if options.mode == "video" and options.sponsorblock_mode != "off" and has_ffmpeg:
        categories = _sponsorblock_categories(options.sponsorblock_categories, warnings)
        if categories:
            postprocessors.append(
                {
                    "key": "SponsorBlock",
                    "categories": categories,
                    "api": "https://sponsor.ajay.app",
                    "when": "after_filter",
                }
            )
            postprocessors.append(
                {
                    "key": "ModifyChapters",
                    "remove_chapters_patterns": [],
                    "remove_sponsor_segments": (
                        categories if options.sponsorblock_mode == "remove" else set()
                    ),
                    "remove_ranges": [],
                    "sponsorblock_chapter_title": "[SponsorBlock]: %(category_names)l",
                    "force_keyframes": False,
                }
            )
    elif options.sponsorblock_mode != "off" and options.mode == "video":
        warnings.append("SponsorBlock needs FFmpeg and video mode; it was skipped.")

    if options.mode == "video" and options.subtitle_mode != "off":
        ydl_opts["writesubtitles"] = True
        ydl_opts["writeautomaticsub"] = options.include_auto_subs
        ydl_opts["subtitleslangs"] = _audio_languages(options.subtitle_languages)
        ydl_opts["subtitlesformat"] = "srt/best"
        if options.subtitle_mode == "embed":
            if has_ffmpeg:
                postprocessors.append(
                    {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False}
                )
            else:
                warnings.append(
                    "Subtitle embedding needs FFmpeg; subtitles will be saved as separate files."
                )

    mark_chapters = options.mode == "video" and options.sponsorblock_mode == "mark"
    add_metadata = options.embed_metadata or options.embed_chapters or mark_chapters
    if add_metadata:
        if has_ffmpeg:
            postprocessors.append(
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": options.embed_metadata,
                    "add_chapters": options.embed_chapters or mark_chapters,
                    "add_infojson": False,
                }
            )
        else:
            warnings.append("Metadata and chapter embedding require FFmpeg; they were skipped.")

    if options.embed_thumbnail:
        if has_ffmpeg:
            ydl_opts["writethumbnail"] = True
            postprocessors.append(
                {"key": "EmbedThumbnail", "already_have_thumbnail": False}
            )
        else:
            warnings.append("Thumbnail embedding requires FFmpeg; it was skipped.")

    if postprocessors:
        ydl_opts["postprocessors"] = postprocessors

    custom = parse_custom_arguments(options.custom_args)
    if custom:
        custom_postprocessors = custom.pop("postprocessors", [])
        overridden: list[str] = []
        for key, value in custom.items():
            if key in ydl_opts and ydl_opts[key] != value:
                overridden.append(key)
            ydl_opts[key] = value
        if custom_postprocessors:
            ydl_opts["postprocessors"] = _merge_postprocessors(
                ydl_opts.get("postprocessors", []), custom_postprocessors
            )
        if overridden:
            warnings.append("Advanced arguments override: " + ", ".join(sorted(overridden)))

    return ydl_opts, warnings
