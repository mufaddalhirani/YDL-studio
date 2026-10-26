"""The Downloads, History, and Console pages."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from . import theme as t
from .config import AUDIO_FORMATS, HistoryEntry
from .ffmpeg import FFmpegInfo
from .media import parse_urls
from .queue import JobSnapshot, JobStatus
from .ui_labels import (
    AUDIO_BITRATE_LABELS,
    QUALITY_CHOICES,
    QUALITY_FROM_LABEL,
    QUALITY_LABEL_FROM_VALUE,
    SPONSORBLOCK_LABEL_FROM_VALUE,
    SUBTITLE_LABEL_FROM_VALUE,
)
from .utils import human_size
from .widgets import (
    BatchDialog,
    EmptyState,
    HistoryRow,
    QueueRow,
    SectionCard,
    SegmentedControl,
    option_menu,
    primary_button,
    secondary_button,
    shorten_path,
    switch,
    truncate,
)

if TYPE_CHECKING:
    from .app import App

def _message_color(kind: str) -> t.Color:
    return {
        "success": t.SUCCESS_TEXT,
        "warning": t.WARNING_TEXT,
        "error": t.DANGER_TEXT,
    }.get(kind, t.MUTED)


class DownloadsTab:
    def __init__(self, master, app: App):
        self.app = app
        self.frame = ctk.CTkFrame(master, fg_color="transparent")
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(3, weight=1)

        self._rows: dict[str, QueueRow] = {}
        self._clipboard_url = ""
        self._empty: EmptyState | None = None

        self.mode_var = tk.StringVar(value="Video")
        self.quality_var = tk.StringVar(value="Best available")
        self.container_var = tk.StringVar(value="MP4")
        self.audio_format_var = tk.StringVar(value="MP3")
        self.bitrate_var = tk.StringVar(value="320 kbps")

        self._build_header()
        self._build_composer()
        self._build_queue()
        self.sync_from_settings()
        for snapshot in self.app.manager.snapshots():
            self._upsert_row(snapshot)
        self.refresh_queue_meta()

    # ----------------------------------------------------------------- layout

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Downloads",
            font=t.font(24, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Queue links from YouTube and thousands of other sites supported by yt-dlp.",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        secondary_button(
            header,
            "Open output folder",
            self.app.open_downloads_folder,
            width=142,
            height=32,
        ).grid(row=0, column=1, rowspan=2, sticky="e")

    def _build_composer(self) -> None:
        card = SectionCard(
            self.frame,
            "New download",
            "One link or a whole batch. Playlist links are handled automatically.",
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        body = card.body

        url_row = ctk.CTkFrame(body, fg_color="transparent")
        url_row.grid(row=0, column=0, sticky="ew")
        url_row.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            url_row,
            height=42,
            corner_radius=10,
            border_width=1,
            fg_color=t.PANEL_ALT,
            border_color=t.BORDER,
            text_color=t.TEXT,
            placeholder_text="Paste a video, playlist, or channel link",
            placeholder_text_color=t.SUBTLE,
            font=t.font(13),
        )
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", self._add_from_entry)
        self.url_entry.bind("<KeyRelease>", lambda _event: self._update_add_state())
        secondary_button(url_row, "Paste", self._paste, width=66, height=42).grid(
            row=0, column=1, padx=(8, 0)
        )
        secondary_button(url_row, "Batch", self._open_batch, width=66, height=42).grid(
            row=0, column=2, padx=(8, 0)
        )
        self.add_button = primary_button(
            url_row,
            "Add to queue",
            self._add_from_entry,
            width=126,
            height=42,
        )
        self.add_button.configure(state="disabled")
        self.add_button.grid(row=0, column=3, padx=(8, 0))

        self.message_label = ctk.CTkLabel(
            body,
            text="",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
            justify="left",
            wraplength=780,
        )
        self.message_label.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        self.clipboard_bar = ctk.CTkFrame(body, fg_color=t.ACCENT_SOFT, corner_radius=9)
        self.clipboard_bar.grid_columnconfigure(0, weight=1)
        self.clipboard_label = ctk.CTkLabel(
            self.clipboard_bar,
            text="",
            font=t.font(11),
            text_color=t.ACCENT_TEXT,
            anchor="w",
            justify="left",
            wraplength=540,
        )
        self.clipboard_label.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=8)
        ctk.CTkButton(
            self.clipboard_bar,
            text="Use link",
            width=76,
            height=26,
            corner_radius=7,
            font=t.font(11, "bold"),
            fg_color="transparent",
            hover_color=t.PANEL_ALT,
            text_color=t.ACCENT_TEXT,
            command=self._use_clipboard_link,
        ).grid(row=0, column=1, padx=(0, 4))
        ctk.CTkButton(
            self.clipboard_bar,
            text="×",
            width=24,
            height=24,
            corner_radius=6,
            font=t.font(13),
            fg_color="transparent",
            hover_color=t.PANEL_ALT,
            text_color=t.SUBTLE,
            command=self.hide_clipboard_suggestion,
        ).grid(row=0, column=2, padx=(0, 8))
        self.clipboard_bar.grid_remove()

        options = ctk.CTkFrame(body, fg_color="transparent")
        options.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        options.grid_columnconfigure(3, weight=1)

        def field(label: str, column: int, *, expand: bool = False) -> ctk.CTkFrame:
            group = ctk.CTkFrame(options, fg_color="transparent")
            group.grid(
                row=0,
                column=column,
                sticky="ew" if expand else "w",
                padx=(0, 10 if not expand else 0),
            )
            ctk.CTkLabel(
                group,
                text=label,
                font=t.font(10, "bold"),
                text_color=t.SUBTLE,
                anchor="w",
            ).pack(anchor="w", pady=(0, 4))
            return group

        mode_group = field("MODE", 0)
        self.mode_control = SegmentedControl(
            mode_group,
            ("Video", "Audio"),
            self.mode_var,
            command=self._mode_changed,
            width=176,
        )
        self.mode_control.pack(anchor="w")

        self.quality_group = field("QUALITY", 1)
        self.quality_menu = option_menu(
            self.quality_group,
            self.quality_var,
            [label for label, _value in QUALITY_CHOICES],
            width=142,
            command=self._quality_changed,
        )
        self.quality_menu.pack(anchor="w")

        self.bitrate_group = field("BITRATE", 1)
        self.bitrate_menu = option_menu(
            self.bitrate_group,
            self.bitrate_var,
            AUDIO_BITRATE_LABELS,
            width=118,
            command=self._bitrate_changed,
        )
        self.bitrate_menu.pack(anchor="w")
        self.bitrate_group.grid_remove()

        self.container_group = field("CONTAINER", 2)
        self.container_menu = option_menu(
            self.container_group,
            self.container_var,
            ("MP4", "MKV"),
            width=98,
            command=self._container_changed,
        )
        self.container_menu.pack(anchor="w")

        self.audio_format_group = field("AUDIO FORMAT", 2)
        self.audio_format_menu = option_menu(
            self.audio_format_group,
            self.audio_format_var,
            tuple(value.upper() for value in AUDIO_FORMATS),
            width=108,
            command=self._audio_format_changed,
        )
        self.audio_format_menu.pack(anchor="w")
        self.audio_format_group.grid_remove()

        folder_group = field("SAVE TO", 3, expand=True)
        self.folder_button = ctk.CTkButton(
            folder_group,
            text="",
            height=32,
            corner_radius=8,
            border_width=1,
            border_color=t.BORDER,
            fg_color=t.PANEL_ALT,
            hover_color=t.PANEL_SOFT,
            text_color=t.TEXT,
            font=t.font(11),
            anchor="w",
            command=self._choose_folder,
        )
        self.folder_button.pack(fill="x")

        self.summary_label = ctk.CTkLabel(
            body,
            text="",
            font=t.font(10),
            text_color=t.SUBTLE,
            anchor="w",
            justify="left",
            wraplength=780,
        )
        self.summary_label.grid(row=4, column=0, sticky="ew", pady=(10, 0))

        self.ffmpeg_banner = ctk.CTkFrame(body, fg_color=t.WARNING_SOFT, corner_radius=9)
        self.ffmpeg_banner.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.ffmpeg_banner,
            text=(
                "FFmpeg is not installed. Merging, audio conversion, subtitles, and "
                "SponsorBlock need it."
            ),
            font=t.font(11),
            text_color=t.WARNING_TEXT,
            anchor="w",
            justify="left",
            wraplength=560,
        ).grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=8)
        ctk.CTkButton(
            self.ffmpeg_banner,
            text="Set up",
            width=64,
            height=26,
            corner_radius=7,
            font=t.font(11, "bold"),
            fg_color="transparent",
            hover_color=t.PANEL_ALT,
            text_color=t.WARNING_TEXT,
            command=lambda: self.app.navigate("settings"),
        ).grid(row=0, column=1, padx=(0, 10))
        self.ffmpeg_banner.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self.ffmpeg_banner.grid_remove()

    def _build_queue(self) -> None:
        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="Queue",
            font=t.font(15, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.queue_meta = ctk.CTkLabel(
            header,
            text="",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
        )
        self.queue_meta.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.clear_finished_button = secondary_button(
            header,
            "Clear finished",
            self._clear_finished,
            width=104,
            height=28,
        )
        self.clear_finished_button.grid(row=0, column=2, sticky="e")

        self.queue_scroll = ctk.CTkScrollableFrame(
            self.frame,
            fg_color=t.PANEL,
            corner_radius=16,
            border_width=1,
            border_color=t.BORDER,
            scrollbar_button_color=t.BORDER,
            scrollbar_button_hover_color=t.SUBTLE,
        )
        self.queue_scroll.grid(row=3, column=0, sticky="nsew")
        self.queue_scroll.grid_columnconfigure(0, weight=1)

    # ---------------------------------------------------------------- actions

    def _paste(self) -> None:
        try:
            text = self.app.clipboard_get()
        except tk.TclError:
            return
        if not text.strip():
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text.strip())
        self.url_entry.focus_set()
        self._update_add_state()

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.app,
            title="Choose a download folder",
            initialdir=self.app.settings.download_dir,
            mustexist=False,
        )
        if selected:
            self.app.update_settings(download_dir=selected)

    def _open_batch(self) -> None:
        BatchDialog(
            self.app,
            initial_text=self.url_entry.get().strip(),
            on_submit=self._add_urls,
        )

    def _add_from_entry(self, _event=None) -> str | None:
        text = self.url_entry.get().strip()
        urls, invalid = parse_urls(text)
        if not urls:
            self._set_message(
                "Enter a full link, such as https://www.youtube.com/watch?v=..." if text
                else "Paste a link first.",
                "error",
            )
            return "break"
        self._add_urls(urls, invalid)
        self.url_entry.delete(0, "end")
        self._update_add_state()
        self.url_entry.focus_set()
        return "break"

    def _add_urls(self, urls: list[str], invalid: list[str] | None = None) -> None:
        added = 0
        errors: list[str] = []
        for url in urls:
            try:
                self.app.enqueue_url(url)
            except (ValueError, OSError) as exc:
                errors.append(str(exc))
            else:
                added += 1
        if added:
            message = f"Added {added} link{'s' if added != 1 else ''} to the queue."
            if invalid:
                preview = ", ".join(truncate(token, 24) for token in invalid[:3])
                message += f" Ignored {len(invalid)} invalid token(s): {preview}"
            self._set_message(message, "warning" if invalid else "success")
            self.hide_clipboard_suggestion()
            self.url_entry.delete(0, "end")
            self._update_add_state()
        if errors:
            self._set_message(errors[0], "error")
        self.refresh_queue_meta()

    def _update_add_state(self) -> None:
        has_text = bool(self.url_entry.get().strip())
        self.add_button.configure(state="normal" if has_text else "disabled")

    def _clear_finished(self) -> None:
        self.app.manager.clear_finished()
        self.refresh_queue_meta()

    def _set_message(self, text: str, kind: str = "muted") -> None:
        self.message_label.configure(
            text=truncate(text, 500),
            text_color=_message_color(kind),
        )

    # ------------------------------------------------------------ clipboard

    def suggest_clipboard(self, url: str) -> None:
        if not url or url == self.url_entry.get().strip():
            return
        self._clipboard_url = url
        self.clipboard_label.configure(
            text=f"Link detected in your clipboard: {truncate(url, 90)}"
        )
        self.clipboard_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _use_clipboard_link(self) -> None:
        if self._clipboard_url:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, self._clipboard_url)
            self.url_entry.focus_set()
            self._update_add_state()
        self.hide_clipboard_suggestion()

    def hide_clipboard_suggestion(self) -> None:
        self._clipboard_url = ""
        self.clipboard_bar.grid_remove()

    def current_url_text(self) -> str:
        return self.url_entry.get()

    def load_urls(self, urls: list[str]) -> None:
        if not urls:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, " ".join(urls))
        self._update_add_state()
        self.url_entry.focus_set()

    # -------------------------------------------------------------- settings

    def _mode_changed(self, display: str) -> None:
        self.app.update_settings(mode="audio" if display == "Audio" else "video")

    def _quality_changed(self, display: str) -> None:
        self.app.update_settings(resolution=QUALITY_FROM_LABEL.get(display, "best"))

    def _container_changed(self, display: str) -> None:
        self.app.update_settings(container=display.lower())

    def _audio_format_changed(self, display: str) -> None:
        self.app.update_settings(audio_format=display.lower())

    def _bitrate_changed(self, display: str) -> None:
        value = display.split()[0]
        if value.isdigit():
            self.app.update_settings(audio_bitrate=value)

    def sync_from_settings(self) -> None:
        settings = self.app.settings
        self.mode_var.set("Audio" if settings.mode == "audio" else "Video")
        self.quality_var.set(
            QUALITY_LABEL_FROM_VALUE.get(settings.resolution, "Best available")
        )
        self.container_var.set(settings.container.upper())
        self.audio_format_var.set(settings.audio_format.upper())
        self.bitrate_var.set(f"{settings.audio_bitrate} kbps")
        self.folder_button.configure(text=shorten_path(settings.download_dir, 52))
        self._apply_mode_visibility()
        self._update_summary()
        self.update_ffmpeg_banner(self.app.ffmpeg_info)

    def _apply_mode_visibility(self) -> None:
        audio = self.mode_var.get() == "Audio"
        if audio:
            self.quality_group.grid_remove()
            self.container_group.grid_remove()
            self.bitrate_group.grid()
            self.audio_format_group.grid()
        else:
            self.bitrate_group.grid_remove()
            self.audio_format_group.grid_remove()
            self.quality_group.grid()
            self.container_group.grid()

    def _update_summary(self) -> None:
        settings = self.app.settings
        if settings.mode == "audio":
            parts = [settings.audio_format.upper()]
            if settings.audio_format in ("mp3", "m4a", "opus"):
                parts.append(f"{settings.audio_bitrate} kbps")
        else:
            parts = [settings.container.upper()]
            parts.append(
                QUALITY_LABEL_FROM_VALUE.get(settings.resolution, "Best available")
            )
            if settings.prefer_h264 and settings.container == "mp4":
                parts.append("H.264 preferred")
        if settings.subtitle_mode != "off" and settings.mode == "video":
            label = SUBTITLE_LABEL_FROM_VALUE.get(
                settings.subtitle_mode, settings.subtitle_mode
            )
            parts.append(f"Subtitles: {label.lower()} ({settings.subtitle_languages})")
        if settings.sponsorblock_mode != "off" and settings.mode == "video":
            label = SPONSORBLOCK_LABEL_FROM_VALUE.get(
                settings.sponsorblock_mode, settings.sponsorblock_mode
            )
            parts.append(f"SponsorBlock: {label.lower()}")
        if settings.playlist or settings.playlist_items:
            range_text = f" ({settings.playlist_items})" if settings.playlist_items else ""
            parts.append(f"Playlist{range_text}")
        if settings.cookies_browser != "None":
            parts.append(f"Cookies: {settings.cookies_browser}")
        elif settings.cookies_file:
            parts.append("Cookies: file")
        self.summary_label.configure(text="   ·   ".join(parts))

    def update_ffmpeg_banner(self, info: FFmpegInfo) -> None:
        if info.found:
            self.ffmpeg_banner.grid_remove()
        else:
            self.ffmpeg_banner.grid()

    # ---------------------------------------------------------------- queue

    def _upsert_row(self, snapshot: JobSnapshot) -> None:
        row = self._rows.get(snapshot.id)
        if row is not None:
            row.update_snapshot(snapshot)
            return
        if self._empty is not None:
            self._empty.grid_remove()
        row = QueueRow(
            self.queue_scroll,
            snapshot,
            on_cancel=self._cancel_job,
            on_retry=self._retry_job,
            on_remove=self._remove_job,
            on_open=self.app.open_file,
            on_reveal=self.app.reveal_file,
        )
        index = len(self._rows)
        self._rows[snapshot.id] = row
        row.grid(
            row=index,
            column=0,
            sticky="ew",
            padx=12,
            pady=(10 if index == 0 else 0, 10),
        )

    def update_job(self, snapshot: JobSnapshot) -> None:
        self._upsert_row(snapshot)
        self.refresh_queue_meta()

    def remove_job(self, job_id: str) -> None:
        row = self._rows.pop(job_id, None)
        if row is not None:
            row.destroy()
        self._reindex_rows()
        if not self._rows:
            self._show_empty_state()
        self.refresh_queue_meta()

    def _reindex_rows(self) -> None:
        for index, row in enumerate(self._rows.values()):
            row.grid_configure(
                row=index,
                column=0,
                sticky="ew",
                padx=12,
                pady=(10 if index == 0 else 0, 10),
            )

    def _show_empty_state(self) -> None:
        if self._empty is None:
            self._empty = EmptyState(
                self.queue_scroll,
                "Your queue is empty",
                "Paste a link above to start downloading. Use Batch to add several links at once.",
                icon="download",
                action_text="Add multiple links",
                action=self._open_batch,
            )
            self._empty.grid(row=0, column=0, sticky="ew", pady=(0, 12), padx=12)
        else:
            self._empty.grid()

    def _cancel_job(self, job_id: str) -> None:
        self.app.manager.cancel_job(job_id)

    def _retry_job(self, job_id: str) -> None:
        self.app.manager.retry_job(job_id)

    def _remove_job(self, job_id: str) -> None:
        self.app.manager.remove_job(job_id)

    def refresh_queue_meta(self) -> None:
        snapshots = self.app.manager.snapshots()
        active = sum(1 for item in snapshots if item.status.active)
        queued = sum(1 for item in snapshots if item.status == JobStatus.QUEUED)
        finished = sum(
            1
            for item in snapshots
            if item.status
            in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        )
        if not snapshots:
            text = "Nothing queued yet."
        else:
            parts = []
            if active:
                parts.append(f"{active} active")
            if queued:
                parts.append(f"{queued} waiting")
            if finished:
                parts.append(f"{finished} finished")
            text = "  ·  ".join(parts) + f"  ·  {len(snapshots)} total"
        self.queue_meta.configure(text=text)
        self.clear_finished_button.configure(state="normal" if finished else "disabled")
        if not self._rows:
            self._show_empty_state()


class HistoryTab:
    def __init__(self, master, app: App):
        self.app = app
        self.frame = ctk.CTkFrame(master, fg_color="transparent")
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(2, weight=1)
        self._rows: list[HistoryRow] = []
        self._extras: list[tk.Widget] = []
        self._limit = 60
        self._search_job: str | None = None
        self.search_var = tk.StringVar()
        self._build()
        self.search_var.trace_add("write", self._schedule_search)

    def _build(self) -> None:
        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="History",
            font=t.font(24, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Completed downloads, newest first. The files stay wherever you saved them.",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        secondary_button(
            header,
            "Open output folder",
            self.app.open_downloads_folder,
            width=142,
            height=32,
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        toolbar = ctk.CTkFrame(self.frame, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        toolbar.grid_columnconfigure(1, weight=1)
        self.search_entry = ctk.CTkEntry(
            toolbar,
            width=300,
            height=32,
            corner_radius=8,
            border_width=1,
            fg_color=t.PANEL,
            border_color=t.BORDER,
            text_color=t.TEXT,
            placeholder_text="Search titles and paths",
            placeholder_text_color=t.SUBTLE,
            font=t.font(12),
        )
        self.search_entry.grid(row=0, column=0, sticky="w")
        self.search_entry.bind("<KeyRelease>", self._on_search_typed)
        self.search_entry.bind("<Escape>", lambda _event: self._reset_search())
        self.summary_label = ctk.CTkLabel(
            toolbar,
            text="",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
        )
        self.summary_label.grid(row=0, column=1, sticky="w", padx=(12, 12))
        self.reset_search_button = secondary_button(
            toolbar,
            "Reset",
            self._reset_search,
            width=58,
            height=30,
        )
        self.reset_search_button.grid(row=0, column=2, padx=(0, 8))
        self.clear_button = secondary_button(
            toolbar,
            "Clear history",
            self._clear_history,
            width=104,
            height=30,
            text_color=t.DANGER_TEXT,
        )
        self.clear_button.grid(row=0, column=3)

        self.scroll = ctk.CTkScrollableFrame(
            self.frame,
            fg_color=t.PANEL,
            corner_radius=16,
            border_width=1,
            border_color=t.BORDER,
            scrollbar_button_color=t.BORDER,
            scrollbar_button_hover_color=t.SUBTLE,
        )
        self.scroll.grid(row=2, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

    def _schedule_search(self, *_args) -> None:
        self._limit = 60
        if self._search_job is not None:
            self.frame.after_cancel(self._search_job)
        self._search_job = self.frame.after(180, self.refresh)

    def _on_search_typed(self, _event=None) -> None:
        text = self.search_entry.get()
        if text != self.search_var.get():
            self.search_var.set(text)

    def _reset_search(self) -> None:
        self.search_entry.delete(0, "end")
        if self.search_var.get():
            self.search_var.set("")
        self.search_entry.focus_set()

    def on_show(self) -> None:
        self.refresh()

    def _load_more(self) -> None:
        self._limit += 60
        self.refresh()

    def refresh(self) -> None:
        self._search_job = None
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        for extra in self._extras:
            extra.destroy()
        self._extras.clear()

        entries = self.app.history_store.entries
        query = self.search_var.get().strip().lower()
        if query:
            filtered = [
                item
                for item in entries
                if query in item.title.lower()
                or query in item.file_path.lower()
                or query in item.url.lower()
            ]
        else:
            filtered = list(entries)

        total_size = sum(item.size_bytes for item in entries)
        if query:
            summary = f"{len(filtered)} of {len(entries)} matching"
        else:
            summary = f"{len(entries)} download{'s' if len(entries) != 1 else ''}"
        if entries:
            summary += f"  ·  {human_size(total_size)} recorded"
        self.summary_label.configure(text=summary)
        self.reset_search_button.configure(state="normal" if query else "disabled")
        self.clear_button.configure(state="normal" if entries else "disabled")

        if not entries:
            empty = EmptyState(
                self.scroll,
                "No downloads yet",
                "Finished downloads will appear here with quick access to the saved file.",
                icon="history",
                action_text="Start a download",
                action=lambda: self.app.navigate("downloads"),
            )
            empty.grid(row=0, column=0, sticky="ew", pady=(0, 12), padx=12)
            self._extras.append(empty)
            return

        if not filtered:
            empty = EmptyState(
                self.scroll,
                "No matches",
                f'Nothing in your history matches "{truncate(self.search_var.get(), 40)}".',
                icon="history",
                action_text="Reset search",
                action=self._reset_search,
            )
            empty.grid(row=0, column=0, sticky="ew", pady=(0, 12), padx=12)
            self._extras.append(empty)
            return

        for index, item in enumerate(filtered[: self._limit]):
            row = HistoryRow(
                self.scroll,
                title=item.title,
                meta=(
                    f"{item.completed_local()}   ·   {human_size(item.size_bytes)}"
                    f"   ·   {item.mode}"
                ),
                path=item.file_path,
                mode=item.mode,
                file_exists=Path(item.file_path).is_file(),
                on_open=lambda entry=item: self.app.open_file(entry.file_path),
                on_reveal=lambda entry=item: self.app.reveal_file(entry.file_path),
                on_requeue=lambda entry=item: self.app.requeue_url(entry.url),
                on_remove=lambda entry=item: self._remove_entry(entry),
            )
            row.grid(
                row=index,
                column=0,
                sticky="ew",
                padx=12,
                pady=(10 if index == 0 else 0, 8),
            )
            self._rows.append(row)

        remaining = len(filtered) - len(self._rows)
        if remaining > 0:
            button = secondary_button(
                self.scroll,
                f"Load {min(remaining, 60)} more of {remaining}",
                self._load_more,
                width=190,
                height=30,
            )
            button.grid(
                row=len(self._rows),
                column=0,
                pady=(2, 16),
                padx=12,
            )
            self._extras.append(button)

    def _remove_entry(self, entry: HistoryEntry) -> None:
        self.app.history_store.remove(entry.id)
        self.refresh()

    def _clear_history(self) -> None:
        if not self.app.history_store.entries:
            return
        confirmed = messagebox.askyesno(
            "Clear download history",
            "Remove every entry from the history list?\n\nThe downloaded files are not deleted.",
            parent=self.app,
        )
        if not confirmed:
            return
        self.app.history_store.clear()
        self.refresh()


class ConsoleTab:
    _MAX_LINES = 5000

    def __init__(self, master, app: App):
        self.app = app
        self.frame = ctk.CTkFrame(master, fg_color="transparent")
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)
        self.autoscroll_var = tk.BooleanVar(value=True)

        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Console",
            font=t.font(24, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Live output from the download engine. Useful when a site misbehaves.",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        switch(
            actions,
            self.autoscroll_var,
            text="Auto-scroll",
            width=90,
            font=t.font(11),
        ).pack(side="left", padx=(0, 12))
        secondary_button(actions, "Copy", self._copy, width=62, height=30).pack(
            side="left", padx=(0, 6)
        )
        secondary_button(actions, "Clear", self._clear, width=62, height=30).pack(side="left")

        self._box = ctk.CTkTextbox(
            self.frame,
            corner_radius=16,
            border_width=1,
            border_color=t.BORDER,
            fg_color=t.PANEL,
            text_color=t.TEXT,
            font=t.font(11, mono=True),
            scrollbar_button_color=t.BORDER,
            scrollbar_button_hover_color=t.SUBTLE,
            wrap="word",
        )
        self._box.grid(row=1, column=0, sticky="nsew")
        self._box.configure(state="disabled")
        self.apply_theme()
        self.append("info", "Console ready. Download activity will appear here.")

    def apply_theme(self) -> None:
        self._box.configure(text_color=t.TEXT)
        for tag, color in (
            ("info", t.TEXT),
            ("debug", t.SUBTLE),
            ("warning", t.WARNING_TEXT),
            ("error", t.DANGER_TEXT),
        ):
            self._box.tag_config(tag, foreground=t.resolve(color))

    def append(self, level: str, message: str) -> None:
        if not self._box.winfo_exists():
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        label = {"warning": "WARN", "error": "ERROR", "debug": "DEBUG"}.get(level, "INFO")
        text = str(message).rstrip()
        if not text:
            return
        text = text.replace("\n", "\n            ")
        line = f"[{timestamp}] {label:<5}  {text}\n"
        self._box.configure(state="normal")
        self._box.insert("end", line, level if level in ("debug", "warning", "error") else "info")
        try:
            line_count = int(self._box.index("end-1c").split(".")[0])
            if line_count > self._MAX_LINES:
                self._box.delete("1.0", f"{line_count - self._MAX_LINES + 800}.0")
        except (tk.TclError, ValueError):
            pass
        if self.autoscroll_var.get():
            self._box.see("end")
        self._box.configure(state="disabled")

    def _copy(self) -> None:
        content = self._box.get("1.0", "end-1c").strip()
        if not content:
            return
        self.app.clipboard_clear()
        self.app.clipboard_append(content)
        self.app.show_toast("Console copied", "The log is now on your clipboard.", kind="info")

    def _clear(self) -> None:
        self._box.configure(state="normal")
        self._box.delete("1.0", "end")
        self._box.configure(state="disabled")
        self.append("info", "Console cleared.")
