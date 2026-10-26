"""FFmpeg discovery, verification, and automatic installation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from .config import app_data_dir

ProgressCallback = Callable[[int, int], None]
StatusCallback = Callable[[str], None]

_STABLE_ARCHIVE_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
_GITHUB_LATEST_API = "https://api.github.com/repos/GyanD/codexffmpeg/releases/latest"
_MAX_ARCHIVE_BYTES = 400 * 1024 * 1024
_MIN_ARCHIVE_BYTES = 20 * 1024 * 1024
_MIN_EXECUTABLE_BYTES = 5 * 1024 * 1024


class FFmpegInstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class FFmpegInfo:
    found: bool
    path: str | None = None
    version: str | None = None
    ffprobe_path: str | None = None
    source: str = ""

    @property
    def has_ffprobe(self) -> bool:
        return bool(self.ffprobe_path)

    @property
    def short_version(self) -> str:
        match = re.search(r"\d+(?:\.\d+)+", self.version or "")
        return match.group(0) if match else (self.version or "")


def executable_name(base: str) -> str:
    return f"{base}.exe" if os.name == "nt" else base


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", app_dir()))


def tools_dir() -> Path:
    return app_data_dir() / "bin"


def can_auto_install() -> bool:
    return os.name == "nt"


def install_instructions() -> str:
    if os.name == "nt":
        return "Use the automatic installer, or place ffmpeg.exe and ffprobe.exe on PATH."
    if sys.platform == "darwin":
        return "Install FFmpeg with: brew install ffmpeg"
    return "Install FFmpeg with your package manager, for example: sudo apt install ffmpeg"


def _windows_no_console() -> dict[str, int]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _candidate_paths() -> Iterator[tuple[Path, str]]:
    name = executable_name("ffmpeg")
    yield tools_dir() / name, "installed"
    yield app_dir() / "bin" / name, "portable"
    bundle = _bundle_dir()
    if bundle != app_dir():
        yield bundle / "bin" / name, "bundled"
    discovered = shutil.which("ffmpeg")
    if discovered:
        yield Path(discovered), "system"


def _version_for(path: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            timeout=8,
            **_windows_no_console(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return None
    first_line = output.splitlines()[0].strip()
    match = re.search(r"ffmpeg version (\S+)", first_line, re.IGNORECASE)
    return match.group(1) if match else first_line[:80]


def _ffprobe_for(path: Path) -> str | None:
    candidate = path.with_name(executable_name("ffprobe"))
    if candidate.is_file():
        return str(candidate)
    return None


def find_ffmpeg() -> FFmpegInfo:
    seen: set[str] = set()
    for path, source in _candidate_paths():
        key = os.path.normcase(str(path.resolve(strict=False)))
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        version = _version_for(path)
        if version is None:
            continue
        return FFmpegInfo(
            found=True,
            path=str(path),
            version=version,
            ffprobe_path=_ffprobe_for(path),
            source=source,
        )
    return FFmpegInfo(found=False)


def _github_archive_url() -> str | None:
    request = Request(
        _GITHUB_LATEST_API,
        headers={
            "User-Agent": "YDL-Studio",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return None
    for asset in payload.get("assets", []):
        name = str(asset.get("name", ""))
        if name.endswith("essentials_build.zip") and asset.get("browser_download_url"):
            return str(asset["browser_download_url"])
    return None


def _download_urls(status_callback: StatusCallback | None) -> Iterator[str]:
    yield _STABLE_ARCHIVE_URL
    if status_callback:
        status_callback("Checking the GitHub mirror...")
    fallback = _github_archive_url()
    if fallback and fallback != _STABLE_ARCHIVE_URL:
        yield fallback


def _download_archive(
    url: str,
    target: Path,
    progress_callback: ProgressCallback | None,
    status_callback: StatusCallback | None,
    cancel_event,
) -> None:
    if status_callback:
        status_callback(f"Downloading FFmpeg from {url.split('/')[2]}...")

    request = Request(
        url,
        headers={
            "User-Agent": "YDL-Studio/2",
            "Accept": "application/zip,application/octet-stream",
        },
    )
    with urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        if total > _MAX_ARCHIVE_BYTES:
            raise FFmpegInstallError(
                f"The FFmpeg archive is unexpectedly large ({total / 1_048_576:.0f} MB)."
            )

        downloaded = 0
        last_percent = -1
        last_report = 0
        with target.open("wb") as handle:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise FFmpegInstallError("FFmpeg installation was cancelled.")
                chunk = response.read(512 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if downloaded > _MAX_ARCHIVE_BYTES:
                    raise FFmpegInstallError("FFmpeg download exceeded the size limit.")
                if progress_callback:
                    if total:
                        percent = int(downloaded * 100 / total)
                        if percent != last_percent:
                            last_percent = percent
                            progress_callback(downloaded, total)
                    elif downloaded - last_report >= 2 * 1024 * 1024:
                        last_report = downloaded
                        progress_callback(downloaded, total)

    if target.stat().st_size < _MIN_ARCHIVE_BYTES:
        raise FFmpegInstallError("The downloaded FFmpeg archive is incomplete.")
    if progress_callback:
        progress_callback(downloaded, total or downloaded)


def _required_members(archive: Path) -> dict[str, str]:
    if not zipfile.is_zipfile(archive):
        raise FFmpegInstallError("The downloaded file is not a valid ZIP archive.")
    wanted = {executable_name("ffmpeg"), executable_name("ffprobe")}
    found: dict[str, str] = {}
    with zipfile.ZipFile(archive) as handle:
        for member in handle.namelist():
            base = os.path.basename(member).lower()
            for name in wanted:
                if base == name.lower() and not member.endswith("/"):
                    found[name] = member
    missing = wanted - set(found)
    if missing:
        raise FFmpegInstallError(
            "The archive is missing: " + ", ".join(sorted(missing))
        )
    return found


def _extract_executables(archive: Path, destination: Path) -> dict[str, Path]:
    members = _required_members(archive)
    destination.mkdir(parents=True, exist_ok=True)
    extracted: dict[str, Path] = {}
    with zipfile.ZipFile(archive) as handle:
        for name, member in members.items():
            output = destination / name
            with handle.open(member) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target)
            if output.stat().st_size < _MIN_EXECUTABLE_BYTES:
                raise FFmpegInstallError(f"{name} is unexpectedly small.")
            extracted[name] = output
    return extracted


def _install_executables(extracted: dict[str, Path], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, source in extracted.items():
        target = destination / name
        temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
            if os.name != "nt":
                target.chmod(0o755)
        except PermissionError as exc:
            temporary.unlink(missing_ok=True)
            raise FFmpegInstallError(
                "Windows is using the existing FFmpeg files. Close any active downloads "
                "or other apps using FFmpeg, then try again."
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)


def download_and_install_ffmpeg(
    progress_callback: ProgressCallback | None = None,
    status_callback: StatusCallback | None = None,
    cancel_event=None,
) -> FFmpegInfo:
    if not can_auto_install():
        raise FFmpegInstallError(
            "Automatic installation is only available on Windows. " + install_instructions()
        )

    target_dir = tools_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="ydl-studio-ffmpeg-") as temp:
        archive = Path(temp) / "ffmpeg.zip"
        for url in _download_urls(status_callback):
            try:
                host = url.split("/")[2]
                _download_archive(
                    url, archive, progress_callback, status_callback, cancel_event
                )
                if status_callback:
                    status_callback("Verifying and extracting FFmpeg...")
                extracted = _extract_executables(archive, Path(temp) / "extracted")
                _install_executables(extracted, target_dir)
                info = find_ffmpeg()
                if not info.found:
                    raise FFmpegInstallError(
                        "FFmpeg was installed but could not be started. "
                        "Check your antivirus quarantine."
                    )
                if status_callback:
                    status_callback(f"FFmpeg {info.version or ''} is ready.".strip())
                return info
            except FFmpegInstallError as exc:
                if "cancelled" in str(exc).lower():
                    raise
                errors.append(f"{host}: {exc}")
                archive.unlink(missing_ok=True)
                if status_callback:
                    status_callback(f"Mirror {host} failed; trying the next source...")
            except OSError as exc:
                errors.append(f"{host}: {exc}")
                archive.unlink(missing_ok=True)
                if status_callback:
                    status_callback(f"Mirror {host} failed; trying the next source...")

    detail = " | ".join(errors) if errors else "No download source was reachable."
    raise FFmpegInstallError(f"Could not install FFmpeg. {detail}")


def install_from_executable(
    ffmpeg_path: str | Path,
    ffprobe_path: str | Path | None = None,
) -> FFmpegInfo:
    source = Path(ffmpeg_path)
    if not source.is_file():
        raise FFmpegInstallError("The selected ffmpeg file does not exist.")
    version = _version_for(source)
    if version is None:
        raise FFmpegInstallError(
            "The selected ffmpeg file could not be started. Choose a working build."
        )

    probe_source = Path(ffprobe_path) if ffprobe_path else source.with_name(
        executable_name("ffprobe")
    )
    target_dir = tools_dir()
    extracted = {executable_name("ffmpeg"): source}
    if probe_source.is_file():
        extracted[executable_name("ffprobe")] = probe_source
    _install_executables(extracted, target_dir)

    info = find_ffmpeg()
    if not info.found:
        raise FFmpegInstallError("FFmpeg was copied but could not be started.")
    return info
