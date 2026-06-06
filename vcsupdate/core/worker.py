"""Background worker thread + result message types.

Tk is single-threaded and remote SSH commands are slow/blocking, so all remote
work runs on one long-lived worker thread. Results are posted to a thread-safe
queue that the Tk side drains via ``root.after`` (same pattern as
foldersync/core/worker.py).
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, List, Optional


# ---- result messages (worker -> Tk) ----
@dataclass
class LogLine:
    text: str
    stream: str = "out"  # "out" | "err" | "info"


@dataclass
class Connected:
    host: str
    cred_ok: bool          # True if the git key was loaded + injected into robot RAM
    detail: str = ""       # key fingerprint on success, error message on failure


@dataclass
class RepoList:
    root: Any  # RepoNode (vcsupdate.core.repolist) — merged tree model


@dataclass
class RepoUpdated:
    path: str
    node: Any  # RepoNode — refreshed single-repo state


@dataclass
class TaskDone:
    name: str
    exit_code: int


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

    def __init__(self) -> None:
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
