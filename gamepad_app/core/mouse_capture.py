from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


class MouseCapture:
    """Confine and hide the Windows pointer while gameplay is active."""

    def __init__(self) -> None:
        self._active = False
        self._hidden_count = 0
        self._user32: Any = None

    @property
    def active(self) -> bool:
        return self._active

    def capture(self) -> None:
        if self._active:
            return
        if not hasattr(ctypes, "windll"):
            raise OSError("La capture souris est disponible uniquement sous Windows.")
        self._user32 = ctypes.windll.user32
        rect = ctypes.wintypes.RECT()
        if not self._user32.GetWindowRect(self._user32.GetDesktopWindow(), ctypes.byref(rect)):
            raise ctypes.WinError()
        if not self._user32.ClipCursor(ctypes.byref(rect)):
            raise ctypes.WinError()
        while self._user32.ShowCursor(False) >= 0:
            self._hidden_count += 1
        self._hidden_count += 1
        self._active = True
        LOGGER.info("Pointeur confiné à l'écran et masqué; Échap le libère.")

    def release(self) -> None:
        if not self._active:
            return
        try:
            self._user32.ClipCursor(None)
            for _ in range(self._hidden_count):
                self._user32.ShowCursor(True)
        finally:
            self._active = False
            self._hidden_count = 0
            LOGGER.info("Capture souris relâchée.")
