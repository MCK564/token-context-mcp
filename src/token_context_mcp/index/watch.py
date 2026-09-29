"""``token-context index --watch`` (M7.10): re-index after the working tree settles.

A change opens a debounce window (default 1.5 s); every further change restarts it, and the incremental index
runs once the tree has been quiet for the whole window.  The change source is ``watchdog`` when it is installed
(an optional extra) and a cheap ``(path, size, mtime_ns)`` poll every 2 s otherwise.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from token_context_mcp.index.runner import _inventory, build_index
from token_context_mcp.models import RepositoryConfig
from token_context_mcp.security.content_policy import is_hard_denied
from token_context_mcp.security.path_policy import relative_posix

DEFAULT_DEBOUNCE_SECONDS = 1.5
DEFAULT_POLL_SECONDS = 2.0


def tree_signature(repository: RepositoryConfig) -> str:
    """Fingerprint of everything an index run would look at: paths, sizes and mtimes (no file is read)."""
    digest = hashlib.sha256()
    for path in _inventory(repository):
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(f"{relative_posix(repository.root, path)}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


class _PollSource:
    """Reports "something changed" by comparing tree signatures."""

    def __init__(self, repository: RepositoryConfig) -> None:
        self._repository = repository
        self._last = tree_signature(repository)

    def changed(self) -> bool:
        current = tree_signature(self._repository)
        if current != self._last:
            self._last = current
            return True
        return False

    def close(self) -> None:
        pass


class _WatchdogSource:  # pragma: no cover - only exercised where watchdog is installed
    def __init__(self, repository: RepositoryConfig, ignore: list[Path]) -> None:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        self._dirty = threading.Event()
        root = repository.root
        ignored = [item.resolve() for item in ignore]
        outer = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event: Any) -> None:  # noqa: ANN401
                path = Path(getattr(event, "src_path", "") or "")
                try:
                    if any(path.resolve().is_relative_to(item) for item in ignored):
                        return
                    if is_hard_denied(relative_posix(root, path)):
                        return
                except (ValueError, OSError):
                    pass
                outer._dirty.set()

        self._observer = Observer()
        self._observer.schedule(Handler(), str(root), recursive=True)
        self._observer.start()

    def changed(self) -> bool:
        if self._dirty.is_set():
            self._dirty.clear()
            return True
        return False

    def close(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=2)


def watchdog_available() -> bool:
    try:
        import watchdog.observers  # noqa: F401
    except ImportError:
        return False
    return True


def watch_index(
    repository: RepositoryConfig,
    index_directory: Path,
    *,
    network_policy: str,
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    stop: threading.Event | None = None,
    on_index: Callable[[dict[str, Any]], None] | None = None,
    use_watchdog: bool | None = None,
    index_kwargs: dict[str, Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Index once, then re-index whenever the tree changes and settles.  Returns the number of index runs."""
    stop = stop or threading.Event()
    kwargs = dict(index_kwargs or {})
    runs = 0

    def run() -> None:
        nonlocal runs
        manifest = build_index(repository, index_directory, network_policy=network_policy, **kwargs)
        runs += 1
        if on_index is not None:
            on_index(manifest)

    run()
    if use_watchdog is None:
        use_watchdog = watchdog_available()
    source: Any = _WatchdogSource(repository, [index_directory]) if use_watchdog else _PollSource(repository)
    tick = min(poll_seconds, 0.25) if use_watchdog else poll_seconds
    last_change: float | None = None
    try:
        while not stop.is_set():
            if stop.wait(tick):
                break
            if source.changed():
                last_change = clock()  # every change restarts the window
                continue
            if last_change is not None and clock() - last_change >= debounce_seconds:
                last_change = None
                run()
                source.changed()  # the index run itself may have touched files (e.g. mtimes of the index dir)
    finally:
        source.close()
    return runs
