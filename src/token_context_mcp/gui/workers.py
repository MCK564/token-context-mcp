"""Run blocking work off the UI thread (M8.1).

``run_async(fn, *args, on_ok=..., on_err=...)`` executes ``fn`` on ``QThreadPool.globalInstance()`` (at most four
threads) and delivers the result to ``on_ok`` / ``on_err`` **on the thread that called run_async** (the UI thread),
through a queued signal.  ``fn`` must not touch widgets; give it plain values.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThread, QThreadPool, Signal, Slot

logger = logging.getLogger("token_context_mcp.gui.workers")

MAX_WORKER_THREADS = 4

_pending = 0
_live: set[_Signals] = set()


def is_ui_thread() -> bool:
    """True on the thread that owns the QApplication (where widgets live)."""
    app = QCoreApplication.instance()
    return app is not None and QThread.currentThread() is app.thread()


class _Signals(QObject):
    ok = Signal(object)
    err = Signal(object)

    def __init__(self, on_ok: Callable[[Any], None] | None, on_err: Callable[[BaseException], None] | None) -> None:
        super().__init__()
        self._on_ok = on_ok
        self._on_err = on_err
        # receivers are bound methods of this object (which lives on the UI thread): the emit from a worker
        # thread is therefore queued to the UI thread
        self.ok.connect(self._deliver_ok)
        self.err.connect(self._deliver_err)

    def _finish(self) -> None:
        global _pending
        _pending -= 1
        _live.discard(self)
        self.deleteLater()

    @Slot(object)
    def _deliver_ok(self, result: Any) -> None:
        try:
            if self._on_ok is not None:
                self._on_ok(result)
        except Exception:  # a broken render must not kill the event loop
            logger.exception("run_async on_ok callback failed")
        finally:
            self._finish()

    @Slot(object)
    def _deliver_err(self, error: BaseException) -> None:
        try:
            if self._on_err is not None:
                self._on_err(error)
            else:
                logger.error("background task failed: %r", error)
        except Exception:
            logger.exception("run_async on_err callback failed")
        finally:
            self._finish()


class _Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any], signals: _Signals) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except BaseException as exc:  # noqa: BLE001 - reported to on_err
            self._signals.err.emit(exc)
        else:
            self._signals.ok.emit(result)


def run_async(
    fn: Callable[..., Any],
    *args: Any,
    on_ok: Callable[[Any], None] | None = None,
    on_err: Callable[[BaseException], None] | None = None,
    **kwargs: Any,
) -> None:
    """Run ``fn(*args, **kwargs)`` in the global pool; call ``on_ok(result)`` or ``on_err(exc)`` on the UI thread."""
    global _pending
    pool = QThreadPool.globalInstance()
    if pool.maxThreadCount() != MAX_WORKER_THREADS:
        pool.setMaxThreadCount(MAX_WORKER_THREADS)
    signals = _Signals(on_ok, on_err)
    _live.add(signals)
    _pending += 1
    pool.start(_Task(fn, args, kwargs, signals))


def pending_count() -> int:
    """Tasks started with run_async whose callback has not run yet."""
    return _pending


def wait_idle(timeout_ms: int = 10_000) -> bool:
    """Pump the event loop until every run_async task has delivered its callback (tests, scripts).

    Zero-delay timers and callbacks may start more tasks, so idle means "no pending task after two event passes".
    """
    deadline = time.monotonic() + timeout_ms / 1000
    app = QCoreApplication.instance()
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if _pending == 0:
            if app is not None:
                app.processEvents()
                time.sleep(0.01)
                app.processEvents()
            if _pending == 0:
                return True
        time.sleep(0.005)
    return _pending == 0
