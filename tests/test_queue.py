"""The download queue: state machine, event stream and output-path recovery.

yt-dlp itself is never invoked here. ``ScriptedManager`` replaces the single
method that touches the network so the rest of the manager can be exercised
deterministically, including from its worker thread.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from helpers import NO_FFMPEG, make_options

from ydl_studio.options import OptionsError
from ydl_studio.queue import (
    DownloadCancelled,
    DownloadJob,
    DownloadManager,
    JobSnapshot,
    JobStatus,
    _collect_output_paths,
    _postprocessor_label,
    _recent_media_files,
    _YdlLogger,
    drain_events,
)

URL = "https://example.com/watch?v=abc"


@pytest.fixture
def manager() -> DownloadManager:
    # No job is added, so no worker thread is started and the assertions below
    # describe the manager exactly as the UI sees it between actions.
    return DownloadManager(ffmpeg_provider=lambda: NO_FFMPEG)


class ScriptedManager(DownloadManager):
    """A manager whose downloads are supplied by the test."""

    def __init__(self, behavior=None) -> None:
        super().__init__(ffmpeg_provider=lambda: NO_FFMPEG)
        self._behavior = behavior or (lambda job: (JobStatus.COMPLETED, ""))
        self.ran: list[str] = []

    def _execute_job(self, job) -> None:
        self.ran.append(job.id)
        outcome = self._behavior(job)
        if outcome is not None:
            self._finish(job, *outcome)


def wait_for_status(mgr, job_id, *statuses, timeout=3.0) -> JobSnapshot:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for snapshot in mgr.snapshots():
            if snapshot.id == job_id and snapshot.status in statuses:
                return snapshot
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {[s.value for s in statuses]}")


# ------------------------------------------------------------- job lifecycle


def test_add_job_rejects_an_unusable_url(manager) -> None:
    with pytest.raises(ValueError, match="valid"):
        manager.add_job("not a url", make_options())


def test_add_job_normalises_and_snapshots(manager) -> None:
    snapshot = manager.add_job(f"  {URL}  ", make_options(), title="  My Title ")
    assert snapshot.url == URL
    assert snapshot.title == "My Title"
    assert snapshot.status is JobStatus.QUEUED
    assert snapshot.stage == "Queued"


def test_snapshot_falls_back_to_the_url_as_a_title(manager) -> None:
    assert manager.add_job(URL, make_options()).title == URL


def test_events_describe_the_new_job_and_queue(manager) -> None:
    manager.add_job(URL, make_options())
    events = drain_events(manager)
    job_events = [event for event in events if event["type"] == "job"]
    states = [event for event in events if event["type"] == "queue_state"]
    assert len(job_events) == 1
    assert job_events[0]["job"].url == URL
    assert states[-1] == {
        "type": "queue_state",
        "queued": 1,
        "active": False,
        "current_id": None,
    }


def test_snapshots_keep_insertion_order(manager) -> None:
    first = manager.add_job(URL, make_options())
    second = manager.add_job("https://example.org/other", make_options())
    assert [snapshot.id for snapshot in manager.snapshots()] == [first.id, second.id]


def test_a_scripted_job_completes_and_notifies() -> None:
    mgr = ScriptedManager()
    job_id = mgr.add_job(URL, make_options()).id
    assert wait_for_status(mgr, job_id, JobStatus.COMPLETED).percent == 100.0
    assert mgr.ran == [job_id]

    events = drain_events(mgr)
    notices = [event for event in events if event["type"] == "notify"]
    assert [event["title"] for event in notices] == ["Download complete"]


def test_a_scripted_job_reports_failure_to_the_ui() -> None:
    def boom(job):
        return (JobStatus.FAILED, "network went away")

    mgr = ScriptedManager(boom)
    job_id = mgr.add_job(URL, make_options()).id
    snapshot = wait_for_status(mgr, job_id, JobStatus.FAILED)
    assert snapshot.error == "network went away"
    assert snapshot.stage == "Failed"
    notices = [event for event in drain_events(mgr) if event["type"] == "notify"]
    assert [event["title"] for event in notices] == ["Download failed"]
    assert "network went away" in notices[0]["message"]


@pytest.mark.parametrize(
    ("exception", "stage", "error"),
    [
        (OptionsError("bad template"), "Failed", "bad template"),
        (DownloadCancelled(), "Cancelled", "Cancelled"),
        (RuntimeError("nope"), "Failed", None),
    ],
)
def test_worker_turns_exceptions_into_terminal_states(
    exception, stage, error
) -> None:
    def blow_up(job):
        raise exception

    mgr = ScriptedManager(blow_up)
    job_id = mgr.add_job(URL, make_options()).id
    snapshot = wait_for_status(mgr, job_id, JobStatus.FAILED, JobStatus.CANCELLED)
    assert snapshot.stage == stage
    if error is not None:
        assert snapshot.error == error


def test_cancel_a_queued_job_that_is_waiting_behind_another() -> None:
    def slow(job):
        time.sleep(0.4)
        return (JobStatus.COMPLETED, "")

    mgr = ScriptedManager(slow)
    first = mgr.add_job("https://example.com/first", make_options()).id
    second = mgr.add_job("https://example.com/second", make_options()).id
    wait_for_status(mgr, first, JobStatus.DOWNLOADING)

    assert mgr.cancel_job(second) is True
    assert wait_for_status(mgr, second, JobStatus.CANCELLED).stage == (
        "Cancelled before starting"
    )
    wait_for_status(mgr, first, JobStatus.COMPLETED)
    assert mgr.ran == [first], "a cancelled job must never reach the worker"


def test_shutdown_cancels_the_in_flight_job_and_joins_the_worker() -> None:
    def block(job):
        # The real download loop polls this event, so shutdown has to set it.
        job.cancel_event.wait(5)
        return (JobStatus.CANCELLED, "Cancelled")

    mgr = ScriptedManager(block)
    job_id = mgr.add_job(URL, make_options()).id
    wait_for_status(mgr, job_id, JobStatus.DOWNLOADING)

    mgr.shutdown()
    assert mgr._worker is None or not mgr._worker.is_alive()
    assert wait_for_status(mgr, job_id, JobStatus.CANCELLED).status is (
        JobStatus.CANCELLED
    )


# ------------------------------------------------------------ queue actions


def make_job(status: JobStatus, **overrides) -> DownloadJob:
    job = DownloadJob(id=overrides.pop("id", "job-1"), url=URL, options=make_options())
    job.status = status
    for key, value in overrides.items():
        setattr(job, key, value)
    return job


def register(manager, *jobs) -> None:
    for job in jobs:
        manager._jobs[job.id] = job
        manager._order.append(job.id)


def test_cancel_queued_job_short_circuits(manager) -> None:
    job = make_job(JobStatus.QUEUED)
    register(manager, job)
    assert manager.cancel_job(job.id) is True
    assert (job.status, job.stage) == (JobStatus.CANCELLED, "Cancelled before starting")
    assert not job.cancel_event.is_set()


def test_cancel_running_job_signals_the_event(manager) -> None:
    job = make_job(JobStatus.DOWNLOADING)
    register(manager, job)
    assert manager.cancel_job(job.id) is True
    assert job.cancel_event.is_set()
    assert job.stage == "Cancelling..."


@pytest.mark.parametrize("status", [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED])
def test_cancel_on_a_finished_job_is_a_no_op(manager, status) -> None:
    job = make_job(status)
    register(manager, job)
    assert manager.cancel_job(job.id) is False
    assert manager.cancel_job("missing") is False


def test_retry_only_accepts_failed_or_cancelled(manager) -> None:
    failed = make_job(JobStatus.FAILED, error="boom", percent=63.5, file_paths=["x"])
    done = make_job(JobStatus.COMPLETED, id="job-2")
    register(manager, failed, done)

    assert manager.retry_job("missing") is False
    assert manager.retry_job(done.id) is False

    assert manager.retry_job(failed.id) is True
    assert failed.status is JobStatus.QUEUED
    assert (failed.error, failed.percent, failed.file_paths) == ("", 0.0, [])
    assert failed.stage == "Queued for retry"


def test_retry_gives_the_job_a_fresh_cancel_event(manager) -> None:
    job = make_job(JobStatus.CANCELLED)
    job.cancel_event.set()
    register(manager, job)
    manager.retry_job(job.id)
    assert not job.cancel_event.is_set()


def test_remove_refuses_an_active_job(manager) -> None:
    running = make_job(JobStatus.PROCESSING)
    done = make_job(JobStatus.COMPLETED, id="job-2")
    register(manager, running, done)

    assert manager.remove_job(running.id) is False
    assert manager.snapshots()[0].id == running.id
    assert manager.remove_job("missing") is False

    assert manager.remove_job(done.id) is True
    assert [snapshot.id for snapshot in manager.snapshots()] == [running.id]
    removed = [event for event in drain_events(manager) if event["type"] == "job_removed"]
    assert [event["id"] for event in removed] == [done.id]


def test_clear_finished_keeps_the_work_left_to_do(manager) -> None:
    register(
        manager,
        make_job(JobStatus.COMPLETED),
        make_job(JobStatus.FAILED, id="job-2"),
        make_job(JobStatus.CANCELLED, id="job-3"),
        make_job(JobStatus.QUEUED, id="job-4"),
        make_job(JobStatus.DOWNLOADING, id="job-5"),
    )
    assert manager.clear_finished() == 3
    assert [snapshot.id for snapshot in manager.snapshots()] == ["job-4", "job-5"]
    assert manager.has_unfinished_jobs() is True


def test_has_unfinished_jobs_and_clear_on_an_empty_queue(manager) -> None:
    assert manager.has_unfinished_jobs() is False
    assert manager.clear_finished() == 0
    register(manager, make_job(JobStatus.COMPLETED))
    assert manager.has_unfinished_jobs() is False
    assert manager.clear_finished() == 1


# ------------------------------------------------------------------- status


@pytest.mark.parametrize(
    ("status", "active"),
    [
        (JobStatus.QUEUED, False),
        (JobStatus.DOWNLOADING, True),
        (JobStatus.PROCESSING, True),
        (JobStatus.COMPLETED, False),
        (JobStatus.FAILED, False),
        (JobStatus.CANCELLED, False),
    ],
)
def test_active_only_covers_in_flight_states(status: JobStatus, active: bool) -> None:
    assert status.active is active
    assert status == status.value


def test_snapshot_clamps_the_percentage(manager) -> None:
    job = make_job(JobStatus.DOWNLOADING, percent=-4.0)
    assert job.snapshot().percent == 0.0
    job.percent = 118.0
    assert job.snapshot().percent == 100.0


# --------------------------------------------------------------- log labels


def test_postprocessor_labels_are_humanised() -> None:
    assert _postprocessor_label("Merger") == "Merging video and audio..."
    assert _postprocessor_label("ExtractAudio") == "Converting audio..."
    assert _postprocessor_label("FixupM4a") == "Finalizing audio..."
    assert _postprocessor_label("WeirdOne") == "Running WeirdOne..."


# ------------------------------------------------------------ output paths


def test_collect_paths_reads_requested_downloads(tmp_path) -> None:
    keep = tmp_path / "video.mp4"
    keep.write_bytes(b"x")
    partial = tmp_path / "video.mp4.part"
    partial.write_bytes(b"x")

    info = {
        "requested_downloads": [
            {"filepath": str(keep)},
            {"_filename": str(partial)},
            {"filepath": str(tmp_path / "missing.mkv")},
        ]
    }
    assert _collect_output_paths(info, []) == [str(keep.resolve())]


def test_collect_paths_walks_playlist_entries(tmp_path) -> None:
    one = tmp_path / "one.mp4"
    two = tmp_path / "two.mp4"
    one.write_bytes(b"1")
    two.write_bytes(b"2")
    info = {
        "entries": [
            {"requested_downloads": [{"filepath": str(one)}]},
            {"filepath": str(two)},
            "not-a-dict",
        ]
    }
    assert _collect_output_paths(info, []) == [str(one.resolve()), str(two.resolve())]


def test_collect_paths_deduplicates_across_case_and_fallbacks(tmp_path) -> None:
    one = tmp_path / "one.mp4"
    one.write_bytes(b"1")
    paths = _collect_output_paths(
        {"filepath": str(one)}, [str(one), str(one).upper(), ""]
    )
    assert len(paths) == 1


def test_collect_paths_only_falls_back_to_existing_files(tmp_path) -> None:
    missing = tmp_path / "gone.mp4"
    assert _collect_output_paths(None, [str(missing)]) == []
    missing.write_bytes(b"x")
    assert _collect_output_paths(None, [str(missing)]) == [str(missing.resolve())]


def test_recent_media_files_finds_new_media_only(tmp_path) -> None:
    fresh = tmp_path / "fresh.mp4"
    audio = tmp_path / "track.mp3"
    notes = tmp_path / "notes.txt"
    nested = tmp_path / "sub" / "nested.mkv"
    nested.parent.mkdir()
    for path in (fresh, audio, notes, nested):
        path.write_bytes(b"x")

    found = [Path(path).name for path in _recent_media_files(tmp_path, time.time() - 60)]
    assert sorted(found) == ["fresh.mp4", "nested.mkv", "track.mp3"]


def test_recent_media_files_respects_the_time_window(tmp_path) -> None:
    old = tmp_path / "old.mp4"
    old.write_bytes(b"x")
    long_ago = time.time() - 400
    os.utime(old, (long_ago, long_ago))
    assert _recent_media_files(tmp_path, time.time()) == []
    assert len(_recent_media_files(tmp_path, long_ago - 10)) == 1


def test_recent_media_files_returns_the_newest_first_and_caps(tmp_path) -> None:
    moment = time.time()
    for index in range(25):
        path = tmp_path / f"clip{index:02d}.mp4"
        path.write_bytes(b"x")
        stamp = moment - index
        os.utime(path, (stamp, stamp))

    found = _recent_media_files(tmp_path, moment - 300)
    assert len(found) == 20
    assert Path(found[0]).name == "clip00.mp4"
    assert Path(found[-1]).name == "clip19.mp4"


def test_recent_media_files_survives_an_unreadable_folder() -> None:
    assert _recent_media_files(Path("Z:/does/not/exist"), time.time() - 60) == []


# ------------------------------------------------------------------- logger


def collect_sink():
    messages: list[tuple[str, str]] = []
    return messages, lambda level, text: messages.append((level, text))


def test_logger_forwards_each_severity() -> None:
    messages, sink = collect_sink()
    logger = _YdlLogger(sink)
    logger.info("Downloading")
    logger.warning("Cannot be embedded")
    logger.error("Giving up")
    assert messages == [
        ("info", "Downloading"),
        ("warning", "Cannot be embedded"),
        ("error", "Giving up"),
    ]


def test_logger_strips_ansi_and_drops_noise() -> None:
    messages, sink = collect_sink()
    logger = _YdlLogger(sink)
    logger.info("\x1b[0;32m[download]\x1b[0m  42.0%")
    logger.debug("[debug] lazy_extractors")
    logger.debug("real message")
    logger.info("   ")
    assert messages == [("info", "[download]  42.0%"), ("debug", "real message")]


def test_logger_converts_any_payload_to_text() -> None:
    messages, sink = collect_sink()
    _YdlLogger(sink).info(42)
    assert messages == [("info", "42")]


# ------------------------------------------------------------- event pump


def test_drain_events_respects_the_limit(manager) -> None:
    for index in range(5):
        manager._emit({"type": "log", "level": "info", "message": str(index)})
    assert len(drain_events(manager, limit=3)) == 3
    assert len(drain_events(manager)) == 2
    assert drain_events(manager) == []


def test_finish_is_idempotent_once_terminal(manager) -> None:
    job = make_job(JobStatus.COMPLETED, percent=100.0)
    register(manager, job)
    drain_events(manager)

    manager._finish(job, JobStatus.FAILED, "too late")
    assert job.status is JobStatus.COMPLETED
    assert job.error == ""
    assert drain_events(manager) == []


def test_finish_cancels_at_most_at_99_percent(manager) -> None:
    job = make_job(JobStatus.DOWNLOADING, percent=100.0)
    register(manager, job)
    manager._finish(job, JobStatus.CANCELLED, "Cancelled")
    assert job.percent == 99.0
    assert job.stage == "Cancelled"


def test_completion_notice_counts_multiple_files(manager) -> None:
    job = make_job(JobStatus.DOWNLOADING, title="Big Buck Bunny")
    register(manager, job)
    manager._finish(job, JobStatus.COMPLETED, "", paths=["a.mp4", "b.mp4"])
    notices = [event for event in drain_events(manager) if event["type"] == "notify"]
    assert notices[0]["message"] == "Big Buck Bunny\n2 files saved."


def test_completion_notice_uses_one_wording_for_a_single_file(manager) -> None:
    job = make_job(JobStatus.DOWNLOADING, title="One")
    register(manager, job)
    manager._finish(job, JobStatus.COMPLETED, "", paths=["a.mp4"])
    notices = [event for event in drain_events(manager) if event["type"] == "notify"]
    assert notices[0]["message"].endswith("Saved to your output folder.")


def test_finish_records_the_title_found_while_downloading(manager) -> None:
    job = make_job(JobStatus.PROCESSING, title="")
    register(manager, job)
    manager._finish(job, JobStatus.COMPLETED, "", paths=["a.mp4"], title="Real Title")
    assert job.title == "Real Title"


def test_failure_notice_is_truncated(manager) -> None:
    job = make_job(JobStatus.DOWNLOADING, title="Long")
    register(manager, job)
    manager._finish(job, JobStatus.FAILED, "x" * 500)
    notices = [event for event in drain_events(manager) if event["type"] == "notify"]
    assert len(notices[0]["message"]) < 300


def test_options_are_carried_through_to_the_worker() -> None:
    captured = {}

    def remember(job):
        captured["options"] = job.options
        return (JobStatus.COMPLETED, "")

    options = make_options(mode="audio", container="mkv")
    mgr = ScriptedManager(remember)
    job_id = mgr.add_job(URL, options).id
    snapshot = wait_for_status(mgr, job_id, JobStatus.COMPLETED)
    assert captured["options"] is options
    assert snapshot.mode == "audio"
