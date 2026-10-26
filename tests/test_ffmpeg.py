"""FFmpeg discovery, verification and installation helpers.

Everything here stays offline: the network, the subprocess boundary and the
install directory are all replaced with stand-ins.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from ydl_studio import ffmpeg as ff
from ydl_studio.ffmpeg import FFmpegInfo, FFmpegInstallError, executable_name

FFMPEG = executable_name("ffmpeg")
FFPROBE = executable_name("ffprobe")


class FakeProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def install_root(tmp_path, monkeypatch):
    """Point every discovery root at a throwaway directory."""
    tools = tmp_path / "tools"
    app = tmp_path / "app"
    tools.mkdir()
    app.mkdir()
    monkeypatch.setattr(ff, "tools_dir", lambda: tools)
    monkeypatch.setattr(ff, "app_dir", lambda: app)
    monkeypatch.setattr(ff, "_bundle_dir", lambda: app)
    monkeypatch.setattr(ff.shutil, "which", lambda _: None)
    return {"tools": tools, "app": app}


def make_binary(path: Path, version: str = "ffmpeg version 7.1-essentials") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(version.encode("utf-8"))
    return path


def build_archive(archive: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(archive, "w") as handle:
        for name, payload in members.items():
            handle.writestr(f"ffmpeg-build/bin/{name}", payload)
    return archive


# ------------------------------------------------------------------- basics


def test_executable_name_follows_the_platform() -> None:
    expected = "ffmpeg.exe" if ff.os.name == "nt" else "ffmpeg"
    assert executable_name("ffmpeg") == expected


def test_short_version_extracts_the_numbers() -> None:
    info = FFmpegInfo(found=True, version="ffmpeg version 7.1-essentials_build")
    assert info.short_version == "7.1"


def test_short_version_falls_back_to_the_raw_string() -> None:
    assert FFmpegInfo(found=True, version="nightly").short_version == "nightly"
    assert FFmpegInfo(found=False).short_version == ""


def test_has_ffprobe_is_derived_from_the_path() -> None:
    assert not FFmpegInfo(found=True).has_ffprobe
    assert FFmpegInfo(found=True, ffprobe_path="/opt/ffprobe").has_ffprobe


def test_can_auto_install_only_offers_windows(monkeypatch) -> None:
    monkeypatch.setattr(ff.os, "name", "nt")
    assert ff.can_auto_install()
    monkeypatch.setattr(ff.os, "name", "posix")
    assert not ff.can_auto_install()


@pytest.mark.parametrize(
    ("os_name", "platform_name", "needle"),
    [("nt", "win32", "PATH"), ("posix", "darwin", "brew"), ("posix", "linux", "apt")],
)
def test_install_instructions_are_platform_specific(
    monkeypatch, os_name, platform_name, needle
) -> None:
    monkeypatch.setattr(ff.os, "name", os_name)
    monkeypatch.setattr(ff.sys, "platform", platform_name)
    assert needle in ff.install_instructions()


# ------------------------------------------------------------------ versions


def test_version_parses_the_banner_line(monkeypatch) -> None:
    monkeypatch.setattr(
        ff.subprocess,
        "run",
        lambda *a, **k: FakeProcess(stdout="ffmpeg version 7.1 Copyright (c) 2000 FFmpeg\n"),
    )
    assert ff._version_for(Path(FFMPEG)) == "7.1"


def test_version_uses_stderr_and_truncates_unknown_formats(monkeypatch) -> None:
    monkeypatch.setattr(
        ff.subprocess,
        "run",
        lambda *a, **k: FakeProcess(returncode=1, stderr="x" * 400),
    )
    assert ff._version_for(Path(FFMPEG)) is None

    monkeypatch.setattr(
        ff.subprocess,
        "run",
        lambda *a, **k: FakeProcess(stdout="some custom build\nsecond line"),
    )
    assert ff._version_for(Path(FFMPEG)) == "some custom build"


def test_version_returns_none_when_the_binary_cannot_run(monkeypatch) -> None:
    monkeypatch.setattr(
        ff.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("quarantined"))
    )
    assert ff._version_for(Path(FFMPEG)) is None


def test_version_returns_none_on_a_timeout(monkeypatch) -> None:
    import subprocess

    monkeypatch.setattr(
        ff.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("ffmpeg", 8)),
    )
    assert ff._version_for(Path(FFMPEG)) is None


# ---------------------------------------------------------------- discovery


def test_find_ffmpeg_prefers_the_installed_copy(install_root, monkeypatch) -> None:
    make_binary(install_root["tools"] / FFMPEG)
    make_binary(install_root["app"] / "bin" / FFMPEG)
    monkeypatch.setattr(ff, "_version_for", lambda path: "7.1")
    info = ff.find_ffmpeg()
    assert (info.found, info.source) == (True, "installed")
    assert Path(info.path).parent == install_root["tools"]


def test_find_ffmpeg_reports_portable_before_system(install_root, monkeypatch) -> None:
    make_binary(install_root["app"] / "bin" / FFMPEG)
    monkeypatch.setattr(ff.shutil, "which", lambda _: str(Path("/usr/bin/ffmpeg.exe")))
    monkeypatch.setattr(ff, "_version_for", lambda path: "7.1")
    assert ff.find_ffmpeg().source == "portable"


def test_find_ffmpeg_picks_up_a_sibling_ffprobe(install_root, monkeypatch) -> None:
    make_binary(install_root["tools"] / FFMPEG)
    make_binary(install_root["tools"] / FFPROBE)
    monkeypatch.setattr(ff, "_version_for", lambda path: "7.1")
    assert Path(ff.find_ffmpeg().ffprobe_path).name == FFPROBE


def test_find_ffmpeg_skips_a_broken_binary(install_root, monkeypatch) -> None:
    make_binary(install_root["tools"] / FFMPEG)
    make_binary(install_root["app"] / "bin" / FFMPEG)
    # A quarantined or non-executable leftover must not shadow a working build.
    monkeypatch.setattr(
        ff, "_version_for", lambda path: None if "tools" in str(path) else "7.1"
    )
    assert ff.find_ffmpeg().source == "portable"


def test_find_ffmpeg_reports_not_found_without_running_anything(
    install_root, monkeypatch
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(ff, "_version_for", lambda path: calls.append(path))
    assert ff.find_ffmpeg().found is False
    assert calls == []


def test_find_ffmpeg_ignores_a_directory_called_ffmpeg(install_root) -> None:
    (install_root["tools"] / FFMPEG).mkdir()
    assert ff.find_ffmpeg().found is False


# --------------------------------------------------------------- archives


def test_required_members_finds_both_executables(tmp_path) -> None:
    archive = build_archive(
        tmp_path / "ffmpeg.zip", {FFMPEG: b"a", FFPROBE: b"b", "readme.txt": b"c"}
    )
    assert ff._required_members(archive) == {FFMPEG: f"ffmpeg-build/bin/{FFMPEG}",
                                             FFPROBE: f"ffmpeg-build/bin/{FFPROBE}"}


def test_required_members_rejects_a_missing_ffprobe(tmp_path) -> None:
    archive = build_archive(tmp_path / "ffmpeg.zip", {FFMPEG: b"a"})
    with pytest.raises(FFmpegInstallError, match=FFPROBE):
        ff._required_members(archive)


def test_required_members_rejects_a_non_zip(tmp_path) -> None:
    archive = tmp_path / "ffmpeg.zip"
    archive.write_bytes(b"not a zip file")
    with pytest.raises(FFmpegInstallError, match="not a valid ZIP"):
        ff._required_members(archive)


def test_required_members_ignores_directory_entries(tmp_path) -> None:
    with zipfile.ZipFile(tmp_path / "ffmpeg.zip", "w") as handle:
        handle.writestr("ffmpeg-build/bin/", "")
        handle.writestr(f"ffmpeg-build/bin/{FFMPEG}", b"a")
        handle.writestr(f"ffmpeg-build/{FFPROBE}/", "")
    with pytest.raises(FFmpegInstallError, match="missing"):
        ff._required_members(tmp_path / "ffmpeg.zip")


def test_extract_writes_only_the_executables(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ff, "_MIN_EXECUTABLE_BYTES", 1)
    archive = build_archive(
        tmp_path / "ffmpeg.zip", {FFMPEG: b"ffmpeg!", FFPROBE: b"ffprobe!", "docs": b"x"}
    )
    destination = tmp_path / "out"
    extracted = ff._extract_executables(archive, destination)
    assert sorted(path.name for path in extracted.values()) == sorted([FFMPEG, FFPROBE])
    assert (destination / FFMPEG).read_bytes() == b"ffmpeg!"
    assert not (destination / "docs").exists()


def test_extract_rejects_a_truncated_executable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ff, "_MIN_EXECUTABLE_BYTES", 1024)
    archive = build_archive(tmp_path / "ffmpeg.zip", {FFMPEG: b"tiny", FFPROBE: b"tiny"})
    with pytest.raises(FFmpegInstallError, match="unexpectedly small"):
        ff._extract_executables(archive, tmp_path / "out")


# --------------------------------------------------------------- installs


def test_install_replaces_an_existing_binary(install_root) -> None:
    destination = install_root["tools"]
    make_binary(destination / FFMPEG, "old")
    source = install_root["app"] / "downloaded"
    make_binary(source, "new")
    ff._install_executables({FFMPEG: source}, destination)
    assert (destination / FFMPEG).read_text(encoding="utf-8") == "new"
    assert list(destination.glob("*.tmp")) == []


def test_install_gives_a_helpful_error_when_the_file_is_locked(
    install_root, monkeypatch
) -> None:
    def deny(_src, _dst):
        raise PermissionError("in use")

    monkeypatch.setattr(ff.shutil, "copyfile", deny)
    source = make_binary(install_root["app"] / "downloaded")
    with pytest.raises(FFmpegInstallError, match="Windows is using"):
        ff._install_executables({FFMPEG: source}, install_root["tools"])
    assert list(install_root["tools"].glob("*.tmp")) == []


def test_install_from_executable_needs_a_launchable_file(install_root, monkeypatch) -> None:
    with pytest.raises(FFmpegInstallError, match="does not exist"):
        ff.install_from_executable(install_root["tools"] / "nope.exe")

    source = make_binary(install_root["app"] / "downloaded")
    monkeypatch.setattr(ff, "_version_for", lambda path: None)
    with pytest.raises(FFmpegInstallError, match="could not be started"):
        ff.install_from_executable(source)


def test_install_from_executable_copies_both_tools(
    install_root, monkeypatch
) -> None:
    source = make_binary(install_root["app"] / "dl" / FFMPEG)
    probe = make_binary(install_root["app"] / "dl" / FFPROBE)
    monkeypatch.setattr(ff, "_version_for", lambda path: "7.1")
    monkeypatch.setattr(
        ff, "find_ffmpeg", lambda: FFmpegInfo(found=True, path=str(source), version="7.1")
    )
    info = ff.install_from_executable(source, probe)
    assert info.found
    assert (install_root["tools"] / FFMPEG).is_file()
    assert (install_root["tools"] / FFPROBE).is_file()


def test_install_from_executable_tolerates_a_missing_ffprobe(
    install_root, monkeypatch
) -> None:
    source = make_binary(install_root["app"] / "dl" / FFMPEG)
    monkeypatch.setattr(ff, "_version_for", lambda path: "7.1")
    monkeypatch.setattr(ff, "find_ffmpeg", lambda: FFmpegInfo(found=True))
    ff.install_from_executable(source)
    assert not (install_root["tools"] / FFPROBE).exists()


def test_download_and_install_refuses_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(ff, "can_auto_install", lambda: False)
    with pytest.raises(FFmpegInstallError, match="only available on Windows"):
        ff.download_and_install_ffmpeg()


# ---------------------------------------------------------------- download


class FakeResponse:
    def __init__(self, chunks, content_length=None):
        self._chunks = list(chunks)
        length = sum(len(chunk) for chunk in self._chunks) if content_length is None else content_length
        self.headers = {"Content-Length": str(length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, _size):
        return self._chunks.pop(0) if self._chunks else b""


def test_download_reports_progress_and_stops_on_cancel(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ff, "_MIN_ARCHIVE_BYTES", 1)
    seen: list[tuple[int, int]] = []
    response = FakeResponse([b"x" * 10, b"x" * 10])
    monkeypatch.setattr(ff, "urlopen", lambda *a, **k: response)

    class Cancel:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls > 1

    with pytest.raises(FFmpegInstallError, match="cancelled"):
        ff._download_archive(
            "https://example.com/ffmpeg.zip",
            tmp_path / "partial.zip",
            lambda done, total: seen.append((done, total)),
            lambda message: None,
            Cancel(),
        )
    assert seen == [(10, 20)]


def test_download_rejects_an_absurd_content_length(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        ff, "urlopen", lambda *a, **k: FakeResponse([b"x"], content_length=10**12)
    )
    with pytest.raises(FFmpegInstallError, match="unexpectedly large"):
        ff._download_archive(
            "https://example.com/ffmpeg.zip", tmp_path / "never.zip", None, None, None
        )


def test_download_rejects_a_body_larger_than_the_header(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ff, "_MAX_ARCHIVE_BYTES", 16)
    monkeypatch.setattr(ff, "_MIN_ARCHIVE_BYTES", 1)
    monkeypatch.setattr(
        ff, "urlopen", lambda *a, **k: FakeResponse([b"x" * 40], content_length=8)
    )
    with pytest.raises(FFmpegInstallError, match="exceeded the size limit"):
        ff._download_archive(
            "https://example.com/ffmpeg.zip", tmp_path / "huge.zip", None, None, None
        )


def test_download_rejects_a_truncated_archive(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ff, "_MIN_ARCHIVE_BYTES", 1_000_000)
    monkeypatch.setattr(ff, "urlopen", lambda *a, **k: FakeResponse([b"x" * 10]))
    with pytest.raises(FFmpegInstallError, match="incomplete"):
        ff._download_archive(
            "https://example.com/ffmpeg.zip", tmp_path / "short.zip", None, None, None
        )


def test_download_urls_avoids_repeating_the_primary_source(monkeypatch) -> None:
    monkeypatch.setattr(ff, "_github_archive_url", lambda: ff._STABLE_ARCHIVE_URL)
    messages: list[str] = []
    urls = list(ff._download_urls(lambda text: messages.append(text)))
    assert urls == [ff._STABLE_ARCHIVE_URL]
    assert messages == ["Checking the GitHub mirror..."]


def test_download_urls_appends_a_working_mirror(monkeypatch) -> None:
    monkeypatch.setattr(ff, "_github_archive_url", lambda: "https://gh.example/v1.zip")
    assert list(ff._download_urls(None)) == [ff._STABLE_ARCHIVE_URL, "https://gh.example/v1.zip"]


def test_download_urls_skips_an_unreachable_mirror(monkeypatch) -> None:
    monkeypatch.setattr(ff, "_github_archive_url", lambda: None)
    assert list(ff._download_urls(None)) == [ff._STABLE_ARCHIVE_URL]
