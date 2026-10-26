"""End-to-end runs of the real download path against a loopback HTTP server.

yt-dlp and the queue are used unmodified; only the "site" is local. Nothing in
here touches the internet, so the suite stays runnable on an offline CI box.
"""

from __future__ import annotations

import http.server
import shutil
import socket
import sys
import threading
import time
from functools import partial
from pathlib import Path

import pytest
from helpers import NO_FFMPEG, SAMPLE_MP4, make_options

from ydl_studio.queue import DownloadManager, JobStatus, drain_events

PAYLOAD = SAMPLE_MP4.read_bytes()
CHUNK = 1024
CHUNK_DELAY = 0.3


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path.startswith("/slow"):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            for offset in range(0, len(PAYLOAD), CHUNK):
                self.wfile.write(PAYLOAD[offset : offset + CHUNK])
                self.wfile.flush()
                time.sleep(CHUNK_DELAY)
            return
        super().do_GET()


class QuietServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        # Cancelling a download closes the socket mid-response; that is the
        # behaviour under test, not a server fault worth a traceback.
        if not isinstance(sys.exc_info()[1], OSError):
            super().handle_error(request, client_address)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    shutil.copyfile(SAMPLE_MP4, root / "sample.mp4")
    handler = partial(QuietHandler, directory=str(root))
    httpd = QuietServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, name="test-http", daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def wait_for_terminal(mgr: DownloadManager, job_id: str, timeout=90.0):
    deadline = time.monotonic() + timeout
    events: list[dict] = []
    while time.monotonic() < deadline:
        events.extend(drain_events(mgr, limit=500))
        snapshot = next((s for s in mgr.snapshots() if s.id == job_id), None)
        if snapshot and snapshot.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ):
            time.sleep(0.1)
            events.extend(drain_events(mgr, limit=500))
            return snapshot, events
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def run(manager, url, options, timeout=90.0):
    job_id = manager.add_job(url, options).id
    return wait_for_terminal(manager, job_id, timeout)


# -------------------------------------------------------------- happy path


def test_a_direct_media_url_downloads_and_verifies_bytes(server, tmp_path) -> None:
    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        snapshot, events = run(mgr, f"{server}/sample.mp4", make_options(output_dir=str(tmp_path)))
        assert snapshot.status is JobStatus.COMPLETED
        assert snapshot.percent == 100.0
        assert len(snapshot.file_paths) == 1
        saved = Path(snapshot.file_paths[0])
        assert saved.is_file(), saved
        assert saved.read_bytes() == PAYLOAD
        assert saved.suffix == ".mp4"

        messages = " | ".join(event["message"] for event in events if event["type"] == "log")
        assert "Starting download" in messages
        assert f"Saved: {saved}" in messages
        assert any(event["type"] == "notify" for event in events)
    finally:
        mgr.shutdown()


def test_the_filename_template_decides_what_lands_on_disk(server, tmp_path) -> None:
    options = make_options(
        output_dir=str(tmp_path),
        filename_template="%(title)s.%(ext)s",
    )
    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        snapshot, _ = run(mgr, f"{server}/sample.mp4", options)
        assert sorted(path.name for path in tmp_path.iterdir()) == ["sample.mp4"]
        assert Path(snapshot.file_paths[0]).name == "sample.mp4"
    finally:
        mgr.shutdown()


def test_the_subfolder_template_creates_the_directory(server, tmp_path) -> None:
    options = make_options(
        output_dir=str(tmp_path),
        filename_template="clips/%(title)s.%(ext)s",
    )
    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        snapshot, _ = run(mgr, f"{server}/sample.mp4", options)
        assert snapshot.status is JobStatus.COMPLETED
        assert Path(snapshot.file_paths[0]).parent.name == "clips"
    finally:
        mgr.shutdown()


def test_progress_is_published_to_the_ui_as_it_downloads(server, tmp_path) -> None:
    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        job_id = mgr.add_job(f"{server}/slow.mp4", make_options(output_dir=str(tmp_path))).id
        percentages: list[float] = []
        stages: set[str] = set()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            for event in drain_events(mgr, limit=500):
                if event["type"] == "job" and event["job"].id == job_id:
                    percentages.append(event["job"].percent)
                    stages.add(event["job"].stage)
            current = next(s for s in mgr.snapshots() if s.id == job_id)
            if current.status is JobStatus.COMPLETED:
                break
            time.sleep(0.02)
        assert current.status is JobStatus.COMPLETED
        assert any(value > 0 for value in percentages), percentages
        assert max(percentages) <= 100.0
        assert "Downloading" in stages
    finally:
        mgr.shutdown()


def test_several_urls_run_one_after_the_other(server, tmp_path) -> None:
    options = make_options(output_dir=str(tmp_path), filename_template="%(title)s-%(id)s.%(ext)s")
    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        first = mgr.add_job(f"{server}/sample.mp4", options, title="first").id
        second = mgr.add_job(f"{server}/slow.mp4", options, title="second").id
        for job_id in (first, second):
            snapshot, _ = wait_for_terminal(mgr, job_id)
            assert snapshot.status is JobStatus.COMPLETED, snapshot.error
        assert len(list(tmp_path.glob("*.mp4"))) == 2
        assert mgr.has_unfinished_jobs() is False
    finally:
        mgr.shutdown()


def test_a_cancelled_queued_job_never_reaches_the_server(server, tmp_path) -> None:
    options = make_options(output_dir=str(tmp_path))
    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        running = mgr.add_job(f"{server}/slow.mp4", options).id
        skipped = mgr.add_job(f"{server}/sample.mp4", options).id
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = next(s for s in mgr.snapshots() if s.id == running)
            if current.status.active and current.percent > 0:
                break
            time.sleep(0.02)

        assert mgr.cancel_job(skipped) is True
        snapshot, _ = wait_for_terminal(mgr, skipped, timeout=60)
        assert snapshot.status is JobStatus.CANCELLED
        assert snapshot.stage == "Cancelled before starting"

        finished, _ = wait_for_terminal(mgr, running, timeout=60)
        assert finished.status in (JobStatus.COMPLETED, JobStatus.CANCELLED)
        # Only the job that actually ran may leave a file behind.
        assert not (tmp_path / "sample.mp4").exists()
    finally:
        mgr.shutdown()


# ------------------------------------------------------------ error routes


def test_a_missing_file_fails_with_the_server_message(server, tmp_path) -> None:
    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        snapshot, events = run(mgr, f"{server}/nope.mp4", make_options(output_dir=str(tmp_path)))
        assert snapshot.status is JobStatus.FAILED
        assert snapshot.error
        assert "404" in snapshot.error
        assert snapshot.file_paths == ()
        assert [event["title"] for event in events if event["type"] == "notify"] == [
            "Download failed"
        ]
        assert list(tmp_path.iterdir()) == []
    finally:
        mgr.shutdown()


def test_a_dead_port_fails_cleanly(tmp_path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]

    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        snapshot, events = run(
            mgr, f"http://127.0.0.1:{free_port}/sample.mp4", make_options(output_dir=str(tmp_path))
        )
        assert snapshot.status is JobStatus.FAILED
        assert snapshot.error
        assert any(event["type"] == "notify" for event in events)
    finally:
        mgr.shutdown()


def test_an_unreachable_host_does_not_hang_the_queue(tmp_path) -> None:
    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        snapshot, _ = run(
            mgr, "http://192.0.2.1:9/clip.mp4", make_options(output_dir=str(tmp_path)), timeout=120
        )
        assert snapshot.status is JobStatus.FAILED
    finally:
        mgr.shutdown()


# --------------------------------------------------------------- cancelling


def test_cancelling_a_slow_download_marks_the_job_cancelled(server, tmp_path) -> None:
    mgr = DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)
    try:
        job_id = mgr.add_job(f"{server}/slow.mp4", make_options(output_dir=str(tmp_path))).id
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = next(s for s in mgr.snapshots() if s.id == job_id)
            if current.status.active and current.percent > 0:
                break
            time.sleep(0.02)
        assert current.percent > 0, "the download never got underway"

        assert mgr.cancel_job(job_id) is True
        snapshot, events = wait_for_terminal(mgr, job_id, timeout=60)
        assert snapshot.status is JobStatus.CANCELLED
        assert snapshot.percent < 100.0
        assert not list(tmp_path.glob("*.mp4")), "a partial file must not be published"
        assert not any(
            event["type"] == "notify" and event["title"] == "Download complete"
            for event in events
        )
    finally:
        mgr.shutdown()
