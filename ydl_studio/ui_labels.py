"""Human-readable labels for the values stored in settings."""

from __future__ import annotations

from .config import AUDIO_BITRATES

QUALITY_CHOICES = (
    ("Best available", "best"),
    ("2160p (4K)", "2160"),
    ("1440p", "1440"),
    ("1080p", "1080"),
    ("720p", "720"),
    ("480p", "480"),
    ("360p", "360"),
)
QUALITY_FROM_LABEL = dict(QUALITY_CHOICES)
QUALITY_LABEL_FROM_VALUE = {value: label for label, value in QUALITY_CHOICES}

AUDIO_BITRATE_LABELS = tuple(f"{value} kbps" for value in AUDIO_BITRATES)

SUBTITLE_CHOICES = (
    ("Off", "off"),
    ("Embed in video", "embed"),
    ("Save separately", "sidecar"),
)
SUBTITLE_FROM_LABEL = dict(SUBTITLE_CHOICES)
SUBTITLE_LABEL_FROM_VALUE = {value: label for label, value in SUBTITLE_CHOICES}

SPONSORBLOCK_CHOICES = (
    ("Off", "off"),
    ("Mark chapters", "mark"),
    ("Remove segments", "remove"),
)
SPONSORBLOCK_FROM_LABEL = dict(SPONSORBLOCK_CHOICES)
SPONSORBLOCK_LABEL_FROM_VALUE = {value: label for label, value in SPONSORBLOCK_CHOICES}
