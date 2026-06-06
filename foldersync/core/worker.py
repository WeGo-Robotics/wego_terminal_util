"""Background worker thread + result message types.

Tk is single-threaded and SFTP list/hash/copy are slow, so all heavy work runs
on one long-lived worker thread. Results are posted to a thread-safe queue that
the Tk side drains via ``root.after``.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---- result messages (worker -> Tk) ----
@dataclass
class Progress:
    done: int
    total: int
    msg: str = ""


@dataclass
class CompareDone:
    report: Any  # CompareReport


@dataclass
class CopyDone:
    relpath: str
    direction: str
    ok: bool = True


@dataclass
class Connected:
    side: str         # "left" | "right"
    fs: Any           # FileSystem
    label: str = ""


@dataclass
class Error:
    message: str
    context: str = ""


@dataclass
class _Task:
    fn: Callable[["WorkerThread"], None]
    name: str = ""


class WorkerThread(threading.Thread):
    """Consumes tasks serially; tasks push messages onto ``results``."""

    def __init__(self):
        super().__init__(daemon=True)
        self._tasks: "queue.Queue[Optional[_Task]]" = queue.Queue()
        self.results: "queue.Queue[Any]" = queue.Queue()
        self.cancel_event = threading.Event()
        self._stop = False

    def submit(self, fn: Callable[["WorkerThread"], None], name: str = "") -> None:
        """Queue a task. ``fn`` receives this worker (for ``self.cancel_event``)."""
        self.cancel_event.clear()
        self._tasks.put(_Task(fn, name))

    def cancel(self) -> None:
        self.cancel_event.set()

    def post(self, msg: Any) -> None:
        self.results.put(msg)

    def shutdown(self) -> None:
        self._stop = True
        self._tasks.put(None)

    def run(self) -> None:
        while not self._stop:
            task = self._tasks.get()
            if task is None:
                break
            try:
                task.fn(self)
            except Exception as exc:  # noqa: BLE001 - surface to UI
                self.post(Error(message=str(exc), context=task.name))
