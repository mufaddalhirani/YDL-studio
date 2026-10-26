"""The Settings page."""

from __future__ import annotations

import re
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk
from yt_dlp.version import __version__ as YTDLP_VERSION

from . import __version__
from . import theme as t
from .config import (
    AUDIO_FORMATS,
    COOKIE_BROWSERS,
    DEFAULT_FILENAME_TEMPLATE,
    THEMES,
    AppSettings,
)
from .ffmpeg import (
    FFmpegInfo,
    can_auto_install,
    download_and_install_ffmpeg,
    install_from_executable,
    install_instructions,
    tools_dir,
)
from .options import OptionsError, parse_custom_arguments, validate_filename_template
from .ui_labels import (
    AUDIO_BITRATE_LABELS,
    QUALITY_CHOICES,
    QUALITY_FROM_LABEL,
    QUALITY_LABEL_FROM_VALUE,
    SPONSORBLOCK_CHOICES,
    SPONSORBLOCK_FROM_LABEL,
    SPONSORBLOCK_LABEL_FROM_VALUE,
    SUBTITLE_CHOICES,
    SUBTITLE_FROM_LABEL,
    SUBTITLE_LABEL_FROM_VALUE,
)
from .utils import human_size
from .widgets import (
    SectionCard,
    SegmentedControl,
    entry,
    option_menu,
    primary_button,
    secondary_button,
    shorten_path,
    switch,
)

if TYPE_CHECKING:
    from .app import App

_CATEGORY_HINT = "sponsor, selfpromo, interaction, intro, outro, preview, music_offtopic, poi_highlight, filler"


class SettingsTab:
    def __init__(self, master, app: App):
        self.app = app
        self.frame = ctk.CTkFrame(master, fg_color="transparent")
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        self._loading = True
        self._dirty = False
        self._vars: dict[str, tk.Variable] = {}
        self._section_index = 0
        self._install_queue: Queue | None = None
        self._installing = False
        self._progress_indeterminate = False
        self._cancel_install: threading.Event | None = None
        self._ffmpeg_info = FFmpegInfo(found=False)

        self._create_variables()
        self._build_header()
        self._build_scroll()
        self._build_sections()
        self._build_save_bar()
        self._load(self.app.settings)
        self.set_ffmpeg_info(self.app.ffmpeg_info)

    # ------------------------------------------------------------- variables

    def _string_var(self, name: str, value: str) -> tk.StringVar:
        variable = tk.StringVar(value=value)
        variable.trace_add("write", self._on_control_changed)
        self._vars[name] = variable
        return variable

    def _bool_var(self, name: str, value: bool) -> tk.BooleanVar:
        variable = tk.BooleanVar(value=value)
        variable.trace_add("write", self._on_control_changed)
        self._vars[name] = variable
        return variable

    def _create_variables(self) -> None:
        defaults = AppSettings()
        self.theme_var = self._string_var("theme", defaults.theme)
        self.download_dir_var = self._string_var("download_dir", defaults.download_dir)
        self.filename_template_var = self._string_var(
            "filename_template", defaults.filename_template
        )
        self.mode_var = self._string_var("mode", "Video")
        self.quality_var = self._string_var("quality", "Best available")
        self.container_var = self._string_var("container", defaults.container.upper())
        self.prefer_h264_var = self._bool_var("prefer_h264", defaults.prefer_h264)
        self.audio_format_var = self._string_var(
            "audio_format", defaults.audio_format.upper()
        )
        self.audio_bitrate_var = self._string_var(
            "audio_bitrate", f"{defaults.audio_bitrate} kbps"
        )
        self.embed_metadata_var = self._bool_var("embed_metadata", defaults.embed_metadata)
        self.embed_thumbnail_var = self._bool_var(
            "embed_thumbnail", defaults.embed_thumbnail
        )
        self.embed_chapters_var = self._bool_var("embed_chapters", defaults.embed_chapters)
        self.subtitle_mode_var = self._string_var("subtitle_mode", "Off")
        self.subtitle_languages_var = self._string_var(
            "subtitle_languages", defaults.subtitle_languages
        )
        self.include_auto_subs_var = self._bool_var(
            "include_auto_subs", defaults.include_auto_subs
        )
        self.sponsorblock_mode_var = self._string_var("sponsorblock_mode", "Off")
        self.sponsorblock_categories_var = self._string_var(
            "sponsorblock_categories", defaults.sponsorblock_categories
        )
        self.playlist_var = self._bool_var("playlist", defaults.playlist)
        self.playlist_items_var = self._string_var(
            "playlist_items", defaults.playlist_items
        )
        self.cookies_browser_var = self._string_var(
            "cookies_browser", defaults.cookies_browser
        )
        self.cookies_file_var = self._string_var("cookies_file", defaults.cookies_file)
        self.rate_limit_var = self._string_var("rate_limit_mbps", defaults.rate_limit_mbps)
        self.clipboard_watch_var = self._bool_var(
            "clipboard_watch", defaults.clipboard_watch
        )
        self.minimize_to_tray_var = self._bool_var(
            "minimize_to_tray", defaults.minimize_to_tray
        )
        self.notifications_var = self._bool_var(
            "notifications", defaults.notifications
        )

    # ----------------------------------------------------------------- layout

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Settings",
            font=t.font(24, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Defaults and behavior for new downloads. Changes apply after saving.",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        secondary_button(
            header,
            "Restore defaults",
            self._restore_defaults,
            width=124,
            height=32,
        ).grid(row=0, column=1, rowspan=2, sticky="e")

    def _build_scroll(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(
            self.frame,
            fg_color="transparent",
            scrollbar_button_color=t.BORDER,
            scrollbar_button_hover_color=t.SUBTLE,
        )
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

    def _build_save_bar(self) -> None:
        bar = ctk.CTkFrame(
            self.frame,
            fg_color=t.PANEL,
            border_width=1,
            border_color=t.BORDER,
            corner_radius=12,
        )
        bar.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        bar.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(
            bar,
            text="Changes apply to new downloads after saving.",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=16, pady=12)
        self.revert_button = secondary_button(
            bar, "Revert", self._revert, width=74, height=34
        )
        self.revert_button.grid(row=0, column=1, padx=(10, 8))
        self.save_button = primary_button(
            bar, "Save changes", self.save, width=118, height=34
        )
        self.save_button.grid(row=0, column=2, padx=(0, 12))

    def _section(self, title: str, subtitle: str = "") -> ctk.CTkFrame:
        card = SectionCard(self.scroll, title, subtitle)
        card.grid(
            row=self._section_index,
            column=0,
            sticky="ew",
            padx=2,
            pady=(0, 14),
        )
        self._section_index += 1
        return card.body

    def _text_row(self, parent, title: str, hint: str = "") -> ctk.CTkFrame:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 11))
        row.grid_columnconfigure(0, weight=1)
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            left,
            text=title,
            font=t.font(12, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).pack(anchor="w")
        if hint:
            ctk.CTkLabel(
                left,
                text=hint,
                font=t.font(10),
                text_color=t.MUTED,
                anchor="w",
                justify="left",
                wraplength=340,
            ).pack(anchor="w", pady=(1, 0))
        return row

    def _add_switch(self, parent, title: str, hint: str, variable: tk.BooleanVar) -> None:
        row = self._text_row(parent, title, hint)
        switch(row, variable).grid(row=0, column=1, sticky="e", padx=(20, 0))

    def _add_menu(
        self,
        parent,
        title: str,
        hint: str,
        variable: tk.StringVar,
        values,
        *,
        width: int = 170,
    ) -> ctk.CTkOptionMenu:
        row = self._text_row(parent, title, hint)
        menu = option_menu(row, variable, list(values), width=width)
        menu.grid(row=0, column=1, sticky="e", padx=(20, 0))
        return menu

    def _add_entry(
        self,
        parent,
        title: str,
        hint: str,
        variable: tk.StringVar,
        *,
        width: int = 260,
        placeholder: str = "",
    ) -> ctk.CTkEntry:
        row = self._text_row(parent, title, hint)
        field = entry(row, variable, width=width, placeholder=placeholder)
        field.grid(row=0, column=1, sticky="e", padx=(20, 0))
        return field

    def _build_sections(self) -> None:
        # General
        body = self._section("General", "Appearance and background behavior.")
        self._add_menu(
            body,
            "Theme",
            "Applies to the whole app after saving.",
            self.theme_var,
            THEMES,
            width=150,
        )
        self._add_switch(
            body,
            "Desktop notifications",
            "Notify when a download finishes or fails.",
            self.notifications_var,
        )
        self._add_switch(
            body,
            "Watch the clipboard",
            "Offer a suggestion when a supported link is copied. Never starts a download by itself.",
            self.clipboard_watch_var,
        )
        self._add_switch(
            body,
            "Close to the system tray",
            "Keep the app and active downloads running when the window is closed.",
            self.minimize_to_tray_var,
        )

        # Output
        body = self._section("Output", "Where finished files go and how they are named.")
        row = self._text_row(
            body,
            "Download folder",
            "New downloads are saved here. Subfolders follow the filename template.",
        )
        self.folder_button = ctk.CTkButton(
            row,
            text="",
            width=280,
            height=32,
            corner_radius=8,
            border_width=1,
            border_color=t.BORDER,
            fg_color=t.PANEL_ALT,
            hover_color=t.PANEL_SOFT,
            text_color=t.TEXT,
            font=t.font(11),
            anchor="w",
            command=self._choose_output_folder,
        )
        self.folder_button.grid(row=0, column=1, sticky="e", padx=(20, 0))

        row = self._text_row(
            body,
            "Filename template",
            'Placeholders include %(title)s, %(uploader)s, %(id)s, and %(ext)s. The template must keep %(ext)s.',
        )
        holder = ctk.CTkFrame(row, fg_color="transparent")
        holder.grid(row=0, column=1, sticky="e", padx=(20, 0))
        self.filename_entry = entry(
            holder, self.filename_template_var, width=244, height=32
        )
        self.filename_entry.pack(side="left")
        secondary_button(
            holder,
            "Default",
            lambda: self.filename_template_var.set(DEFAULT_FILENAME_TEMPLATE),
            width=64,
            height=32,
        ).pack(side="left", padx=(6, 0))

        row = self._text_row(
            body,
            "Folders",
            "Open the folders YDL Studio uses for downloads, settings, and logs.",
        )
        holder = ctk.CTkFrame(row, fg_color="transparent")
        holder.grid(row=0, column=1, sticky="e", padx=(20, 0))
        for label, command in (
            ("Output", self.app.open_downloads_folder),
            ("Settings", self.app.open_data_folder),
            ("Logs", self.app.open_log_folder),
        ):
            secondary_button(holder, label, command, width=72, height=32).pack(
                side="left", padx=(6, 0)
            )

        # Download defaults
        body = self._section(
            "Download defaults", "Starting point for every new link. You can override it per download."
        )
        row = self._text_row(
            body,
            "Default mode",
            "Video saves a complete media file. Audio extracts the soundtrack when FFmpeg is available.",
        )
        SegmentedControl(row, ("Video", "Audio"), self.mode_var, width=176).grid(
            row=0, column=1, sticky="e", padx=(20, 0)
        )
        self._add_menu(
            body,
            "Video quality",
            "Best available never caps the resolution. Used in video mode.",
            self.quality_var,
            [label for label, _value in QUALITY_CHOICES],
            width=158,
        )
        self._add_menu(
            body,
            "Video container",
            "MP4 is the most compatible choice. MKV is more flexible for odd codecs.",
            self.container_var,
            ("MP4", "MKV"),
            width=110,
        )
        self._add_switch(
            body,
            "Prefer H.264",
            "Choose H.264/MP4 sources for maximum compatibility. Falls back when a site has no H.264 stream.",
            self.prefer_h264_var,
        )
        self._add_menu(
            body,
            "Audio format",
            "Used in audio mode. Lossless formats ignore the bitrate setting.",
            self.audio_format_var,
            tuple(value.upper() for value in AUDIO_FORMATS),
            width=120,
        )
        self._add_menu(
            body,
            "Audio bitrate",
            "Used for MP3, M4A, and Opus. Higher values create larger files.",
            self.audio_bitrate_var,
            AUDIO_BITRATE_LABELS,
            width=120,
        )

        # Metadata
        body = self._section(
            "Metadata", "Details embedded into the final file. FFmpeg is required."
        )
        self._add_switch(
            body,
            "Embed title, artist, and date",
            "Write media tags so the file looks right in players.",
            self.embed_metadata_var,
        )
        self._add_switch(
            body,
            "Embed thumbnail",
            "Use the source thumbnail as cover art.",
            self.embed_thumbnail_var,
        )
        self._add_switch(
            body,
            "Embed chapters",
            "Keep chapter markers from the source.",
            self.embed_chapters_var,
        )

        # Subtitles
        body = self._section(
            "Subtitles", "Download subtitles in video mode. Embedding needs FFmpeg."
        )
        self._add_menu(
            body,
            "Subtitle handling",
            "Embed into the video container, save .srt files beside the video, or skip subtitles.",
            self.subtitle_mode_var,
            [label for label, _value in SUBTITLE_CHOICES],
            width=160,
        )
        self._add_entry(
            body,
            "Languages",
            "Comma-separated language codes such as en, es, ja, or all.",
            self.subtitle_languages_var,
            width=170,
            placeholder="en",
        )
        self._add_switch(
            body,
            "Include auto-generated subtitles",
            "Useful when the source has no authored subtitle track.",
            self.include_auto_subs_var,
        )

        # SponsorBlock
        body = self._section(
            "SponsorBlock",
            "Skip or mark sponsor segments using the public SponsorBlock database.",
        )
        self._add_menu(
            body,
            "SponsorBlock handling",
            "Mark segments as chapters or cut them out. Video mode and FFmpeg are required.",
            self.sponsorblock_mode_var,
            [label for label, _value in SPONSORBLOCK_CHOICES],
            width=160,
        )
        self._add_entry(
            body,
            "Categories",
            "Comma-separated segment types. Valid values: " + _CATEGORY_HINT + ".",
            self.sponsorblock_categories_var,
            width=260,
        )

        # Playlists
        body = self._section("Playlists", "Control what happens when a link belongs to a playlist.")
        self._add_switch(
            body,
            "Download full playlists",
            "When off, yt-dlp downloads only the selected video where the site allows it.",
            self.playlist_var,
        )
        self._add_entry(
            body,
            "Playlist items",
            'Optional range such as 1-5, 1,3,7, or 1:10. Leave empty for every item.',
            self.playlist_items_var,
            width=190,
            placeholder="1-10",
        )

        # Cookies and network
        body = self._section(
            "Cookies and network",
            "Cookies unlock private, members-only, or age-restricted media. Only use cookies for accounts you own.",
        )
        self._add_menu(
            body,
            "Read cookies from browser",
            "Close the browser if it locks its cookie database. Chrome and Edge may need it fully closed.",
            self.cookies_browser_var,
            COOKIE_BROWSERS,
            width=150,
        )
        row = self._text_row(
            body,
            "cookies.txt file",
            "Overrides browser cookies. Use Netscape cookie format from a browser extension.",
        )
        holder = ctk.CTkFrame(row, fg_color="transparent")
        holder.grid(row=0, column=1, sticky="e", padx=(20, 0))
        entry(holder, self.cookies_file_var, width=180, height=32).pack(side="left")
        secondary_button(
            holder, "Browse", self._choose_cookies_file, width=66, height=32
        ).pack(side="left", padx=(6, 0))
        secondary_button(
            holder,
            "Clear",
            lambda: self.cookies_file_var.set(""),
            width=52,
            height=32,
        ).pack(side="left", padx=(6, 0))

        self._add_entry(
            body,
            "Speed limit",
            "Maximum download speed in MB/s. Leave empty for unlimited.",
            self.rate_limit_var,
            width=110,
            placeholder="Unlimited",
        )

        # Advanced
        body = self._section(
            "Advanced", "Escape hatch for yt-dlp options that are not exposed in the app."
        )
        self._text_row(
            body,
            "Custom arguments",
            "Example: --geo-bypass --sleep-requests 0.5. Help, version, and update flags are blocked for safety.",
        )
        self.custom_args_box = ctk.CTkTextbox(
            body,
            height=78,
            corner_radius=8,
            border_width=1,
            border_color=t.BORDER,
            fg_color=t.PANEL_ALT,
            text_color=t.TEXT,
            font=t.font(11, mono=True),
            wrap="word",
        )
        self.custom_args_box.pack(fill="x", pady=(2, 2))
        self.custom_args_box.bind("<KeyRelease>", lambda _event: self._on_control_changed())

        # FFmpeg
        body = self._section(
            "FFmpeg", "Required for merging, audio conversion, subtitles, and SponsorBlock."
        )
        status_card = ctk.CTkFrame(
            body,
            fg_color=t.PANEL_ALT,
            corner_radius=10,
            border_width=1,
            border_color=t.BORDER,
        )
        status_card.pack(fill="x")
        status_card.grid_columnconfigure(1, weight=1)
        self.ffmpeg_dot = ctk.CTkLabel(
            status_card,
            text="",
            width=10,
            height=10,
            corner_radius=5,
            fg_color=t.WARNING,
        )
        self.ffmpeg_dot.grid(row=0, column=0, padx=(12, 8), pady=(12, 0), sticky="n")
        self.ffmpeg_title = ctk.CTkLabel(
            status_card,
            text="Checking FFmpeg…",
            font=t.font(12, "bold"),
            text_color=t.TEXT,
            anchor="w",
        )
        self.ffmpeg_title.grid(row=0, column=1, sticky="w", pady=(10, 0))
        self.ffmpeg_show_button = secondary_button(
            status_card,
            "Show folder",
            self._show_ffmpeg_folder,
            width=90,
            height=28,
        )
        self.ffmpeg_show_button.grid(row=0, column=2, sticky="e", padx=(8, 12), pady=(8, 0))
        self.ffmpeg_detail = ctk.CTkLabel(
            status_card,
            text="",
            font=t.font(10),
            text_color=t.MUTED,
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self.ffmpeg_detail.grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=(1, 11)
        )

        controls = ctk.CTkFrame(body, fg_color="transparent")
        controls.pack(fill="x", pady=(10, 0))
        self.ffmpeg_install_button = primary_button(
            controls,
            "Install automatically",
            self._install_ffmpeg,
            width=150,
            height=32,
        )
        self.ffmpeg_install_button.pack(side="left")
        if not can_auto_install():
            self.ffmpeg_install_button.configure(
                state="disabled", text="Automatic install (Windows)"
            )
        self.ffmpeg_pick_button = secondary_button(
            controls,
            "Use existing files…",
            self._pick_ffmpeg_files,
            width=144,
            height=32,
        )
        self.ffmpeg_pick_button.pack(side="left", padx=(8, 0))
        self.ffmpeg_cancel_button = secondary_button(
            controls,
            "Cancel install",
            self._cancel_ffmpeg_install,
            width=110,
            height=32,
            text_color=t.DANGER_TEXT,
        )
        self.ffmpeg_cancel_button.pack(side="left", padx=(8, 0))
        self.ffmpeg_cancel_button.pack_forget()

        self.ffmpeg_progress_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.ffmpeg_progress = ctk.CTkProgressBar(
            self.ffmpeg_progress_frame,
            height=6,
            corner_radius=3,
            fg_color=t.NEUTRAL_CHIP,
            progress_color=t.ACCENT,
        )
        self.ffmpeg_progress.pack(fill="x")
        self.ffmpeg_progress.set(0)
        self.ffmpeg_progress_label = ctk.CTkLabel(
            self.ffmpeg_progress_frame,
            text="",
            font=t.font(10),
            text_color=t.MUTED,
            anchor="w",
        )
        self.ffmpeg_progress_label.pack(fill="x", pady=(4, 0))
        self.ffmpeg_progress_frame.pack_forget()

        if not can_auto_install():
            ctk.CTkLabel(
                body,
                text=install_instructions(),
                font=t.font(10),
                text_color=t.MUTED,
                anchor="w",
            ).pack(fill="x", pady=(8, 0))

        # About
        body = self._section(
            "About", "YDL Studio is an independent, open-source desktop front end for yt-dlp."
        )
        ctk.CTkLabel(
            body,
            text=f"YDL Studio {__version__}",
            font=t.font(13, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            body,
            text=f"Powered by yt-dlp {YTDLP_VERSION} and FFmpeg. Released under the MIT License.",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
            justify="left",
            wraplength=650,
        ).pack(anchor="w", pady=(2, 0))
        links = ctk.CTkFrame(body, fg_color="transparent")
        links.pack(fill="x", pady=(10, 0))
        for label, url in (
            ("yt-dlp project", "https://github.com/yt-dlp/yt-dlp"),
            ("FFmpeg", "https://ffmpeg.org"),
            ("MIT License", "https://opensource.org/license/mit"),
        ):
            secondary_button(
                links,
                label,
                lambda target=url: self.app.open_url(target),
                width=106 if label != "FFmpeg" else 78,
                height=30,
            ).pack(side="left", padx=(0, 6))

    # ------------------------------------------------------------------ state

    def _load(self, settings: AppSettings, *, keep_dirty: bool = False) -> None:
        self._loading = True
        try:
            self.theme_var.set(settings.theme)
            self.download_dir_var.set(settings.download_dir)
            self.filename_template_var.set(settings.filename_template)
            self.mode_var.set("Audio" if settings.mode == "audio" else "Video")
            self.quality_var.set(
                QUALITY_LABEL_FROM_VALUE.get(settings.resolution, "Best available")
            )
            self.container_var.set(settings.container.upper())
            self.prefer_h264_var.set(settings.prefer_h264)
            self.audio_format_var.set(settings.audio_format.upper())
            self.audio_bitrate_var.set(f"{settings.audio_bitrate} kbps")
            self.embed_metadata_var.set(settings.embed_metadata)
            self.embed_thumbnail_var.set(settings.embed_thumbnail)
            self.embed_chapters_var.set(settings.embed_chapters)
            self.subtitle_mode_var.set(
                SUBTITLE_LABEL_FROM_VALUE.get(settings.subtitle_mode, "Off")
            )
            self.subtitle_languages_var.set(settings.subtitle_languages)
            self.include_auto_subs_var.set(settings.include_auto_subs)
            self.sponsorblock_mode_var.set(
                SPONSORBLOCK_LABEL_FROM_VALUE.get(settings.sponsorblock_mode, "Off")
            )
            self.sponsorblock_categories_var.set(settings.sponsorblock_categories)
            self.playlist_var.set(settings.playlist)
            self.playlist_items_var.set(settings.playlist_items)
            self.cookies_browser_var.set(settings.cookies_browser)
            self.cookies_file_var.set(settings.cookies_file)
            self.rate_limit_var.set(settings.rate_limit_mbps)
            self.clipboard_watch_var.set(settings.clipboard_watch)
            self.minimize_to_tray_var.set(settings.minimize_to_tray)
            self.notifications_var.set(settings.notifications)
            self.folder_button.configure(text=shorten_path(settings.download_dir, 46))
            self.custom_args_box.delete("1.0", "end")
            self.custom_args_box.insert("1.0", settings.custom_args)
        finally:
            self._loading = False
        if not keep_dirty:
            self._dirty = False
        self._update_save_bar()

    def _on_control_changed(self, *_args) -> None:
        if self._loading:
            return
        self._dirty = True
        self.folder_button.configure(text=shorten_path(self.download_dir_var.get(), 46))
        self._update_save_bar()

    def _update_save_bar(self) -> None:
        if self._dirty:
            self.status_label.configure(
                text="Unsaved changes. New downloads keep the current settings until you save.",
                text_color=t.WARNING_TEXT,
            )
            self.revert_button.configure(state="normal")
        else:
            self.status_label.configure(
                text="Changes apply to new downloads after saving.",
                text_color=t.MUTED,
            )
            self.revert_button.configure(state="disabled")

    def _set_status(self, text: str, color: t.Color) -> None:
        self.status_label.configure(text=text, text_color=color)

    def _restore_defaults(self) -> None:
        self._load(AppSettings())
        self._dirty = True
        self._update_save_bar()
        self._set_status(
            "Defaults loaded. Review them, then save to apply.",
            t.WARNING_TEXT,
        )

    def _revert(self) -> None:
        self._load(self.app.settings)
        self._set_status("Changes reverted.", t.MUTED)

    def _choose_output_folder(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.app,
            title="Choose a download folder",
            initialdir=self.download_dir_var.get() or str(Path.home()),
            mustexist=False,
        )
        if selected:
            self.download_dir_var.set(selected)

    def _choose_cookies_file(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.app,
            title="Choose a cookies.txt file",
            filetypes=[
                ("Cookie files", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self.cookies_file_var.set(selected)

    # ---------------------------------------------------------------- save

    def _collect(self) -> AppSettings:
        data = {
            "theme": self.theme_var.get(),
            "download_dir": self.download_dir_var.get(),
            "filename_template": self.filename_template_var.get(),
            "mode": "audio" if self.mode_var.get() == "Audio" else "video",
            "resolution": QUALITY_FROM_LABEL.get(self.quality_var.get(), "best"),
            "container": self.container_var.get().lower(),
            "prefer_h264": self.prefer_h264_var.get(),
            "audio_format": self.audio_format_var.get().lower(),
            "audio_bitrate": self.audio_bitrate_var.get().split()[0],
            "embed_metadata": self.embed_metadata_var.get(),
            "embed_thumbnail": self.embed_thumbnail_var.get(),
            "embed_chapters": self.embed_chapters_var.get(),
            "subtitle_mode": SUBTITLE_FROM_LABEL.get(self.subtitle_mode_var.get(), "off"),
            "subtitle_languages": self.subtitle_languages_var.get(),
            "include_auto_subs": self.include_auto_subs_var.get(),
            "sponsorblock_mode": SPONSORBLOCK_FROM_LABEL.get(
                self.sponsorblock_mode_var.get(), "off"
            ),
            "sponsorblock_categories": self.sponsorblock_categories_var.get(),
            "playlist": self.playlist_var.get(),
            "playlist_items": self.playlist_items_var.get(),
            "cookies_browser": self.cookies_browser_var.get(),
            "cookies_file": self.cookies_file_var.get(),
            "rate_limit_mbps": self.rate_limit_var.get(),
            "custom_args": self.custom_args_box.get("1.0", "end").strip(),
            "clipboard_watch": self.clipboard_watch_var.get(),
            "minimize_to_tray": self.minimize_to_tray_var.get(),
            "notifications": self.notifications_var.get(),
        }
        return AppSettings.from_dict(data)

    def _validate(self, settings: AppSettings) -> str:
        try:
            validate_filename_template(settings.filename_template)
            parse_custom_arguments(settings.custom_args)
            if settings.playlist_items and not re.fullmatch(
                r"[\d,\-:\s]+", settings.playlist_items
            ):
                raise OptionsError('Playlist items must look like "1-5", "1,3,7", or "1:10".')
            if settings.rate_limit_mbps:
                rate = float(settings.rate_limit_mbps)
                if rate <= 0:
                    raise OptionsError("The speed limit must be greater than zero.")
            if settings.cookies_file and not Path(settings.cookies_file).is_file():
                raise OptionsError(f"Cookies file not found: {settings.cookies_file}")
            folder = Path(settings.download_dir).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            if not folder.is_dir():
                raise OptionsError("The download folder is not a directory.")
        except (OptionsError, OSError, ValueError) as exc:
            return str(exc)
        return ""

    def save(self) -> bool:
        settings = self._collect()
        error = self._validate(settings)
        if error:
            self._set_status(error, t.DANGER_TEXT)
            self.app.show_toast("Settings not saved", error, kind="error")
            return False
        if not self.app.apply_settings(settings):
            self._set_status(
                "Settings changed for this session, but the settings file could not be written.",
                t.WARNING_TEXT,
            )
            return False
        self._load(settings)
        self._set_status(
            "Settings saved. New downloads will use these defaults.",
            t.SUCCESS_TEXT,
        )
        self.app.show_toast(
            "Settings saved",
            "New downloads will use the updated defaults.",
            kind="success",
        )
        return True

    def is_dirty(self) -> bool:
        return self._dirty

    def on_show(self) -> None:
        if not self._dirty:
            self._load(self.app.settings)
        self.set_ffmpeg_info(self.app.ffmpeg_info)

    def on_external_settings(self, settings: AppSettings) -> None:
        if not self._dirty:
            self._load(settings)

    # --------------------------------------------------------------- ffmpeg

    def set_ffmpeg_info(self, info: FFmpegInfo) -> None:
        self._ffmpeg_info = info
        if info.found:
            self.ffmpeg_dot.configure(fg_color=t.SUCCESS)
            version = f" {info.short_version}" if info.short_version else ""
            self.ffmpeg_title.configure(text=f"FFmpeg{version} is ready")
            self.ffmpeg_detail.configure(
                text=f"{info.source.title() if info.source else 'Detected'}  ·  {shorten_path(info.path or '', 74)}"
            )
            self.ffmpeg_show_button.grid()
            self.ffmpeg_install_button.configure(text="Reinstall or update")
        else:
            self.ffmpeg_dot.configure(fg_color=t.WARNING)
            self.ffmpeg_title.configure(text="FFmpeg was not found")
            self.ffmpeg_detail.configure(
                text=(
                    "Video merging, audio conversion, subtitles, thumbnails, and "
                    "SponsorBlock need FFmpeg. Install it here or place ffmpeg.exe on PATH."
                )
            )
            self.ffmpeg_show_button.grid_remove()
            self.ffmpeg_install_button.configure(text="Install automatically")

    def _show_ffmpeg_folder(self) -> None:
        target = (
            Path(self._ffmpeg_info.path)
            if self._ffmpeg_info.found and self._ffmpeg_info.path
            else tools_dir()
        )
        if self._ffmpeg_info.found and self._ffmpeg_info.path:
            t.reveal_path(target)
        else:
            target.mkdir(parents=True, exist_ok=True)
            t.open_path(target)

    def _set_ffmpeg_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.ffmpeg_install_button.configure(state=state)
        self.ffmpeg_pick_button.configure(state=state)
        if not can_auto_install():
            self.ffmpeg_install_button.configure(state="disabled")
        if enabled:
            self.ffmpeg_cancel_button.pack_forget()
            self.ffmpeg_cancel_button.configure(state="normal")
        else:
            self.ffmpeg_cancel_button.configure(state="normal")
            self.ffmpeg_cancel_button.pack(side="left", padx=(8, 0))

    def _install_ffmpeg(self) -> None:
        if self._installing:
            return
        if not can_auto_install():
            messagebox.showinfo(
                "Install FFmpeg",
                install_instructions(),
                parent=self.app,
            )
            return
        confirmed = messagebox.askyesno(
            "Install FFmpeg",
            (
                "Download the latest FFmpeg essentials build now?\n\n"
                "The archive is roughly 30–100 MB depending on the source. It is downloaded "
                "from gyan.dev or the official codexffmpeg GitHub releases, verified, and "
                "stored inside the YDL Studio settings folder."
            ),
            parent=self.app,
        )
        if not confirmed:
            return
        self._begin_install("Preparing the FFmpeg download…")
        cancel = threading.Event()
        self._cancel_install = cancel
        threading.Thread(
            target=self._install_worker,
            args=(cancel, None),
            name="ydl-studio-ffmpeg",
            daemon=True,
        ).start()

    def _pick_ffmpeg_files(self) -> None:
        if self._installing:
            return
        selected = filedialog.askopenfilename(
            parent=self.app,
            title="Select ffmpeg.exe",
            filetypes=[
                ("FFmpeg executable", "ffmpeg.exe"),
                ("Executables", "*.exe"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        self._begin_install("Copying FFmpeg into YDL Studio…")
        cancel = threading.Event()
        self._cancel_install = cancel
        threading.Thread(
            target=self._install_worker,
            args=(cancel, selected),
            name="ydl-studio-ffmpeg",
            daemon=True,
        ).start()

    def _begin_install(self, status: str) -> None:
        self._installing = True
        self._install_queue = Queue()
        self._set_ffmpeg_controls_enabled(False)
        self.ffmpeg_progress_frame.pack(fill="x", pady=(10, 0))
        self._progress_indeterminate = True
        self.ffmpeg_progress.configure(mode="indeterminate")
        self.ffmpeg_progress.start()
        self.ffmpeg_progress_label.configure(text=status)
        self._set_status(status, t.MUTED)
        self._poll_install()

    def _install_worker(self, cancel: threading.Event, source_path: str | None) -> None:
        queue = self._install_queue
        if queue is None:
            return
        try:
            if source_path:
                info = install_from_executable(source_path)
            else:
                info = download_and_install_ffmpeg(
                    progress_callback=lambda done, total: queue.put(
                        ("progress", done, total)
                    ),
                    status_callback=lambda message: queue.put(("status", message)),
                    cancel_event=cancel,
                )
            queue.put(("done", info))
        except Exception as exc:  # surfaced in the UI; never raised on the worker
            queue.put(("error", str(exc)))

    def _poll_install(self) -> None:
        if not self.frame.winfo_exists():
            return
        queue = self._install_queue
        if queue is None:
            return
        should_continue = True
        while True:
            try:
                event = queue.get_nowait()
            except Empty:
                break
            kind = event[0]
            if kind == "status":
                self.ffmpeg_progress_label.configure(text=str(event[1]))
                self._set_status(str(event[1]), t.MUTED)
            elif kind == "progress":
                done, total = event[1], event[2]
                if total:
                    if self._progress_indeterminate:
                        self.ffmpeg_progress.stop()
                        self.ffmpeg_progress.configure(mode="determinate")
                        self._progress_indeterminate = False
                    self.ffmpeg_progress.set(min(1.0, done / total))
                    self.ffmpeg_progress_label.configure(
                        text=f"Downloading FFmpeg… {human_size(done)} of {human_size(total)}"
                    )
                else:
                    self.ffmpeg_progress_label.configure(
                        text=f"Downloading FFmpeg… {human_size(done)}"
                    )
            elif kind == "done":
                self._finish_install_success(event[1])
                should_continue = False
                break
            elif kind == "error":
                self._finish_install_error(str(event[1]))
                should_continue = False
                break
        if self._installing and should_continue:
            self.frame.after(140, self._poll_install)

    def _finish_install_success(self, info: FFmpegInfo) -> None:
        self._installing = False
        self._progress_indeterminate = False
        self._cancel_install = None
        self.ffmpeg_progress.stop()
        self.ffmpeg_progress.configure(mode="determinate")
        self.ffmpeg_progress_frame.pack_forget()
        self._set_ffmpeg_controls_enabled(True)
        self.app.refresh_ffmpeg(info)
        self._set_status(
            f"FFmpeg{' ' + info.short_version if info.short_version else ''} is ready.",
            t.SUCCESS_TEXT,
        )
        self.app.show_toast(
            "FFmpeg installed",
            "Merging, audio conversion, and media extras are now available.",
            kind="success",
        )

    def _finish_install_error(self, message: str) -> None:
        self._installing = False
        self._progress_indeterminate = False
        self._cancel_install = None
        self.ffmpeg_progress.stop()
        self.ffmpeg_progress_frame.pack_forget()
        self._set_ffmpeg_controls_enabled(True)
        cancelled = "cancel" in message.lower()
        self._set_status(
            "FFmpeg installation was cancelled." if cancelled else message,
            t.MUTED if cancelled else t.DANGER_TEXT,
        )
        if not cancelled:
            self.app.show_toast("FFmpeg was not installed", message, kind="error")

    def _cancel_ffmpeg_install(self) -> None:
        if self._cancel_install is not None:
            self._cancel_install.set()
            self._set_status("Cancelling the FFmpeg installation…", t.MUTED)
            self.ffmpeg_cancel_button.configure(state="disabled")
            self.frame.after(300, self._reset_cancel_button)

    def _reset_cancel_button(self) -> None:
        if self.frame.winfo_exists():
            self.ffmpeg_cancel_button.configure(state="normal")

    def cancel_pending_work(self) -> None:
        if self._cancel_install is not None:
            self._cancel_install.set()
