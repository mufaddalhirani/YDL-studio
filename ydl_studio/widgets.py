"""Reusable widgets shared by the YDL Studio pages."""

from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path

import customtkinter as ctk

from . import theme as t
from .media import parse_urls
from .queue import JobSnapshot, JobStatus


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def shorten_path(path: str | Path, limit: int = 48) -> str:
    text = str(path)
    home = str(Path.home())
    if os.name == "nt" and text.lower().startswith(home.lower()):
        text = "~" + text[len(home) :]
    elif text.startswith(home):
        text = "~" + text[len(home) :]
    if len(text) <= limit:
        return text
    keep = max(4, (limit - 1) // 2)
    return f"{text[:keep]}…{text[-keep:]}"


class Card(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", t.PANEL)
        kwargs.setdefault("corner_radius", 16)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", t.BORDER)
        super().__init__(master, **kwargs)


def option_menu(
    master,
    variable: tk.StringVar,
    values: Sequence[str],
    *,
    width: int = 150,
    command: Callable[[str], None] | None = None,
) -> ctk.CTkOptionMenu:
    return ctk.CTkOptionMenu(
        master,
        variable=variable,
        values=list(values),
        width=width,
        height=32,
        corner_radius=8,
        fg_color=t.PANEL_ALT,
        button_color=t.BORDER,
        button_hover_color=t.SUBTLE,
        text_color=t.TEXT,
        dropdown_fg_color=t.PANEL,
        dropdown_hover_color=t.ACCENT_SOFT,
        dropdown_text_color=t.TEXT,
        font=t.font(12),
        dropdown_font=t.font(12),
        dynamic_resizing=False,
        command=command,
    )


def entry(
    master,
    variable: tk.StringVar | None = None,
    *,
    width: int = 260,
    placeholder: str = "",
    height: int = 34,
) -> ctk.CTkEntry:
    return ctk.CTkEntry(
        master,
        textvariable=variable,
        width=width,
        height=height,
        corner_radius=8,
        border_width=1,
        fg_color=t.PANEL_ALT,
        border_color=t.BORDER,
        text_color=t.TEXT,
        placeholder_text=placeholder,
        placeholder_text_color=t.SUBTLE,
        font=t.font(12),
    )


def switch(
    master,
    variable: tk.BooleanVar,
    *,
    text: str = "",
    width: int = 42,
    height: int = 22,
    font: ctk.CTkFont | None = None,
    text_color: t.Color = t.MUTED,
) -> ctk.CTkSwitch:
    # The knob is the same height as the track, so a pale track in light mode
    # makes it disappear into the card behind it.
    return ctk.CTkSwitch(
        master,
        text=text,
        variable=variable,
        width=width,
        height=height,
        font=font,
        text_color=text_color,
        progress_color=t.ACCENT,
        fg_color=("#94a3b8", "#1f2733"),
        button_color=("#f1f5f9", "#e8edf6"),
        button_hover_color=("#e2e8f0", "#ffffff"),
    )


def secondary_button(
    master,
    text: str,
    command: Callable[[], None],
    *,
    width: int = 100,
    height: int = 30,
    text_color: t.Color = t.MUTED,
) -> ctk.CTkButton:
    return ctk.CTkButton(
        master,
        text=text,
        width=width,
        height=height,
        corner_radius=8,
        font=t.font(11),
        fg_color="transparent",
        border_width=1,
        border_color=t.BORDER,
        hover_color=t.PANEL_ALT,
        text_color=text_color,
        command=command,
    )


def primary_button(
    master,
    text: str,
    command: Callable[[], None],
    *,
    width: int = 116,
    height: int = 34,
) -> ctk.CTkButton:
    return ctk.CTkButton(
        master,
        text=text,
        width=width,
        height=height,
        corner_radius=9,
        font=t.font(12, "bold"),
        fg_color=t.ACCENT,
        hover_color=t.ACCENT_HOVER,
        text_color=("#ffffff", "#ffffff"),
        command=command,
    )


class SectionCard(Card):
    """A card with a heading and a body frame for form content."""

    def __init__(
        self,
        master,
        title: str,
        subtitle: str = "",
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(15, 0))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=title,
            font=t.font(15, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        if subtitle:
            ctk.CTkLabel(
                header,
                text=subtitle,
                font=t.font(11),
                text_color=t.MUTED,
                anchor="w",
                justify="left",
                wraplength=640,
            ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="ew", padx=18, pady=(11, 16))
        self.body.grid_columnconfigure(0, weight=1)


class SegmentedControl(ctk.CTkFrame):
    def __init__(
        self,
        master,
        values: Sequence[str],
        variable: tk.StringVar,
        command: Callable[[str], None] | None = None,
        **kwargs,
    ):
        kwargs.setdefault("fg_color", t.PANEL_SOFT)
        kwargs.setdefault("corner_radius", 10)
        super().__init__(master, **kwargs)
        self._variable = variable
        self._command = command
        self._buttons: dict[str, ctk.CTkButton] = {}
        for index, value in enumerate(values):
            button = ctk.CTkButton(
                self,
                text=value,
                height=30,
                corner_radius=8,
                font=t.font(12, "bold"),
                command=lambda selected=value: self.set(selected),
            )
            padx = (3 if index == 0 else 1, 3 if index == len(values) - 1 else 1)
            button.grid(row=0, column=index, sticky="ew", padx=padx, pady=3)
            self.grid_columnconfigure(index, weight=1, uniform="segment")
            self._buttons[value] = button
        self._refresh()
        variable.trace_add("write", lambda *_: self._refresh())

    def set(self, value: str) -> None:
        if value not in self._buttons:
            return
        self._variable.set(value)
        self._refresh()
        if self._command:
            self._command(value)

    def get(self) -> str:
        return self._variable.get()

    def _refresh(self) -> None:
        current = self._variable.get()
        for value, button in self._buttons.items():
            if value == current:
                button.configure(
                    fg_color=t.ACCENT,
                    hover_color=t.ACCENT_HOVER,
                    text_color=("#ffffff", "#ffffff"),
                )
            else:
                button.configure(
                    fg_color="transparent",
                    hover_color=t.PANEL_ALT,
                    text_color=t.MUTED,
                )


_STATUS_STYLES: dict[JobStatus, tuple[str, t.Color, t.Color]] = {
    JobStatus.QUEUED: ("Queued", t.NEUTRAL_CHIP, t.MUTED),
    JobStatus.DOWNLOADING: ("Downloading", t.ACCENT_SOFT, t.ACCENT_TEXT),
    JobStatus.PROCESSING: ("Processing", t.WARNING_SOFT, t.WARNING_TEXT),
    JobStatus.COMPLETED: ("Completed", t.SUCCESS_SOFT, t.SUCCESS_TEXT),
    JobStatus.FAILED: ("Failed", t.DANGER_SOFT, t.DANGER_TEXT),
    JobStatus.CANCELLED: ("Cancelled", t.NEUTRAL_CHIP, t.SUBTLE),
}


class StatusChip(ctk.CTkLabel):
    def __init__(self, master, status: JobStatus = JobStatus.QUEUED):
        super().__init__(
            master,
            text="",
            height=22,
            corner_radius=9,
            font=t.font(11, "bold"),
        )
        self.set_status(status)

    def set_status(self, status: JobStatus) -> None:
        label, background, foreground = _STATUS_STYLES.get(status, _STATUS_STYLES[JobStatus.QUEUED])
        self.configure(text=f"  {label}  ", fg_color=background, text_color=foreground)


class QueueRow(Card):
    def __init__(
        self,
        master,
        snapshot: JobSnapshot,
        *,
        on_cancel: Callable[[str], None],
        on_retry: Callable[[str], None],
        on_remove: Callable[[str], None],
        on_open: Callable[[str], None],
        on_reveal: Callable[[str], None],
    ):
        super().__init__(
            master,
            fg_color=t.PANEL_ALT,
            corner_radius=12,
            border_color=t.BORDER,
        )
        self._snapshot = snapshot
        self._on_cancel = on_cancel
        self._on_retry = on_retry
        self._on_remove = on_remove
        self._on_open = on_open
        self._on_reveal = on_reveal
        self._primary_path = ""
        self._primary_action: Callable[[], None] | None = None
        self._secondary_action: Callable[[], None] | None = None
        self._tertiary_action: Callable[[], None] | None = None

        self.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
        top.grid_columnconfigure(0, weight=1)

        self._title = ctk.CTkLabel(
            top,
            text="",
            font=t.font(13, "bold"),
            text_color=t.TEXT,
            anchor="w",
        )
        self._title.grid(row=0, column=0, sticky="w")

        self._chip = StatusChip(top)
        self._chip.grid(row=0, column=1, padx=(12, 0), sticky="e")

        self._meta = ctk.CTkLabel(
            top,
            text="",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
        )
        self._meta.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        self._progress = ctk.CTkProgressBar(
            self,
            height=5,
            corner_radius=3,
            fg_color=t.NEUTRAL_CHIP,
            progress_color=t.ACCENT,
        )
        self._progress.grid(row=1, column=0, sticky="ew", padx=14, pady=(10, 0))
        self._progress.set(0)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=14, pady=(7, 12))
        bottom.grid_columnconfigure(0, weight=1)

        self._stats = ctk.CTkLabel(
            bottom,
            text="",
            font=t.font(11),
            text_color=t.SUBTLE,
            anchor="w",
        )
        self._stats.grid(row=0, column=0, sticky="ew")

        self._percent = ctk.CTkLabel(
            bottom,
            text="0%",
            font=t.font(11, "bold"),
            text_color=t.MUTED,
        )
        self._percent.grid(row=0, column=1, padx=(10, 12))

        self._primary = ctk.CTkButton(
            bottom,
            text="Open",
            width=72,
            height=27,
            corner_radius=8,
            font=t.font(11, "bold"),
            command=self._run_primary,
        )
        self._secondary = ctk.CTkButton(
            bottom,
            text="Show",
            width=72,
            height=27,
            corner_radius=8,
            font=t.font(11),
            fg_color="transparent",
            border_width=1,
            border_color=t.BORDER,
            hover_color=t.PANEL,
            text_color=t.MUTED,
            command=self._run_secondary,
        )
        self._tertiary = ctk.CTkButton(
            bottom,
            text="Remove",
            width=70,
            height=27,
            corner_radius=8,
            font=t.font(11),
            fg_color="transparent",
            hover_color=t.PANEL,
            text_color=t.SUBTLE,
            command=self._run_tertiary,
        )
        self._primary.grid(row=0, column=2)
        self._secondary.grid(row=0, column=3, padx=(6, 0))
        self._tertiary.grid(row=0, column=4, padx=(6, 0))

        self._error = ctk.CTkLabel(
            self,
            text="",
            font=t.font(11),
            text_color=t.DANGER_TEXT,
            anchor="w",
            justify="left",
            wraplength=680,
        )
        self._error.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 12))
        self._error.grid_remove()

        self.update_snapshot(snapshot)

    @property
    def job_id(self) -> str:
        return self._snapshot.id

    def update_snapshot(self, snapshot: JobSnapshot) -> None:
        self._snapshot = snapshot
        status = snapshot.status
        title = snapshot.title or snapshot.url
        meta = truncate(snapshot.url, 110)
        if title == snapshot.url:
            if status == JobStatus.QUEUED:
                meta = "Queued and waiting to start."
            elif status in (JobStatus.DOWNLOADING, JobStatus.PROCESSING):
                meta = "Reading media details…"
            else:
                meta = "Source link"
        self._title.configure(text=truncate(title, 82))
        self._meta.configure(text=meta)
        self._chip.set_status(status)

        percent = max(0.0, min(100.0, snapshot.percent))
        self._progress.set(percent / 100)
        self._percent.configure(text=f"{percent:.0f}%")
        progress_color = {
            JobStatus.COMPLETED: t.SUCCESS,
            JobStatus.FAILED: t.DANGER,
            JobStatus.CANCELLED: t.SUBTLE,
            JobStatus.PROCESSING: t.WARNING,
        }.get(status, t.ACCENT)
        self._progress.configure(progress_color=progress_color)

        parts = [part for part in (snapshot.stage, snapshot.speed, snapshot.size) if part]
        if snapshot.eta:
            parts.append(f"ETA {snapshot.eta}")
        if status == JobStatus.COMPLETED and snapshot.file_paths:
            count = len(snapshot.file_paths)
            parts.append(f"{count} file{'s' if count != 1 else ''} saved")
        self._stats.configure(text="   ·   ".join(parts))
        self._percent.configure(
            text_color=(
                t.SUCCESS_TEXT
                if status == JobStatus.COMPLETED
                else t.DANGER_TEXT
                if status == JobStatus.FAILED
                else t.MUTED
            )
        )

        if snapshot.error and status == JobStatus.FAILED:
            self._error.configure(text=truncate(snapshot.error, 320))
            self._error.grid()
        else:
            self._error.grid_remove()

        existing = next((path for path in snapshot.file_paths if Path(path).is_file()), "")
        self._primary_path = existing or (snapshot.file_paths[0] if snapshot.file_paths else "")
        self._configure_actions(status, bool(existing))

    def _configure_actions(self, status: JobStatus, file_exists: bool) -> None:
        self._primary.grid_remove()
        self._secondary.grid_remove()
        self._tertiary.grid_remove()
        self._primary_action = None
        self._secondary_action = None
        self._tertiary_action = None

        if status in (JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.PROCESSING):
            self._tertiary.configure(
                text="Cancel",
                fg_color=t.DANGER_SOFT,
                hover_color=t.DANGER,
                text_color=t.DANGER_TEXT,
            )
            self._tertiary_action = lambda: self._on_cancel(self.job_id)
            self._tertiary.grid(row=0, column=4, padx=(6, 0))
            return

        if status == JobStatus.COMPLETED:
            if file_exists:
                self._primary.configure(
                    text="Open",
                    fg_color=t.ACCENT_SOFT,
                    hover_color=t.ACCENT,
                    text_color=t.ACCENT_TEXT,
                    state="normal",
                )
                self._primary_action = lambda: self._on_open(self._primary_path)
                self._primary.grid(row=0, column=2)

                self._secondary.configure(
                    text="Show",
                    fg_color="transparent",
                    border_color=t.BORDER,
                    hover_color=t.PANEL,
                    text_color=t.MUTED,
                )
                self._secondary_action = lambda: self._on_reveal(self._primary_path)
                self._secondary.grid(row=0, column=3, padx=(6, 0))
            self._tertiary.configure(
                text="Remove",
                fg_color="transparent",
                hover_color=t.PANEL,
                text_color=t.SUBTLE,
            )
            self._tertiary_action = lambda: self._on_remove(self.job_id)
            self._tertiary.grid(row=0, column=4, padx=(6, 0))
            return

        self._primary.configure(
            text="Retry",
            fg_color=t.ACCENT,
            hover_color=t.ACCENT_HOVER,
            text_color=("#ffffff", "#ffffff"),
            state="normal",
        )
        self._primary_action = lambda: self._on_retry(self.job_id)
        self._primary.grid(row=0, column=2)

        self._tertiary.configure(
            text="Remove",
            fg_color="transparent",
            hover_color=t.PANEL,
            text_color=t.SUBTLE,
        )
        self._tertiary_action = lambda: self._on_remove(self.job_id)
        self._tertiary.grid(row=0, column=4, padx=(6, 0))

    def _run_primary(self) -> None:
        if self._primary_action:
            self._primary_action()

    def _run_secondary(self) -> None:
        if self._secondary_action:
            self._secondary_action()

    def _run_tertiary(self) -> None:
        if self._tertiary_action:
            self._tertiary_action()


class HistoryRow(Card):
    def __init__(
        self,
        master,
        *,
        title: str,
        meta: str,
        path: str,
        mode: str,
        file_exists: bool,
        on_open: Callable[[], None],
        on_reveal: Callable[[], None],
        on_requeue: Callable[[], None],
        on_remove: Callable[[], None],
    ):
        super().__init__(
            master,
            fg_color=t.PANEL_ALT,
            corner_radius=12,
            border_color=t.BORDER,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        text_holder = ctk.CTkFrame(self, fg_color="transparent")
        text_holder.grid(row=0, column=0, sticky="ew", padx=(14, 10), pady=11)
        text_holder.grid_columnconfigure(0, weight=1)

        headline = ctk.CTkFrame(text_holder, fg_color="transparent")
        headline.grid(row=0, column=0, sticky="ew")
        headline.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            headline,
            text=truncate(title, 70),
            font=t.font(13, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            headline,
            text=f"  {mode.upper()}  ",
            font=t.font(9, "bold"),
            text_color=t.ACCENT_TEXT,
            fg_color=t.ACCENT_SOFT,
            corner_radius=7,
            height=19,
        ).grid(row=0, column=1, padx=(8, 0))

        ctk.CTkLabel(
            text_holder,
            text=meta,
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ctk.CTkLabel(
            text_holder,
            text=truncate(path, 92) + ("" if file_exists else "  (missing)"),
            font=t.font(10, mono=True),
            text_color=t.SUBTLE if file_exists else t.WARNING_TEXT,
            anchor="w",
        ).grid(row=2, column=0, sticky="w", pady=(3, 0))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e", padx=(0, 12), pady=11)
        for label, command, color in (
            ("Open", on_open, t.ACCENT_TEXT),
            ("Show", on_reveal, t.MUTED),
            ("Again", on_requeue, t.MUTED),
            ("Remove", on_remove, t.SUBTLE),
        ):
            ctk.CTkButton(
                actions,
                text=label,
                width=54 if label != "Remove" else 62,
                height=27,
                corner_radius=8,
                font=t.font(11),
                fg_color="transparent",
                hover_color=t.PANEL,
                text_color=color,
                command=command,
            ).pack(side="left", padx=(6, 0))


class EmptyState(ctk.CTkFrame):
    def __init__(
        self,
        master,
        title: str,
        description: str,
        *,
        icon: str = "download",
        action_text: str = "",
        action: Callable[[], None] | None = None,
    ):
        super().__init__(master, fg_color="transparent")
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(pady=54)
        icon_chip = ctk.CTkFrame(content, width=54, height=54, fg_color=t.ACCENT_SOFT, corner_radius=16)
        icon_chip.pack()
        icon_chip.pack_propagate(False)
        ctk.CTkLabel(
            icon_chip,
            text="",
            image=t.nav_icon(icon, active=True, size=24),
        ).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(
            content,
            text=title,
            font=t.font(14, "bold"),
            text_color=t.TEXT,
        ).pack(pady=(12, 3))
        ctk.CTkLabel(
            content,
            text=description,
            font=t.font(11),
            text_color=t.MUTED,
            wraplength=420,
            justify="center",
        ).pack()
        if action_text and action:
            ctk.CTkButton(
                content,
                text=action_text,
                height=32,
                width=140,
                corner_radius=9,
                font=t.font(12, "bold"),
                fg_color=t.ACCENT_SOFT,
                hover_color=t.ACCENT,
                text_color=t.ACCENT_TEXT,
                command=action,
            ).pack(pady=(14, 0))


class Toast(ctk.CTkFrame):
    def __init__(
        self,
        master,
        title: str,
        message: str,
        *,
        kind: str = "info",
        duration: int = 4500,
    ):
        accent = {
            "info": t.ACCENT,
            "success": t.SUCCESS,
            "warning": t.WARNING,
            "error": t.DANGER,
        }.get(kind, t.ACCENT)
        super().__init__(
            master,
            fg_color=t.PANEL,
            border_width=1,
            border_color=accent,
            corner_radius=14,
            width=360,
        )
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(self, width=4, fg_color=accent, corner_radius=2).grid(
            row=0, column=0, sticky="ns", padx=(10, 0), pady=10
        )
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=1, sticky="ew", padx=(10, 6), pady=(10, 11))
        body.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            body,
            text=title,
            font=t.font(12, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            body,
            text=message,
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
            justify="left",
            wraplength=300,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ctk.CTkButton(
            self,
            text="×",
            width=24,
            height=24,
            corner_radius=6,
            font=t.font(14),
            fg_color="transparent",
            hover_color=t.PANEL_ALT,
            text_color=t.SUBTLE,
            command=self.destroy,
        ).grid(row=0, column=2, sticky="ne", padx=(0, 8), pady=(6, 0))
        self._timer: str | None = self.after(duration, self.destroy)

    def destroy(self) -> None:
        if self._timer is not None:
            try:
                self.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        super().destroy()


class BatchDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        initial_text: str = "",
        on_submit: Callable[[list[str]], None],
    ):
        super().__init__(master)
        self._on_submit = on_submit
        self._urls: list[str] = []
        self._preview_job: str | None = None
        self._focus_job: str | None = None
        self._closed = False
        self.title("Add links in bulk")
        self.configure(fg_color=t.BG)
        self.minsize(560, 430)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-Return>", lambda _event: self._submit())

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 0))
        ctk.CTkLabel(
            header,
            text="Add links in bulk",
            font=t.font(20, "bold"),
            text_color=t.TEXT,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=(
                "Paste one URL per line. Playlists and ytsearch: queries are supported. "
                "Duplicates are ignored."
            ),
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
            justify="left",
            wraplength=580,
        ).pack(anchor="w", pady=(3, 0))

        editor = Card(self)
        editor.grid(row=1, column=0, sticky="nsew", padx=22, pady=14)
        editor.grid_rowconfigure(0, weight=1)
        editor.grid_columnconfigure(0, weight=1)
        self._textbox = ctk.CTkTextbox(
            editor,
            corner_radius=10,
            border_width=1,
            border_color=t.BORDER,
            fg_color=t.PANEL_ALT,
            text_color=t.TEXT,
            font=t.font(12, mono=True),
            wrap="word",
        )
        self._textbox.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self._textbox.insert("1.0", initial_text)
        self._textbox.bind("<KeyRelease>", lambda _event: self._schedule_preview())
        ctk.CTkButton(
            editor,
            text="Paste from clipboard",
            height=30,
            width=150,
            corner_radius=8,
            font=t.font(11),
            fg_color="transparent",
            border_width=1,
            border_color=t.BORDER,
            hover_color=t.PANEL,
            text_color=t.MUTED,
            command=self._paste,
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 12))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 20))
        footer.grid_columnconfigure(0, weight=1)
        self._preview = ctk.CTkLabel(
            footer,
            text="",
            font=t.font(11),
            text_color=t.MUTED,
            anchor="w",
            justify="left",
            wraplength=430,
        )
        self._preview.grid(row=0, column=0, sticky="w", padx=(0, 14))
        ctk.CTkButton(
            footer,
            text="Cancel",
            width=86,
            height=34,
            corner_radius=9,
            font=t.font(12),
            fg_color="transparent",
            border_width=1,
            border_color=t.BORDER,
            hover_color=t.PANEL,
            text_color=t.MUTED,
            command=self.destroy,
        ).grid(row=0, column=1, padx=(0, 8))
        self._add_button = ctk.CTkButton(
            footer,
            text="Add links",
            width=120,
            height=34,
            corner_radius=9,
            font=t.font(12, "bold"),
            fg_color=t.ACCENT,
            hover_color=t.ACCENT_HOVER,
            text_color=("#ffffff", "#ffffff"),
            command=self._submit,
        )
        self._add_button.grid(row=0, column=2)

        self.update_idletasks()
        width, height = 680, 520
        x = master.winfo_rootx() + max(0, (master.winfo_width() - width) // 2)
        y = master.winfo_rooty() + max(0, (master.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self._update_preview()
        self._focus_job = self.after(80, self._focus_editor)

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        for job in (self._preview_job, self._focus_job):
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        self._preview_job = None
        self._focus_job = None
        super().destroy()

    def _focus_editor(self) -> None:
        self._focus_job = None
        if not self.winfo_exists():
            return
        self.lift()
        self._textbox.focus_set()

    def _paste(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        if not text:
            return
        current = self._textbox.get("1.0", "end").strip()
        if current:
            self._textbox.insert("end", "\n" + text.strip())
        else:
            self._textbox.insert("1.0", text.strip())
        self._update_preview()

    def _schedule_preview(self) -> None:
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(180, self._update_preview)

    def _update_preview(self) -> None:
        self._preview_job = None
        if self._closed or not self.winfo_exists():
            return
        self._urls, invalid = parse_urls(self._textbox.get("1.0", "end"))
        count = len(self._urls)
        if count == 0 and not invalid:
            text = "No links yet."
            color = t.SUBTLE
        elif count == 0:
            preview = ", ".join(truncate(token, 28) for token in invalid[:3])
            text = f"No valid links. Ignored: {preview}"
            color = t.DANGER_TEXT
        else:
            text = f"{count} link{'s' if count != 1 else ''} ready"
            if invalid:
                preview = ", ".join(truncate(token, 24) for token in invalid[:3])
                text += f"  ·  ignored {len(invalid)}: {preview}"
                color = t.WARNING_TEXT
            else:
                color = t.MUTED
        self._preview.configure(text=text, text_color=color)
        self._add_button.configure(
            state="normal" if count else "disabled",
            text=f"Add {count} link{'s' if count != 1 else ''}" if count else "Add links",
        )

    def _submit(self) -> None:
        if not self._urls:
            return
        self._on_submit(list(self._urls))
        self.destroy()
