"""Optional system tray icon built on pystray."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from . import APP_NAME
from . import theme as t

log = logging.getLogger(__name__)


class TrayIcon:
    def __init__(
        self,
        *,
        on_show: Callable[[], None],
        on_open_folder: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self._on_show = on_show
        self._on_open_folder = on_open_folder
        self._on_quit = on_quit
        self._icon = None
        self._thread: threading.Thread | None = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def start(self) -> None:
        try:
            import pystray
        except Exception:
            log.exception("pystray is not available")
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem(
                    "Open YDL Studio",
                    lambda _icon, _item: self._on_show(),
                    default=True,
                ),
                pystray.MenuItem(
                    "Open downloads folder",
                    lambda _icon, _item: self._on_open_folder(),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda _icon, _item: self._on_quit()),
            )
            self._icon = pystray.Icon(
                "ydl-studio",
                t.load_icon(64),
                APP_NAME,
                menu,
            )
            self._available = True
            self._thread = threading.Thread(
                target=self._run,
                name="ydl-studio-tray",
                daemon=True,
            )
            self._thread.start()
        except Exception:
            log.exception("Could not start the system tray")
            self._available = False
            self._icon = None

    def _run(self) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.run()
        except Exception:
            log.exception("The tray icon stopped unexpectedly")
            self._available = False

    def notify(self, title: str, message: str) -> bool:
        icon = self._icon
        if icon is None or not self._available:
            return False
        try:
            icon.notify(message, title)
            return True
        except Exception:
            log.debug("Could not show a tray notification", exc_info=True)
            return False

    def stop(self) -> None:
        self._available = False
        icon = self._icon
        self._icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                log.debug("Could not stop the tray icon cleanly", exc_info=True)
