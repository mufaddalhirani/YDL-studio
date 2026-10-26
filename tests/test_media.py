"""URL normalisation and batch parsing."""

from __future__ import annotations

import pytest

from ydl_studio.media import normalize_url, parse_urls


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com/watch?v=1", "https://example.com/watch?v=1"),
        ("  http://example.com/a  ", "http://example.com/a"),
        ("example.com/video", "https://example.com/video"),
        ("www.example.com/video", "https://www.example.com/video"),
        ("//example.com/x", "https://example.com/x"),
        ("http://localhost:8000/sample.mp4", "http://localhost:8000/sample.mp4"),
        ("http://127.0.0.1:8000/sample.mp4", "http://127.0.0.1:8000/sample.mp4"),
        ("<https://example.com/x>", "https://example.com/x"),
        ('"https://example.com/x"', "https://example.com/x"),
        ("ytsearch:lofi beats", "ytsearch:lofi beats"),
        ("ytsearch10:lofi beats to study", "ytsearch10:lofi beats to study"),
    ],
)
def test_normalize_url_accepts(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        "not a url",
        "example",
        "https://example.com/a b",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "https://",
        "https:///no-host",
        "localhost:8000/sample.mp4",
        "ytsearch:",
        "ytsearch:    ",
        "a" * 5000,
    ],
)
def test_normalize_url_rejects(raw) -> None:
    assert normalize_url(raw) is None


def test_parse_urls_keeps_order_and_drops_duplicates() -> None:
    text = (
        "https://example.com/second\n"
        "  https://example.com/first\thttps://example.com/second\n"
        "nonsense https://example.com/third"
    )
    valid, invalid = parse_urls(text)
    assert valid == [
        "https://example.com/second",
        "https://example.com/first",
        "https://example.com/third",
    ]
    assert invalid == ["nonsense"]


def test_parse_urls_handles_empty_input() -> None:
    assert parse_urls("") == ([], [])
    assert parse_urls("   \n\t ") == ([], [])


def test_parse_urls_splits_on_every_whitespace() -> None:
    text = "https://a.example/1 https://b.example/2\r\nhttps://c.example/3"
    valid, invalid = parse_urls(text)
    assert valid == ["https://a.example/1", "https://b.example/2", "https://c.example/3"]
    assert invalid == []


def test_parse_urls_keeps_a_search_query_on_one_line() -> None:
    text = "ytsearch:lofi beats to study\nhttps://example.com/1"
    valid, invalid = parse_urls(text)
    assert valid == ["ytsearch:lofi beats to study", "https://example.com/1"]
    assert invalid == []
