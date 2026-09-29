"""Event-loop stall watchdog (M8.10).

A ``QTimer`` ticks every 50 ms; the lateness of a tick is how long the UI thread was blocked.  Stalls above the
threshold (100 ms) are counted; in debug mode (``debug=True`` or ``TOKEN_CONTEXT_GUI_DEBUG=1``) each one is logged
and ``faulthandler`` dumps the stack of every thread *while the loop is still blocked* (a dead-man's switch that
the next tick cancels and re-arms), so the log shows what the UI thread was doing.
"""
from __future__ import annotations

import faulthandler
import logging
import os
import time
from pathlib import Path
from typing import TextIO

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger("token_context_mcp.gui.perf")

TICK_MS = 50
STALL_MS = 100


class EventLoopWatchdog(QObject):
    def __init__(
        self,
        parent: QObject | None = None,
        *,
        debug: bool | None = None,
        stall_ms: int = STALL_MS,
        dump_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.debug = bool(os.environ.get("TOKEN_CONTEXT_GUI_DEBUG")) if debug is None else debug
        self.stall_ms = stall_ms
        self.stalls_ms: list[float] = []
        self._last = 0.0
        self._dump_file: TextIO | None = None
        self._dump_path = dump_path
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if self.debug and self._dump_file is None:
            path = self._dump_path or Path(os.environ.get("TEMP", "/tmp")) / "token-context-gui-stalls.log"
            self._dump_file = open(path, "a", encoding="utf-8")  # noqa: SIM115 - closed in stop()
        self._last = time.perf_counter()
        self._arm()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._dump_file is not None:
            faulthandler.cancel_dump_traceback_later()
            self._dump_file.close()
            self._dump_file = None

    @property
    def stall_count(self) -> int:
        return len(self.stalls_ms)

    def _arm(self) -> None:
        if self._dump_file is not None:
            faulthandler.dump_traceback_later((self.stall_ms + TICK_MS) / 1000, repeat=False, file=self._dump_file)

    def _tick(self) -> None:
        now = time.perf_counter()
        late_ms = (now - self._last) * 1000 - TICK_MS
        self._last = now
        if self._dump_file is not None:
            faulthandler.cancel_dump_traceback_later()
        if late_ms > self.stall_ms:
            self.stalls_ms.append(round(late_ms, 1))
            if self.debug:
                logger.warning("event loop blocked for %.0f ms (stack dump in the stall log)", late_ms)
        self._arm()
