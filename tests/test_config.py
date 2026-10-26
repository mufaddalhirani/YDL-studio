"""Settings validation, persistence and the history store."""

from __future__ import annotations

import json

import pytest
from helpers import make_settings

from ydl_studio.config import (
    DEFAULT_FILENAME_TEMPLATE,
    AppSettings,
    HistoryEntry,
    HistoryStore,
    load_settings,
    save_settings,
)


def entry(name: str, **overrides) -> HistoryEntry:
    values = {
        "title": name,
        "file_path": f"/downloads/{name}.mp4",
        "url": f"https://example.com/{name}",
        "mode": "video",
        "size_bytes": 1024,
    }
    values.update(overrides)
    return HistoryEntry.create(**values)


# ------------------------------------------------------------------ settings


def test_defaults_are_conservative() -> None:
    settings = AppSettings()
    assert settings.theme == "Dark"
    assert settings.mode == "video"
    assert settings.resolution == "best"
    assert settings.subtitle_mode == "off"
    assert settings.sponsorblock_mode == "off"
    assert settings.cookies_browser == "None"
    assert settings.clipboard_watch is False
    assert settings.minimize_to_tray is False
    assert settings.notifications is True
    assert settings.filename_template == DEFAULT_FILENAME_TEMPLATE


@pytest.mark.parametrize(
    ("field", "junk", "fallback"),
    [
        ("theme", "Gothic", "Dark"),
        ("mode", "surround", "video"),
        ("resolution", "8K", "best"),
        ("container", "avi", "mp4"),
        ("audio_format", "wma", "mp3"),
        ("audio_bitrate", "999", "320"),
        ("subtitle_mode", "burn-in", "off"),
        ("sponsorblock_mode", "mute", "off"),
        ("cookies_browser", "Internet Explorer", "None"),
    ],
)
def test_unknown_enum_values_fall_back(field: str, junk: str, fallback: str) -> None:
    settings = make_settings(**{field: junk})
    assert getattr(settings, field) == fallback


@pytest.mark.parametrize(
    ("field", "junk"),
    [
        ("subtitle_languages", "en; rm -rf /"),
        ("subtitle_languages", ""),
        ("sponsorblock_categories", "SPONSOR!!"),
        ("sponsorblock_categories", "sponsor/../etc"),
    ],
)
def test_free_text_fields_fall_back_when_unsafe(field: str, junk: str) -> None:
    expected = "en" if field == "subtitle_languages" else "sponsor,selfpromo"
    assert getattr(make_settings(**{field: junk}), field) == expected


def test_whitespace_is_stripped_from_lists() -> None:
    settings = make_settings(subtitle_languages=" en , hi ")
    assert settings.subtitle_languages == "en,hi"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), ("true", True), (1, True), (None, True)],
)
def test_booleans_only_change_when_truly_boolean(value, expected: bool) -> None:
    # _as_bool ignores junk and keeps the default, so a hand-edited config cannot
    # silently flip a preference.
    assert make_settings(embed_metadata=value).embed_metadata is expected


def test_settings_survive_a_round_trip(tmp_path) -> None:
    path = tmp_path / "config.json"
    original = make_settings(theme="Light", resolution="720", playlist=True)
    save_settings(original, path)
    loaded = load_settings(path)
    assert loaded.theme == "Light"
    assert loaded.resolution == "720"
    assert loaded.playlist is True


def test_unknown_keys_in_a_config_file_are_ignored(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"theme": "Light", "answer": 42, "mode": 7}), encoding="utf-8"
    )
    settings = load_settings(path)
    assert settings.theme == "Light"
    assert settings.mode == "video"


def test_missing_file_returns_defaults(tmp_path) -> None:
    settings = load_settings(tmp_path / "absent.json")
    assert settings == AppSettings()


@pytest.mark.parametrize(
    "payload",
    ["{ not json", "[]", '"a string"', "null", "{}{}"],
)
def test_corrupt_file_is_moved_aside_and_defaults_return(tmp_path, payload: str) -> None:
    path = tmp_path / "config.json"
    path.write_text(payload, encoding="utf-8")
    settings = load_settings(path)
    assert settings.theme == "Dark"
    backups = [item.name for item in tmp_path.iterdir() if ".corrupt-" in item.name]
    assert backups, "the unreadable file should be kept for inspection"
    assert not path.exists()


def test_saving_leaves_no_temporary_file(tmp_path) -> None:
    path = tmp_path / "nested" / "config.json"
    save_settings(make_settings(), path)
    assert path.is_file()
    assert list(path.parent.glob("*.tmp")) == []


# ------------------------------------------------------------------- history


def test_history_entry_defaults_and_helpers() -> None:
    item = entry("sample")
    assert item.id and item.completed_at
    assert item.file_name == "sample.mp4"
    assert item.size_bytes == 1024
    assert "T" in item.completed_local() or item.completed_local()


def test_history_entry_title_falls_back_to_the_file_name() -> None:
    item = HistoryEntry.create(
        title="   ",
        file_path="/downloads/untitled.mp4",
        url="",
        mode="video",
    )
    assert item.title == "untitled.mp4"


@pytest.mark.parametrize("payload", [
    {},
    {"id": "x"},
    None,
    {"id": "a", "title": "b", "file_path": "c", "completed_at": "d", "size_bytes": "lots"},
])
def test_unreadable_history_entries_are_dropped(payload) -> None:
    # A hand-edited or half-written history line must never crash the tab that
    # renders it, so anything the dataclass cannot coerce is silently dropped.
    assert HistoryEntry.from_dict(payload) is None


def test_readable_history_entries_are_coerced() -> None:
    item = HistoryEntry.from_dict(
        {"id": 1, "title": 2, "file_path": 3, "completed_at": 4, "size_bytes": "1024"}
    )
    assert item is not None
    assert (item.id, item.title, item.file_name) == ("1", "2", "3")
    assert item.size_bytes == 1024
    assert item.mode == "video"


def test_history_round_trip(tmp_path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    store.add_many([entry("older"), entry("newest")])
    store.add_many([entry("later")])
    reloaded = HistoryStore(path)
    assert [item.title for item in reloaded.entries] == ["later", "older", "newest"]


def test_add_many_replaces_an_existing_record(tmp_path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    first = entry("one")
    store.add_many([first])
    again = HistoryEntry(
        id="different",
        title="one",
        file_path=first.file_path,
        url=first.url,
        mode="video",
        completed_at=first.completed_at,
        size_bytes=first.size_bytes,
    )
    store.add_many([again])
    assert len(store.entries) == 1


def test_history_is_capped_oldest_records_fall_off(tmp_path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path, max_entries=3)
    store.add_many([entry("old-1")])
    store.add_many([entry(f"new-{index}") for index in range(3)])
    assert [item.title for item in store.entries] == ["new-0", "new-1", "new-2"]
    assert [item.title for item in HistoryStore(path).entries] == ["new-0", "new-1", "new-2"]


def test_remove_and_clear(tmp_path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    items = [entry("keep"), entry("drop")]
    store.add_many(items)
    store.remove(items[1].id)
    assert [item.title for item in store.entries] == ["keep"]
    assert HistoryStore(path).entries[0].title == "keep"
    store.clear()
    assert HistoryStore(path).entries == []


def test_corrupt_history_is_moved_aside(tmp_path) -> None:
    path = tmp_path / "history.json"
    path.write_text("}}} not json", encoding="utf-8")
    store = HistoryStore(path)
    assert store.entries == []
    assert any(".corrupt-" in item.name for item in tmp_path.iterdir())


def test_history_accepts_a_bare_list(tmp_path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    store.add_many([entry("legacy")])
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(payload["entries"]), encoding="utf-8")
    assert [item.title for item in HistoryStore(path).entries] == ["legacy"]


def test_negative_sizes_are_clamped() -> None:
    item = entry("clamped", size_bytes=-100)
    assert item.size_bytes == 0
