"""Application paths, validated settings, and persistent download history."""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import APP_NAME

THEMES = ("Dark", "Light", "System")
MODES = ("video", "audio")
RESOLUTIONS = ("best", "2160", "1440", "1080", "720", "480", "360")
CONTAINERS = ("mp4", "mkv")
AUDIO_FORMATS = ("mp3", "m4a", "flac", "wav", "opus")
AUDIO_BITRATES = ("320", "256", "192", "128")
SUBTITLE_MODES = ("off", "embed", "sidecar")
SPONSORBLOCK_MODES = ("off", "mark", "remove")
COOKIE_BROWSERS = (
    "None",
    "Chrome",
    "Edge",
    "Firefox",
    "Brave",
    "Opera",
    "Vivaldi",
    "Chromium",
    "Safari",
)

DEFAULT_FILENAME_TEMPLATE = "%(title)s [%(id)s].%(ext)s"
_MAX_HISTORY_ENTRIES = 500


def _windows_downloads_dir() -> Path | None:
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            raw, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
        if raw:
            return Path(os.path.expandvars(str(raw)))
    except (ImportError, OSError, ValueError):
        pass
    return None


def default_download_dir() -> Path:
    if os.name == "nt":
        downloads = _windows_downloads_dir()
        if downloads:
            return downloads / APP_NAME
        return Path.home() / "Downloads" / APP_NAME
    return Path.home() / "Downloads" / APP_NAME


def app_data_dir() -> Path:
    override = os.environ.get("YDL_STUDIO_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME


def settings_path() -> Path:
    return app_data_dir() / "config.json"


def history_path() -> Path:
    return app_data_dir() / "history.json"


def log_dir() -> Path:
    return app_data_dir() / "logs"


def _pick(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
    return value if isinstance(value, str) and value in allowed else fallback


def _as_bool(value: Any, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _as_text(value: Any, fallback: str = "") -> str:
    return value.strip() if isinstance(value, str) else fallback


@dataclass
class AppSettings:
    theme: str = "Dark"
    download_dir: str = ""
    filename_template: str = DEFAULT_FILENAME_TEMPLATE
    mode: str = "video"
    resolution: str = "best"
    container: str = "mp4"
    prefer_h264: bool = True
    audio_format: str = "mp3"
    audio_bitrate: str = "320"
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    embed_chapters: bool = True
    subtitle_mode: str = "off"
    subtitle_languages: str = "en"
    include_auto_subs: bool = False
    sponsorblock_mode: str = "off"
    sponsorblock_categories: str = "sponsor,selfpromo"
    playlist: bool = False
    playlist_items: str = ""
    cookies_browser: str = "None"
    cookies_file: str = ""
    rate_limit_mbps: str = ""
    custom_args: str = ""
    clipboard_watch: bool = False
    minimize_to_tray: bool = False
    notifications: bool = True

    def __post_init__(self) -> None:
        self.normalize()

    def normalize(self) -> None:
        self.theme = _pick(self.theme, THEMES, "Dark")
        self.mode = _pick(self.mode, MODES, "video")
        self.resolution = _pick(self.resolution, RESOLUTIONS, "best")
        self.container = _pick(self.container, CONTAINERS, "mp4")
        self.audio_format = _pick(self.audio_format, AUDIO_FORMATS, "mp3")
        self.audio_bitrate = _pick(self.audio_bitrate, AUDIO_BITRATES, "320")
        self.subtitle_mode = _pick(self.subtitle_mode, SUBTITLE_MODES, "off")
        self.sponsorblock_mode = _pick(self.sponsorblock_mode, SPONSORBLOCK_MODES, "off")
        self.cookies_browser = _pick(self.cookies_browser, COOKIE_BROWSERS, "None")

        self.download_dir = _as_text(self.download_dir) or str(default_download_dir())
        self.filename_template = (
            _as_text(self.filename_template) or DEFAULT_FILENAME_TEMPLATE
        )
        self.cookies_file = _as_text(self.cookies_file)
        self.custom_args = _as_text(self.custom_args)
        self.playlist_items = _as_text(self.playlist_items)
        self.rate_limit_mbps = _as_text(self.rate_limit_mbps)

        languages = _as_text(self.subtitle_languages) or "en"
        languages = re.sub(r"\s+", "", languages)
        self.subtitle_languages = languages if re.fullmatch(r"[\w.*,\-]+", languages) else "en"

        categories = _as_text(self.sponsorblock_categories) or "sponsor,selfpromo"
        categories = re.sub(r"\s+", "", categories)
        self.sponsorblock_categories = (
            categories if re.fullmatch(r"[a-z_,\-]+", categories) else "sponsor,selfpromo"
        )

        self.prefer_h264 = _as_bool(self.prefer_h264, True)
        self.embed_metadata = _as_bool(self.embed_metadata, True)
        self.embed_thumbnail = _as_bool(self.embed_thumbnail, True)
        self.embed_chapters = _as_bool(self.embed_chapters, True)
        self.include_auto_subs = _as_bool(self.include_auto_subs, False)
        self.playlist = _as_bool(self.playlist, False)
        self.clipboard_watch = _as_bool(self.clipboard_watch, False)
        self.minimize_to_tray = _as_bool(self.minimize_to_tray, False)
        self.notifications = _as_bool(self.notifications, True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        known = {item.name for item in fields(cls)}
        clean = {key: value for key, value in data.items() if key in known}
        return cls(**clean)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _backup_corrupt_file(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    try:
        path.replace(path.with_suffix(path.suffix + f".corrupt-{stamp}"))
    except OSError:
        pass


def load_settings(path: Path | None = None) -> AppSettings:
    target = path or settings_path()
    raw = _load_json(target)
    if raw is None:
        if target.exists() and target.stat().st_size > 0:
            _backup_corrupt_file(target)
        return AppSettings()
    if not isinstance(raw, dict):
        _backup_corrupt_file(target)
        return AppSettings()
    try:
        return AppSettings.from_dict(raw)
    except (TypeError, ValueError):
        _backup_corrupt_file(target)
        return AppSettings()


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    settings.normalize()
    _atomic_write_json(path or settings_path(), settings.to_dict())


@dataclass
class HistoryEntry:
    id: str
    title: str
    file_path: str
    url: str
    mode: str
    completed_at: str
    size_bytes: int = 0

    @classmethod
    def create(
        cls,
        *,
        title: str,
        file_path: str,
        url: str,
        mode: str,
        size_bytes: int = 0,
    ) -> HistoryEntry:
        return cls(
            id=uuid.uuid4().hex,
            title=title.strip() or Path(file_path).name,
            file_path=str(Path(file_path)),
            url=url,
            mode=mode,
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            size_bytes=max(0, int(size_bytes)),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry | None:
        try:
            entry = cls(
                id=str(data["id"]),
                title=str(data["title"]),
                file_path=str(data["file_path"]),
                url=str(data.get("url", "")),
                mode=str(data.get("mode", "video")),
                completed_at=str(data["completed_at"]),
                size_bytes=max(0, int(data.get("size_bytes", 0))),
            )
        except (KeyError, TypeError, ValueError):
            return None
        return entry

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def file_name(self) -> str:
        return Path(self.file_path).name

    def completed_local(self) -> str:
        try:
            moment = datetime.fromisoformat(self.completed_at)
        except ValueError:
            return self.completed_at
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone().strftime("%Y-%m-%d %H:%M")


class HistoryStore:
    def __init__(self, path: Path | None = None, max_entries: int = _MAX_HISTORY_ENTRIES):
        self.path = path or history_path()
        self.max_entries = max_entries
        self.entries: list[HistoryEntry] = []
        self.load()

    def load(self) -> None:
        raw = _load_json(self.path)
        if isinstance(raw, dict):
            raw = raw.get("entries")
        if not isinstance(raw, list):
            if self.path.exists() and self.path.stat().st_size > 0:
                _backup_corrupt_file(self.path)
            self.entries = []
            return
        parsed = [HistoryEntry.from_dict(item) for item in raw if isinstance(item, dict)]
        self.entries = [entry for entry in parsed if entry is not None][: self.max_entries]

    def save(self) -> None:
        self.entries = self.entries[: self.max_entries]
        _atomic_write_json(
            self.path,
            {
                "version": 1,
                "entries": [entry.to_dict() for entry in self.entries],
            },
        )

    def add_many(self, entries: list[HistoryEntry]) -> None:
        if not entries:
            return
        seen = {(entry.file_path, entry.completed_at) for entry in entries}
        self.entries = [
            entry
            for entry in entries
            if (entry.file_path, entry.completed_at) in seen
        ] + [
            old
            for old in self.entries
            if (old.file_path, old.completed_at) not in seen
        ]
        self.entries = self.entries[: self.max_entries]
        self.save()

    def remove(self, entry_id: str) -> None:
        self.entries = [entry for entry in self.entries if entry.id != entry_id]
        self.save()

    def clear(self) -> None:
        self.entries = []
        self.save()
