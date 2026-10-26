"""Main application window, navigation, and background event handling."""

from __future__ import annotations

import logging
import os
import time
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from . import APP_NAME, __version__
from . import theme as t
from .config import (
    AppSettings,
    HistoryEntry,
    HistoryStore,
    app_data_dir,
    load_settings,
    log_dir,
    save_settings,
)
from .ffmpeg import FFmpegInfo, find_ffmpeg
from .logging_setup import configure_logging
from .media import normalize_url
from .options import DownloadOptions
from .queue import DownloadManager, JobSnapshot, JobStatus
from .settings_tab import SettingsTab
from .tabs import ConsoleTab, DownloadsTab, HistoryTab
from .tray import TrayIcon
from .widgets import Toast

log = logging.getLogger(__name__)

NAV_ITEMS = (
    ("downloads", "Downloads", "download"),
    ("history", "History", "history"),
    ("console", "Console", "console"),
    ("settings", "Settings", "settings"),
)

_IDEAL_SIZE = (1200, 820)
_MINIMUM_SIZE = (900, 560)
_EDGE_MARGIN = (60, 70)


def plan_window(screen_width: int, screen_height: int) -> tuple[int, int, int, int, int, int]:
    """Return ``(width, height, x, y, min_width, min_height)`` for this display.

    Everything here is in the units Tk reports the screen in, which is also what
    CustomTkinter's ``geometry()`` and ``minsize()`` expect before it applies
    display scaling. The minimum is clamped to the desktop as well: a fixed
    1000x640 floor leaves the title bar off a 1024x600 screen once Windows has
    taken its share of the height.
    """
    width = max(320, min(_IDEAL_SIZE[0], screen_width - _EDGE_MARGIN[0]))
    height = max(280, min(_IDEAL_SIZE[1], screen_height - _EDGE_MARGIN[1]))
    min_width = min(_MINIMUM_SIZE[0], width)
    min_height = min(_MINIMUM_SIZE[1], height)
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2 - 20)
    return width, height, x, y, min_width, min_height


class App(ctk.CTk):
    def __init__(
        self,
        initial_urls: list[str] | None = None,
        *,
        start_tray: bool = True,
        start_pump: bool = True,
    ):
        self.settings = load_settings()
        ctk.set_appearance_mode(self.settings.theme)
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=t.BG)
        self.title(APP_NAME)
        self._configure_window()
        t.apply_window_icon(self)

        self.manager = DownloadManager()
        self.history_store = HistoryStore()
        self.ffmpeg_info: FFmpegInfo = find_ffmpeg()

        self._current_page = ""
        self._pages: dict[str, Any] = {}
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._nav_icons: dict[str, dict[str, ctk.CTkImage]] = {}
        self._recorded_jobs: set[str] = set()
        self._toast: Toast | None = None
        self._pump_id: str | None = None
        self._quitting = False
        self._cleaned_up = False
        self._tray_hint_shown = False
        self._last_clipboard_seen = ""
        self._last_clipboard_check = 0.0
        self._tray_actions: Queue[str] = Queue()
        self._nav_font = t.font(13)
        self._nav_font_bold = t.font(13, "bold")

        self._build_layout()
        self.refresh_ffmpeg(self.ffmpeg_info)
        self.navigate("downloads")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._bind_shortcuts()

        self.tray: TrayIcon | None = None
        if start_tray:
            self.tray = TrayIcon(
                on_show=lambda: self._tray_actions.put("show"),
                on_open_folder=lambda: self._tray_actions.put("folder"),
                on_quit=lambda: self._tray_actions.put("quit"),
            )
            self.tray.start()

        if initial_urls:
            self.after(200, lambda: self._consume_initial_urls(initial_urls))
        if start_pump:
            self._pump_id = self.after(80, self._pump)

    # --------------------------------------------------------------- layout

    def _configure_window(self) -> None:
        width, height, x, y, min_width, min_height = plan_window(
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
        )
        self.minsize(min_width, min_height)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build_layout(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self._build_sidebar()

        self.content = ctk.CTkFrame(self, fg_color=t.BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.downloads_tab = DownloadsTab(self.content, self)
        self.history_tab = HistoryTab(self.content, self)
        self.console_tab = ConsoleTab(self.content, self)
        self.settings_tab = SettingsTab(self.content, self)
        self._pages = {
            "downloads": self.downloads_tab,
            "history": self.history_tab,
            "console": self.console_tab,
            "settings": self.settings_tab,
        }
        for page in self._pages.values():
            page.frame.grid(
                row=0,
                column=0,
                sticky="nsew",
                padx=24,
                pady=(18, 18),
            )
            page.frame.grid_remove()

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, fg_color=t.PANEL, corner_radius=0, width=228)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 22))
        icon = ctk.CTkLabel(
            brand,
            text="",
            image=ctk.CTkImage(
                light_image=t.load_icon(96),
                dark_image=t.load_icon(96),
                size=(38, 38),
            ),
        )
        icon.pack(side="left")
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            brand_text,
            text=APP_NAME,
            font=t.font(17, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_text,
            text="A calm front end for yt-dlp.",
            font=t.font(10),
            text_color=t.MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(1, 0))

        nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=12)
        nav.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            nav,
            text="WORKSPACE",
            font=t.font(9, "bold"),
            text_color=t.SUBTLE,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(0, 6))
        for index, (key, label, icon_name) in enumerate(NAV_ITEMS, start=1):
            icons = {
                "muted": t.nav_icon(icon_name),
                "active": t.nav_icon(icon_name, active=True),
            }
            self._nav_icons[key] = icons
            button = ctk.CTkButton(
                nav,
                text=label,
                image=icons["muted"],
                compound="left",
                anchor="w",
                height=40,
                corner_radius=10,
                border_spacing=10,
                font=self._nav_font,
                fg_color="transparent",
                hover_color=t.PANEL_ALT,
                text_color=t.MUTED,
                command=lambda target=key: self.navigate(target),
            )
            button.grid(row=index, column=0, sticky="ew", pady=2)
            self._nav_buttons[key] = button

        self.ffmpeg_card = ctk.CTkFrame(
            self.sidebar,
            fg_color=t.PANEL_ALT,
            corner_radius=12,
            border_width=1,
            border_color=t.BORDER,
        )
        self.ffmpeg_card.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 10))
        self.ffmpeg_card.grid_columnconfigure(1, weight=1)
        self.ffmpeg_dot = ctk.CTkLabel(
            self.ffmpeg_card,
            text="",
            width=9,
            height=9,
            corner_radius=5,
            fg_color=t.WARNING,
        )
        self.ffmpeg_dot.grid(row=0, column=0, rowspan=2, padx=(12, 8), pady=12)
        self.ffmpeg_title = ctk.CTkLabel(
            self.ffmpeg_card,
            text="FFmpeg",
            font=t.font(11, "bold"),
            text_color=t.TEXT,
            anchor="w",
        )
        self.ffmpeg_title.grid(row=0, column=1, sticky="w", pady=(9, 0))
        self.ffmpeg_subtitle = ctk.CTkLabel(
            self.ffmpeg_card,
            text="",
            font=t.font(9),
            text_color=t.MUTED,
            anchor="w",
        )
        self.ffmpeg_subtitle.grid(row=1, column=1, sticky="w", pady=(0, 9))
        for widget in (
            self.ffmpeg_card,
            self.ffmpeg_dot,
            self.ffmpeg_title,
            self.ffmpeg_subtitle,
        ):
            widget.bind("<Button-1>", lambda _event: self.navigate("settings"))

        ctk.CTkLabel(
            self.sidebar,
            text=f"Version {__version__}   ·   MIT License",
            font=t.font(9),
            text_color=t.SUBTLE,
            anchor="w",
        ).grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 16))

    def _update_nav(self) -> None:
        for key, button in self._nav_buttons.items():
            active = key == self._current_page
            button.configure(
                fg_color=t.ACCENT_SOFT if active else "transparent",
                hover_color=t.ACCENT_SOFT if active else t.PANEL_ALT,
                text_color=t.ACCENT_TEXT if active else t.MUTED,
                image=self._nav_icons[key]["active" if active else "muted"],
                font=self._nav_font_bold if active else self._nav_font,
            )

    # ------------------------------------------------------------ navigation

    def navigate(self, page: str) -> None:
        target = self._pages.get(page)
        if target is None:
            return
        if page == self._current_page:
            if page == "history":
                self.history_tab.on_show()
            elif page == "settings":
                self.settings_tab.on_show()
            return
        current = self._pages.get(self._current_page)
        if current is not None:
            current.frame.grid_remove()
        self._current_page = page
        target.frame.grid()
        if page == "history":
            self.history_tab.on_show()
        elif page == "settings":
            self.settings_tab.on_show()
        self._update_nav()

    def _focus_new_download(self, _event=None) -> str:
        self.navigate("downloads")
        self.downloads_tab.url_entry.focus_set()
        return "break"

    def _bind_shortcuts(self) -> None:
        for index, (key, _label, _icon) in enumerate(NAV_ITEMS, start=1):
            self.bind(
                f"<Control-Key-{index}>",
                lambda _event, target=key: self.navigate(target),
            )
        self.bind("<Control-Key-n>", self._focus_new_download)

    def _consume_initial_urls(self, urls: list[str]) -> None:
        self.navigate("downloads")
        self.downloads_tab.load_urls(urls)

    # ------------------------------------------------------------ queueing

    def enqueue_url(self, url: str) -> None:
        options = DownloadOptions.from_settings(self.settings)
        self.manager.add_job(url, options)

    def requeue_url(self, url: str) -> None:
        if not url:
            self.show_toast(
                "No source link",
                "This history entry does not have a source URL.",
                kind="warning",
            )
            return
        try:
            self.enqueue_url(url)
        except (ValueError, OSError) as exc:
            self.show_toast("Could not queue link", str(exc), kind="error")
        else:
            self.show_toast(
                "Added to queue",
                "The link was queued with your current settings.",
                kind="success",
            )

    # ------------------------------------------------------------- settings

    def update_settings(self, **changes: Any) -> AppSettings:
        data = self.settings.to_dict()
        data.update(changes)
        settings = AppSettings.from_dict(data)
        self.apply_settings(settings)
        self.settings_tab.on_external_settings(settings)
        return settings

    def apply_settings(self, settings: AppSettings) -> bool:
        was_watching = self.settings.clipboard_watch
        self.settings = settings
        saved = True
        try:
            save_settings(settings)
        except OSError as exc:
            saved = False
            log.exception("Could not save settings")
            self.show_toast(
                "Settings could not be saved",
                str(exc),
                kind="error",
            )
        ctk.set_appearance_mode(settings.theme)
        self.downloads_tab.sync_from_settings()
        self.console_tab.apply_theme()
        if not settings.clipboard_watch:
            self.downloads_tab.hide_clipboard_suggestion()
        elif not was_watching:
            self._last_clipboard_seen = ""
        return saved

    def refresh_ffmpeg(self, info: FFmpegInfo) -> None:
        self.ffmpeg_info = info
        if info.found:
            self.ffmpeg_dot.configure(fg_color=t.SUCCESS)
            self.ffmpeg_title.configure(text="FFmpeg ready")
            version_text = f"v{info.short_version}" if info.short_version else "Installed"
            self.ffmpeg_subtitle.configure(text=f"{version_text}  ·  Manage")
        else:
            self.ffmpeg_dot.configure(fg_color=t.WARNING)
            self.ffmpeg_title.configure(text="FFmpeg missing")
            self.ffmpeg_subtitle.configure(text="Click to set up")
        self.downloads_tab.update_ffmpeg_banner(info)
        self.settings_tab.set_ffmpeg_info(info)

    def open_url(self, url: str) -> None:
        try:
            t.open_url(url)
        except OSError as exc:
            log.exception("Could not open URL %s", url)
            self.show_toast("Could not open link", str(exc), kind="error")

    # -------------------------------------------------------------- folders

    def open_downloads_folder(self) -> None:
        folder = Path(self.settings.download_dir).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            t.open_path(folder)
        except OSError as exc:
            self.show_toast("Could not open folder", str(exc), kind="error")

    def open_data_folder(self) -> None:
        try:
            target = app_data_dir()
            target.mkdir(parents=True, exist_ok=True)
            t.open_path(target)
        except OSError as exc:
            self.show_toast("Could not open the settings folder", str(exc), kind="error")

    def open_log_folder(self) -> None:
        try:
            target = log_dir()
            target.mkdir(parents=True, exist_ok=True)
            t.open_path(target)
        except OSError as exc:
            self.show_toast("Could not open the log folder", str(exc), kind="error")

    def open_file(self, path: str) -> None:
        target = Path(path)
        if not target.is_file():
            self.show_toast(
                "File not found",
                "This file was moved or deleted. Use the source link to download it again.",
                kind="error",
            )
            return
        try:
            t.open_path(target)
        except OSError as exc:
            self.show_toast("Could not open file", str(exc), kind="error")

    def reveal_file(self, path: str) -> None:
        target = Path(path)
        if not target.exists():
            self.show_toast(
                "File not found",
                "This file was moved or deleted. Use the source link to download it again.",
                kind="error",
            )
            return
        try:
            t.reveal_path(target)
        except OSError as exc:
            self.show_toast("Could not show the file", str(exc), kind="error")

    # --------------------------------------------------------------- toasts

    def show_toast(self, title: str, message: str, *, kind: str = "info") -> None:
        if self._quitting:
            return
        if self._toast is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
        toast = Toast(self.content, title, message, kind=kind)
        toast.place(relx=1.0, rely=1.0, x=-26, y=-26, anchor="se")
        toast.lift()
        self._toast = toast

    # -------------------------------------------------------------- events

    def _pump(self) -> None:
        self._pump_id = None
        if self._quitting:
            return
        try:
            for _ in range(400):
                try:
                    event = self.manager.events.get_nowait()
                except Empty:
                    break
                try:
                    self._handle_event(event)
                except Exception:
                    log.exception("Could not handle a queue event")
            self._drain_tray_actions()
            self._poll_clipboard()
        finally:
            if not self._quitting:
                self._pump_id = self.after(80, self._pump)

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "job":
            snapshot = event.get("job")
            if isinstance(snapshot, JobSnapshot):
                self.downloads_tab.update_job(snapshot)
                if snapshot.status == JobStatus.COMPLETED:
                    self._record_history(snapshot)
        elif kind == "job_removed":
            self.downloads_tab.remove_job(str(event.get("id", "")))
        elif kind == "log":
            self.console_tab.append(
                str(event.get("level", "info")),
                str(event.get("message", "")),
            )
        elif kind == "notify":
            self._notify_user(
                str(event.get("title", APP_NAME)),
                str(event.get("message", "")),
            )
        elif kind == "queue_state":
            self.downloads_tab.refresh_queue_meta()

    def _record_history(self, snapshot: JobSnapshot) -> None:
        if snapshot.id in self._recorded_jobs:
            return
        self._recorded_jobs.add(snapshot.id)
        if not snapshot.file_paths:
            return
        multiple = len(snapshot.file_paths) > 1
        entries: list[HistoryEntry] = []
        for path in snapshot.file_paths:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if multiple or not snapshot.title or snapshot.title == snapshot.url:
                title = Path(path).stem
            else:
                title = snapshot.title
            entries.append(
                HistoryEntry.create(
                    title=title,
                    file_path=path,
                    url=snapshot.url,
                    mode=snapshot.mode,
                    size_bytes=size,
                )
            )
        try:
            self.history_store.add_many(entries)
        except OSError as exc:
            log.exception("Could not save download history")
            self.show_toast("History could not be saved", str(exc), kind="error")
            return
        if self._current_page == "history":
            self.history_tab.refresh()

    def _notify_user(self, title: str, message: str) -> None:
        if not self.settings.notifications:
            return
        lower = title.lower()
        kind = "success" if "complete" in lower else "error" if "fail" in lower else "info"
        try:
            hidden = self.state() in ("withdrawn", "iconic")
        except tk.TclError:
            return
        if (
            hidden
            and self.tray is not None
            and self.tray.available
            and self.tray.notify(title, message)
        ):
            return
        self.show_toast(title, message, kind=kind)

    def _drain_tray_actions(self) -> None:
        while True:
            try:
                action = self._tray_actions.get_nowait()
            except Empty:
                break
            if action == "show":
                self.show_window()
            elif action == "folder":
                self.open_downloads_folder()
            elif action == "quit":
                self.request_quit()
                if self._quitting:
                    return

    def _poll_clipboard(self) -> None:
        if not self.settings.clipboard_watch:
            return
        now = time.monotonic()
        if now - self._last_clipboard_check < 1.2:
            return
        self._last_clipboard_check = now
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            return
        if not text or len(text) > 4096 or text == self._last_clipboard_seen:
            return
        self._last_clipboard_seen = text
        url = normalize_url(text)
        if not url:
            return
        if self.downloads_tab.current_url_text().strip() == text:
            return
        self.downloads_tab.suggest_clipboard(url)

    # ----------------------------------------------------------- tray/window

    def show_window(self) -> None:
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        if self._quitting:
            return
        if (
            self.settings.minimize_to_tray
            and self.tray is not None
            and self.tray.available
        ):
            self.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                if self.settings.notifications:
                    self.tray.notify(
                        APP_NAME,
                        "YDL Studio is still running. Use the tray icon to reopen it.",
                    )
            return
        self.request_quit()

    def request_quit(self) -> None:
        if self._quitting:
            return
        has_unsaved = self.settings_tab.is_dirty()
        has_jobs = self.manager.has_unfinished_jobs()
        if has_unsaved or has_jobs:
            self.show_window()
        if has_unsaved:
            choice = messagebox.askyesnocancel(
                "Save settings?",
                "You have unsaved settings changes.\n\nSave them before closing?",
                parent=self,
            )
            if choice is None:
                return
            if choice and not self.settings_tab.save():
                return
        if has_jobs:
            confirmed = messagebox.askyesno(
                "Quit while downloading?",
                (
                    "A download is still queued or running.\n\n"
                    "Quitting stops it and may leave a partial file in your output folder. "
                    "Quit anyway?"
                ),
                parent=self,
            )
            if not confirmed:
                return
        self._quitting = True
        if self._pump_id is not None:
            try:
                self.after_cancel(self._pump_id)
            except tk.TclError:
                pass
            self._pump_id = None
        self.cleanup()
        try:
            self.destroy()
        except tk.TclError:
            pass

    def cleanup(self) -> None:
        if self._cleaned_up:
            return
        self._cleaned_up = True
        try:
            self.settings_tab.cancel_pending_work()
        except tk.TclError:
            pass
        if self.tray is not None:
            self.tray.stop()
        self.manager.shutdown()


def run(initial_urls: list[str] | None = None) -> None:
    configure_logging()
    log.info("Starting %s %s", APP_NAME, __version__)
    app = App(initial_urls=initial_urls)
    try:
        app.mainloop()
    finally:
        app.cleanup()
        log.info("%s stopped", APP_NAME)
