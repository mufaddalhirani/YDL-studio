"""A sequential, cancellable download queue powered by yt-dlp."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import yt_dlp

from .ffmpeg import find_ffmpeg
from .media import normalize_url
from .options import DownloadOptions, OptionsError, build_ydl_options
from .utils import friendly_ytdlp_error, human_duration, human_size, strip_ansi

log = logging.getLogger(__name__)

_TEMP_SUFFIXES = {".part", ".ytdl", ".temp", ".tmp"}
_MEDIA_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".avi",
    ".flv",
    ".ts",
    ".mp3",
    ".m4a",
    ".flac",
    ".wav",
    ".opus",
    ".ogg",
    ".aac",
}


class DownloadCancelled(Exception):
    pass


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def active(self) -> bool:
        return self in (JobStatus.DOWNLOADING, JobStatus.PROCESSING)


@dataclass(frozen=True)
class JobSnapshot:
    id: str
    url: str
    title: str
    mode: str
    status: JobStatus
    percent: float
    speed: str
    eta: str
    size: str
    stage: str
    error: str
    file_paths: tuple[str, ...]
    created_at: float


@dataclass
class DownloadJob:
    id: str
    url: str
    options: DownloadOptions
    title: str = ""
    status: JobStatus = JobStatus.QUEUED
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    size: str = ""
    stage: str = "Queued"
    error: str = ""
    file_paths: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    last_emit: float = field(default=0.0, repr=False)

    @property
    def mode(self) -> str:
        return self.options.mode

    def snapshot(self) -> JobSnapshot:
        return JobSnapshot(
            id=self.id,
            url=self.url,
            title=self.title or self.url,
            mode=self.mode,
            status=self.status,
            percent=max(0.0, min(100.0, self.percent)),
            speed=self.speed,
            eta=self.eta,
            size=self.size,
            stage=self.stage,
            error=self.error,
            file_paths=tuple(self.file_paths),
            created_at=self.created_at,
        )


class _YdlLogger:
    def __init__(self, sink):
        self._sink = sink

    def debug(self, message: str) -> None:
        text = strip_ansi(str(message)).strip()
        if text and not text.startswith("[debug] "):
            self._sink("debug", text)

    def info(self, message: str) -> None:
        text = strip_ansi(str(message)).strip()
        if text:
            self._sink("info", text)

    def warning(self, message: str) -> None:
        text = strip_ansi(str(message)).strip()
        if text:
            self._sink("warning", text)

    def error(self, message: str) -> None:
        text = strip_ansi(str(message)).strip()
        if text:
            self._sink("error", text)


def _postprocessor_label(name: str) -> str:
    labels = {
        "Merger": "Merging video and audio...",
        "ExtractAudio": "Converting audio...",
        "VideoRemuxer": "Remuxing video...",
        "VideoConvertor": "Converting video...",
        "Metadata": "Writing metadata and chapters...",
        "EmbedThumbnail": "Embedding thumbnail...",
        "EmbedSubtitle": "Embedding subtitles...",
        "ModifyChapters": "Applying SponsorBlock...",
        "MoveFiles": "Finalizing files...",
        "MoveFilesAfterDownload": "Finalizing files...",
        "FixupM3u8": "Finalizing stream...",
        "FixupM4a": "Finalizing audio...",
    }
    return labels.get(name, f"Running {name}...")


def _collect_output_paths(info: dict | None, fallbacks: list[str]) -> list[str]:
    found: list[str] = []

    def add(value: object) -> None:
        if not isinstance(value, str) or not value:
            return
        path = Path(value)
        if path.suffix.lower() in _TEMP_SUFFIXES:
            return
        if path.is_file():
            found.append(str(path.resolve()))

    def visit(entry: object) -> None:
        if not isinstance(entry, dict):
            return
        requested = entry.get("requested_downloads")
        if isinstance(requested, list):
            for item in requested:
                if isinstance(item, dict):
                    add(item.get("filepath") or item.get("_filename"))
        add(entry.get("filepath"))
        entries = entry.get("entries")
        if isinstance(entries, (list, tuple)):
            for child in entries:
                visit(child)

    visit(info)
    for fallback in fallbacks:
        add(fallback)

    unique: list[str] = []
    seen: set[str] = set()
    for path in found:
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _recent_media_files(folder: Path, since: float) -> list[str]:
    try:
        files = [
            path
            for path in folder.rglob("*")
            if path.is_file()
            and path.suffix.lower() in _MEDIA_SUFFIXES
            and path.stat().st_mtime >= since - 3
        ]
    except OSError:
        return []

    def modified(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    files.sort(key=modified, reverse=True)
    return [str(path.resolve()) for path in files[:20]]


class DownloadManager:
    """Runs queued jobs on one background thread and emits UI-safe snapshots."""

    def __init__(self, ffmpeg_provider=find_ffmpeg):
        self.events: Queue[dict[str, Any]] = Queue()
        self._ffmpeg_provider = ffmpeg_provider
        self._jobs: dict[str, DownloadJob] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._worker: threading.Thread | None = None
        self._shutdown = False
        self._current_id: str | None = None
        self._idle_announced = True

    # ------------------------------------------------------------------ events

    def _emit(self, event: dict[str, Any]) -> None:
        self.events.put(event)

    def _emit_job(self, job: DownloadJob) -> None:
        self._emit({"type": "job", "job": job.snapshot()})

    def _emit_log(self, level: str, message: str) -> None:
        self._emit({"type": "log", "level": level, "message": message})

    def _emit_queue_state(self) -> None:
        with self._lock:
            queued = sum(
                1 for job in self._jobs.values() if job.status == JobStatus.QUEUED
            )
            active = self._current_id is not None
            current = self._current_id
        self._emit(
            {
                "type": "queue_state",
                "queued": queued,
                "active": active,
                "current_id": current,
            }
        )

    def _announce_idle(self) -> None:
        if not self._idle_announced:
            self._idle_announced = True
            self._emit_queue_state()

    def _announce_busy(self) -> None:
        if self._idle_announced:
            self._idle_announced = False
            self._emit_queue_state()

    def _notify(self, title: str, message: str) -> None:
        self._emit({"type": "notify", "title": title, "message": message})

    # ------------------------------------------------------------------ public

    def add_job(
        self,
        url: str,
        options: DownloadOptions,
        *,
        title: str = "",
        auto_start: bool = True,
    ) -> JobSnapshot:
        normalized = normalize_url(url)
        if not normalized:
            raise ValueError("Enter a valid http(s) URL.")
        job = DownloadJob(
            id=uuid.uuid4().hex,
            url=normalized,
            options=options,
            title=title.strip(),
        )
        with self._condition:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._emit_job(job)
            self._emit_queue_state()
            self._ensure_worker_locked()
            if auto_start:
                self._condition.notify_all()
        return job.snapshot()

    def start(self) -> None:
        with self._condition:
            self._ensure_worker_locked()
            self._condition.notify_all()

    def retry_job(self, job_id: str) -> bool:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.status not in (
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            ):
                return False
            job.status = JobStatus.QUEUED
            job.stage = "Queued for retry"
            job.percent = 0.0
            job.speed = ""
            job.eta = ""
            job.size = ""
            job.error = ""
            job.file_paths = []
            job.cancel_event = threading.Event()
            job.last_emit = 0.0
            self._emit_job(job)
            self._emit_queue_state()
            self._ensure_worker_locked()
            self._condition.notify_all()
            return True

    def cancel_job(self, job_id: str) -> bool:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.stage = "Cancelled before starting"
                self._emit_job(job)
                self._emit_queue_state()
                return True
            if job.status.active:
                job.cancel_event.set()
                job.stage = "Cancelling..."
                self._emit_job(job)
                return True
            return False

    def remove_job(self, job_id: str) -> bool:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.status.active:
                return False
            self._jobs.pop(job_id, None)
            if job_id in self._order:
                self._order.remove(job_id)
            self._emit({"type": "job_removed", "id": job_id})
            self._emit_queue_state()
            return True

    def clear_finished(self) -> int:
        with self._condition:
            removable = [
                job.id
                for job in self._jobs.values()
                if job.status
                in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
            ]
            for job_id in removable:
                self._jobs.pop(job_id, None)
                if job_id in self._order:
                    self._order.remove(job_id)
                self._emit({"type": "job_removed", "id": job_id})
            self._emit_queue_state()
            return len(removable)

    def snapshots(self) -> list[JobSnapshot]:
        with self._lock:
            return [self._jobs[job_id].snapshot() for job_id in self._order]

    def has_unfinished_jobs(self) -> bool:
        with self._lock:
            return any(
                job.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.PROCESSING)
                for job in self._jobs.values()
            )

    def shutdown(self) -> None:
        with self._condition:
            self._shutdown = True
            job = self._jobs.get(self._current_id or "")
            if job is not None:
                job.cancel_event.set()
            self._condition.notify_all()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=5)

    # ------------------------------------------------------------------ worker

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._shutdown = False
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="ydl-studio-downloader",
            daemon=True,
        )
        self._worker.start()

    def _next_queued_locked(self) -> DownloadJob | None:
        for job_id in self._order:
            job = self._jobs.get(job_id)
            if job is not None and job.status == JobStatus.QUEUED:
                return job
        return None

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._shutdown:
                    job = self._next_queued_locked()
                    if job is not None:
                        break
                    self._announce_idle()
                    self._condition.wait(timeout=1.0)
                if self._shutdown:
                    return
                self._current_id = job.id
                job.status = JobStatus.DOWNLOADING
                job.stage = "Starting yt-dlp..."
                job.percent = 0.0
                job.cancel_event.clear()
                self._announce_busy()
                self._emit_job(job)

            try:
                self._execute_job(job)
            except OptionsError as exc:
                self._finish(job, JobStatus.FAILED, str(exc))
            except DownloadCancelled:
                self._finish(job, JobStatus.CANCELLED, "Cancelled")
            except Exception as exc:
                log.exception("Unexpected download failure for %s", job.url)
                self._finish(job, JobStatus.FAILED, friendly_ytdlp_error(exc))
            finally:
                with self._condition:
                    self._current_id = None
                    self._emit_queue_state()
                    self._condition.notify_all()

    def _execute_job(self, job: DownloadJob) -> None:
        started = time.time()
        ffmpeg_info = self._ffmpeg_provider()
        fallback_paths: list[str] = []

        def sink(level: str, message: str) -> None:
            self._emit_log(level, message)

        def progress_hook(data: dict) -> None:
            if job.cancel_event.is_set():
                raise DownloadCancelled()
            info = data.get("info_dict") or {}
            status = data.get("status")
            with self._condition:
                if not job.title:
                    job.title = str(info.get("title") or "")
                if status == "downloading":
                    total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                    downloaded = data.get("downloaded_bytes") or 0
                    if total:
                        item_percent = downloaded * 100.0 / total
                    else:
                        item_percent = job.percent
                    index = info.get("playlist_index")
                    count = info.get("n_entries") or info.get("playlist_count")
                    if isinstance(index, int) and isinstance(count, int) and count > 0:
                        job.percent = ((index - 1) + item_percent / 100.0) / count * 100.0
                        job.stage = f"Item {index} of {count}"
                    else:
                        job.percent = item_percent
                        job.stage = "Downloading"
                    speed = data.get("speed")
                    job.speed = (
                        f"{human_size(speed)}/s" if isinstance(speed, (int, float)) and speed else ""
                    )
                    eta = data.get("eta")
                    job.eta = human_duration(eta) if eta else ""
                    job.size = (
                        f"{human_size(downloaded)} / {human_size(total)}"
                        if total
                        else human_size(downloaded)
                    )
                elif status == "finished":
                    filename = data.get("filename")
                    if isinstance(filename, str) and filename:
                        fallback_paths.append(filename)
                    index = info.get("playlist_index")
                    count = info.get("n_entries") or info.get("playlist_count")
                    if isinstance(index, int) and isinstance(count, int) and count > 0:
                        job.percent = index / count * 100.0
                    job.speed = ""
                    job.eta = ""
                    job.stage = "Processing media..."
                else:
                    return
                now = time.monotonic()
                should_emit = status in ("finished",) or now - job.last_emit >= 0.15
                if should_emit:
                    job.last_emit = now
                    job.status = (
                        JobStatus.PROCESSING
                        if status == "finished"
                        else JobStatus.DOWNLOADING
                    )
                    self._emit_job(job)

        def postprocessor_hook(data: dict) -> None:
            info = data.get("info_dict") or {}
            name = str(data.get("postprocessor") or "")
            if data.get("status") == "started":
                with self._condition:
                    job.stage = _postprocessor_label(name)
                    self._emit_job(job)
            elif data.get("status") == "finished":
                filepath = info.get("filepath")
                if isinstance(filepath, str) and filepath:
                    fallback_paths.append(filepath)
                with self._condition:
                    job.stage = _postprocessor_label(name)
                    self._emit_job(job)

        if job.cancel_event.is_set():
            raise DownloadCancelled()

        logger = _YdlLogger(sink)
        ydl_opts, warnings = build_ydl_options(
            job.options,
            ffmpeg_info=ffmpeg_info,
            progress_hook=progress_hook,
            postprocessor_hook=postprocessor_hook,
            logger=logger,
        )
        for warning in warnings:
            self._emit_log("warning", warning)

        self._emit_log("info", f"Starting download: {job.url}")
        self._emit_log("info", f"Saving to: {job.options.output_dir}")
        if ffmpeg_info.found:
            self._emit_log("info", f"Using FFmpeg: {ffmpeg_info.path}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(job.url, download=True)

        paths = _collect_output_paths(info if isinstance(info, dict) else None, fallback_paths)
        if not paths:
            paths = _recent_media_files(Path(job.options.output_dir).expanduser(), started)
            if paths:
                self._emit_log(
                    "warning",
                    "yt-dlp did not report an output path; using the newest media file instead.",
                )

        title = job.title
        if isinstance(info, dict) and info.get("title"):
            title = str(info["title"])

        if paths:
            for path in paths:
                self._emit_log("info", f"Saved: {path}")
            self._finish(job, JobStatus.COMPLETED, "", paths=paths, title=title)
        elif job.cancel_event.is_set():
            self._finish(job, JobStatus.CANCELLED, "Cancelled")
        else:
            self._emit_log(
                "warning",
                "The download finished, but no output file could be located. "
                "Check the output folder and filename template.",
            )
            self._finish(job, JobStatus.COMPLETED, "", paths=[], title=title)

    def _finish(
        self,
        job: DownloadJob,
        status: JobStatus,
        error: str = "",
        *,
        paths: list[str] | None = None,
        title: str | None = None,
    ) -> None:
        with self._condition:
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                return
            job.status = status
            job.error = error
            job.speed = ""
            job.eta = ""
            if paths is not None:
                job.file_paths = paths
            if title:
                job.title = title
            if status == JobStatus.COMPLETED:
                job.percent = 100.0
                job.stage = "Completed"
            elif status == JobStatus.CANCELLED:
                job.stage = "Cancelled"
                job.percent = min(job.percent, 99.0)
            else:
                job.stage = "Failed"
            snapshot = job.snapshot()
            self._emit({"type": "job", "job": snapshot})
            self._emit_queue_state()
            if status == JobStatus.COMPLETED:
                count = len(snapshot.file_paths)
                detail = f"{count} files saved." if count > 1 else "Saved to your output folder."
                self._notify("Download complete", f"{snapshot.title}\n{detail}")
            elif status == JobStatus.FAILED:
                self._notify("Download failed", f"{snapshot.title}\n{error[:200]}")
        log.info("Job %s finished with status %s", job.id, status.value)


def drain_events(manager: DownloadManager, limit: int = 200) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for _ in range(limit):
        try:
            events.append(manager.events.get_nowait())
        except Empty:
            break
    return events
