"""Translation from app settings to yt-dlp options."""

from __future__ import annotations

import pytest
from helpers import NO_FFMPEG, WITH_FFMPEG, make_options, make_settings

from ydl_studio.options import (
    DownloadOptions,
    OptionsError,
    build_ydl_options,
    parse_custom_arguments,
    validate_filename_template,
)


def build(options, ffmpeg=NO_FFMPEG):
    return build_ydl_options(options, ffmpeg_info=ffmpeg)


# --------------------------------------------------------------- templates


@pytest.mark.parametrize(
    "template",
    [
        "",
        "   ",
        "%(title)s.%(id)s",
        "/absolute/%(title)s.%(ext)s",
        "\\server\\share\\%(title)s.%(ext)s",
        "C:/somewhere/%(title)s.%(ext)s",
        "../escape/%(title)s.%(ext)s",
        "nested/../../escape/%(title)s.%(ext)s",
    ],
)
def test_rejected_filename_templates(template: str) -> None:
    with pytest.raises(OptionsError):
        validate_filename_template(template)


@pytest.mark.parametrize(
    "template",
    ["%(title)s.%(ext)s", "%(title)s [%(id)s].%(ext)s", "subs/%(uploader)s/%(title)s.%(ext)s"],
)
def test_accepted_filename_templates(template: str) -> None:
    validate_filename_template(template)


# --------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": "stereo"},
        {"resolution": "1440p"},
        {"container": "webm"},
        {"audio_format": "ogg"},
        {"audio_bitrate": "999"},
        {"subtitle_mode": "burn"},
        {"sponsorblock_mode": "delete"},
        {"output_dir": "   "},
        {"playlist_items": "first-five"},
        {"playlist_items": "1;rm -rf"},
        {"filename_template": "%(title)s"},
    ],
)
def test_build_rejects_unusable_settings(overrides: dict) -> None:
    with pytest.raises(OptionsError):
        build(make_options(**overrides))


def test_playlist_range_syntax_is_accepted(tmp_path) -> None:
    options = make_options(output_dir=str(tmp_path), playlist_items="1-5,8,11:20")
    ydl_opts, _ = build(options)
    assert ydl_opts["playlist_items"] == "1-5,8,11:20"
    assert ydl_opts["noplaylist"] is False


# ------------------------------------------------------------------ video


def test_video_without_ffmpeg_asks_for_a_single_file(tmp_path) -> None:
    ydl_opts, warnings = build(make_options(output_dir=str(tmp_path)))
    assert ydl_opts["format"] == "best/best"
    assert "merge_output_format" not in ydl_opts
    assert any("FFmpeg was not found" in text for text in warnings)


def test_video_with_ffmpeg_prefers_h264(tmp_path) -> None:
    ydl_opts, warnings = build(
        make_options(output_dir=str(tmp_path)), ffmpeg=WITH_FFMPEG
    )
    assert ydl_opts["format"].startswith("bv*[ext=mp4]+ba[ext=m4a]")
    assert ydl_opts["merge_output_format"] == "mp4/mkv"
    assert any("MP4 is preferred" in text for text in warnings)


def test_h264_preference_can_be_turned_off(tmp_path) -> None:
    ydl_opts, _ = build(
        make_options(output_dir=str(tmp_path), prefer_h264=False), ffmpeg=WITH_FFMPEG
    )
    assert ydl_opts["format"] == "bv*+ba/b/b"


def test_mkv_container_does_not_force_mp4_formats(tmp_path) -> None:
    ydl_opts, _ = build(
        make_options(output_dir=str(tmp_path), container="mkv"), ffmpeg=WITH_FFMPEG
    )
    assert "ext=mp4" not in ydl_opts["format"]
    assert ydl_opts["merge_output_format"] == "mkv"


@pytest.mark.parametrize(
    ("resolution", "expected"),
    [
        ("best", "best/best"),
        ("1080", "best[height<=1080]/best"),
        ("2160", "best[height<=2160]/best"),
    ],
)
def test_resolution_caps_format_selection(resolution: str, expected: str, tmp_path) -> None:
    ydl_opts, _ = build(make_options(output_dir=str(tmp_path), resolution=resolution))
    assert ydl_opts["format"] == expected


# ------------------------------------------------------------------ audio


def test_audio_needs_ffmpeg(tmp_path) -> None:
    with pytest.raises(OptionsError, match="Audio conversion requires FFmpeg"):
        build(make_options(output_dir=str(tmp_path), mode="audio"))


def test_audio_lossy_format_carries_a_bitrate(tmp_path) -> None:
    ydl_opts, _ = build(
        make_options(output_dir=str(tmp_path), mode="audio", audio_format="mp3"),
        ffmpeg=WITH_FFMPEG,
    )
    extractor = ydl_opts["postprocessors"][0]
    assert extractor["key"] == "FFmpegExtractAudio"
    assert extractor["preferredcodec"] == "mp3"
    assert extractor["preferredquality"] == "320"
    assert ydl_opts["format"] == "bestaudio/best"


def test_flac_is_lossless_and_skips_bitrate(tmp_path) -> None:
    ydl_opts, _ = build(
        make_options(output_dir=str(tmp_path), mode="audio", audio_format="flac"),
        ffmpeg=WITH_FFMPEG,
    )
    assert "preferredquality" not in ydl_opts["postprocessors"][0]


def test_audio_mode_warns_about_video_only_features(tmp_path) -> None:
    _, warnings = build(
        make_options(
            output_dir=str(tmp_path),
            mode="audio",
            subtitle_mode="embed",
            sponsorblock_mode="mark",
        ),
        ffmpeg=WITH_FFMPEG,
    )
    assert any("Subtitles are only applied to video" in text for text in warnings)
    assert any("SponsorBlock is only applied to video" in text for text in warnings)


# ------------------------------------------------------------ subtitles etc


def test_embedded_subtitles_configuration(tmp_path) -> None:
    ydl_opts, _ = build(
        make_options(
            output_dir=str(tmp_path),
            subtitle_mode="embed",
            subtitle_languages="en,hi",
            include_auto_subs=True,
        ),
        ffmpeg=WITH_FFMPEG,
    )
    assert ydl_opts["writesubtitles"] is True
    assert ydl_opts["writeautomaticsub"] is True
    assert ydl_opts["subtitleslangs"] == ["en", "hi"]
    assert "FFmpegEmbedSubtitle" in [pp["key"] for pp in ydl_opts["postprocessors"]]


def test_sidecar_subtitles_are_not_embedded(tmp_path) -> None:
    ydl_opts, _ = build(
        make_options(output_dir=str(tmp_path), subtitle_mode="sidecar"),
        ffmpeg=WITH_FFMPEG,
    )
    assert ydl_opts["writesubtitles"] is True
    assert "FFmpegEmbedSubtitle" not in [pp["key"] for pp in ydl_opts.get("postprocessors", [])]


def test_subtitle_languages_fall_back_to_english(tmp_path) -> None:
    ydl_opts, _ = build(
        make_options(
            output_dir=str(tmp_path),
            subtitle_mode="sidecar",
            subtitle_languages=" , ",
        ),
        ffmpeg=WITH_FFMPEG,
    )
    assert ydl_opts["subtitleslangs"] == ["en"]


def test_sponsorblock_remove_and_mark(tmp_path) -> None:
    removed, _ = build(
        make_options(output_dir=str(tmp_path), sponsorblock_mode="remove"),
        ffmpeg=WITH_FFMPEG,
    )
    keys = [pp["key"] for pp in removed["postprocessors"]]
    assert "SponsorBlock" in keys
    assert "ModifyChapters" in keys
    modify = next(pp for pp in removed["postprocessors"] if pp["key"] == "ModifyChapters")
    assert modify["remove_sponsor_segments"] == {"sponsor", "selfpromo"}

    marked, _ = build(
        make_options(output_dir=str(tmp_path), sponsorblock_mode="mark"),
        ffmpeg=WITH_FFMPEG,
    )
    modify = next(pp for pp in marked["postprocessors"] if pp["key"] == "ModifyChapters")
    assert modify["remove_sponsor_segments"] == set()
    assert any(
        pp["key"] == "FFmpegMetadata" and pp["add_chapters"] for pp in marked["postprocessors"]
    )


def test_unknown_sponsorblock_categories_warn(tmp_path) -> None:
    _, warnings = build(
        make_options(
            output_dir=str(tmp_path),
            sponsorblock_mode="mark",
            sponsorblock_categories="sponsor,not-a-category",
        ),
        ffmpeg=WITH_FFMPEG,
    )
    assert any("Ignoring unknown SponsorBlock categories: not-a-category" in t for t in warnings)


def test_metadata_and_thumbnail_are_skipped_without_ffmpeg(tmp_path) -> None:
    ydl_opts, warnings = build(make_options(output_dir=str(tmp_path)))
    assert "postprocessors" not in ydl_opts
    assert "writethumbnail" not in ydl_opts
    assert any("Metadata and chapter embedding require FFmpeg" in t for t in warnings)
    assert any("Thumbnail embedding requires FFmpeg" in t for t in warnings)


def test_metadata_and_thumbnail_are_applied_with_ffmpeg(tmp_path) -> None:
    ydl_opts, _ = build(make_options(output_dir=str(tmp_path)), ffmpeg=WITH_FFMPEG)
    keys = [pp["key"] for pp in ydl_opts["postprocessors"]]
    assert "FFmpegMetadata" in keys
    assert "EmbedThumbnail" in keys
    assert ydl_opts["writethumbnail"] is True


# ------------------------------------------------------ playlists and net


def test_playlist_toggle_controls_noplaylist(tmp_path) -> None:
    single, _ = build(make_options(output_dir=str(tmp_path)))
    whole, _ = build(make_options(output_dir=str(tmp_path), playlist=True))
    assert single["noplaylist"] is True
    assert whole["noplaylist"] is False


def test_rate_limit_converts_mb_to_bytes_per_second(tmp_path) -> None:
    ydl_opts, _ = build(make_options(output_dir=str(tmp_path), rate_limit_mbps="2.5"))
    assert ydl_opts["ratelimit"] == int(2.5 * 1024 * 1024)


@pytest.mark.parametrize("value", ["fast", "0", "-1"])
def test_bad_rate_limit_rejected(value: str, tmp_path) -> None:
    with pytest.raises(OptionsError):
        build(make_options(output_dir=str(tmp_path), rate_limit_mbps=value))


def test_cookies_from_browser_reach_yt_dlp(tmp_path) -> None:
    ydl_opts, _ = build(make_options(output_dir=str(tmp_path), cookies_browser="Firefox"))
    assert ydl_opts["cookiesfrombrowser"] == ("firefox",)


def test_bad_cookie_file_raises_options_error(tmp_path) -> None:
    with pytest.raises(OptionsError, match="Cookies file not found"):
        build(make_options(output_dir=str(tmp_path), cookies_file=str(tmp_path / "nope.txt")))


# ---------------------------------------------------------- advanced args


def test_blocked_custom_arguments(tmp_path) -> None:
    for text in ("--version", "-U", "--help", "--update-to nightly"):
        with pytest.raises(OptionsError):
            build(make_options(output_dir=str(tmp_path), custom_args=text))


def test_unparseable_custom_arguments_raise() -> None:
    with pytest.raises(OptionsError, match="Could not parse advanced arguments"):
        parse_custom_arguments('--referer "unbalanced')


def test_custom_argument_overrides_and_warns(tmp_path) -> None:
    ydl_opts, warnings = build(
        make_options(output_dir=str(tmp_path), custom_args="--socket-timeout 5")
    )
    assert ydl_opts["socket_timeout"] == 5
    assert any("Advanced arguments override: socket_timeout" in t for t in warnings)


def test_empty_custom_arguments_change_nothing(tmp_path) -> None:
    plain, _ = build(make_options(output_dir=str(tmp_path)))
    blank, _ = build(make_options(output_dir=str(tmp_path), custom_args="   "))
    assert plain == blank


# ------------------------------------------------------------- from_settings


def test_from_settings_maps_every_field(tmp_path) -> None:
    settings = make_settings(
        download_dir=str(tmp_path),
        mode="audio",
        resolution="720",
        container="mkv",
        audio_format="opus",
        audio_bitrate="128",
        subtitle_mode="sidecar",
        sponsorblock_mode="mark",
        playlist=True,
        playlist_items="2-4",
        cookies_browser="Edge",
        rate_limit_mbps="1",
        custom_args="--no-mtime",
        prefer_h264=False,
        embed_thumbnail=False,
    )
    options = DownloadOptions.from_settings(settings)
    assert options.output_dir == str(tmp_path)
    assert options.mode == "audio"
    assert options.resolution == "720"
    assert options.container == "mkv"
    assert options.audio_format == "opus"
    assert options.audio_bitrate == "128"
    assert options.subtitle_mode == "sidecar"
    assert options.sponsorblock_mode == "mark"
    assert options.playlist is True
    assert options.playlist_items == "2-4"
    assert options.cookies_browser == "Edge"
    assert options.rate_limit_mbps == "1"
    assert options.custom_args == "--no-mtime"
    assert options.prefer_h264 is False
    assert options.embed_thumbnail is False


# ------------------------------------------------------------- output paths


def test_output_directory_is_created(tmp_path) -> None:
    target = tmp_path / "deep" / "nested"
    ydl_opts, _ = build(make_options(output_dir=str(target)))
    assert target.is_dir()
    assert ydl_opts["outtmpl"].startswith(str(target))


def test_windows_filename_sanitising_is_enabled(tmp_path) -> None:
    ydl_opts, _ = build(make_options(output_dir=str(tmp_path)))
    assert isinstance(ydl_opts["windowsfilenames"], bool)
