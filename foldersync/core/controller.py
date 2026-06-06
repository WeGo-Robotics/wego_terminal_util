"""Controller: orchestrates fs / compare / gitscope / sync on the worker thread.

The UI calls only these methods; everything heavy is enqueued and replies come
back as messages on ``worker.results``.
"""

from __future__ import annotations

from typing import Optional

from ..compare.engine import Cancelled, CompareEngine
from ..fs.base import FileSystem
from ..fs.local_fs import LocalFileSystem
from ..fs.sftp_fs import SftpFileSystem
from ..fs.ssh_config import SourceSpec
from ..gitscope.resolver import GitNotAvailable, GitScopeResolver
from ..sync.copier import SyncCopier
from .worker import (
    CompareDone,
    Connected,
    CopyDone,
    Error,
    Progress,
    WorkerThread,
)


def build_fs(spec: SourceSpec) -> FileSystem:
    if spec.kind == "local":
        return LocalFileSystem(spec.path)
    if spec.kind == "ssh":
        return SftpFileSystem(spec)
    raise ValueError(f"unknown source kind: {spec.kind}")


class Controller:
    def __init__(self, worker: WorkerThread):
        self.worker = worker
        self.left_fs: Optional[FileSystem] = None
        self.right_fs: Optional[FileSystem] = None
        self.algo = "sha256"

    # ---- connect ----
    def connect(self, side: str, spec: SourceSpec) -> None:
        def task(w: WorkerThread) -> None:
            w.post(Progress(0, 0, f"connecting {side}…"))
            fs = build_fs(spec)
            # touch root so we fail fast if it is unreachable
            fs.stat("")
            self._set_fs(side, fs)
            w.post(Connected(side=side, fs=fs, label=fs.label()))

        self.worker.submit(task, name=f"connect {side}")

    def _set_fs(self, side: str, fs: FileSystem) -> None:
        old = self.left_fs if side == "left" else self.right_fs
        if old is not None and old is not fs:
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
        if side == "left":
            self.left_fs = fs
        else:
            self.right_fs = fs

    # ---- compare ----
    def compare(self, git_mode: bool) -> None:
        if self.left_fs is None or self.right_fs is None:
            self.worker.post(Error("Both sources must be set before comparing."))
            return

        left_fs, right_fs = self.left_fs, self.right_fs

        def task(w: WorkerThread) -> None:
            engine = CompareEngine(
                left_fs,
                right_fs,
                algo=self.algo,
                progress_cb=lambda d, t, m: w.post(
                    Progress(d, t, f"Comparing {m}" if m else "Comparing…")
                ),
                cancel_event=w.cancel_event,
            )
            try:
                if git_mode:
                    # Fast path: compare git blob oids — no content hashing.
                    w.post(Progress(0, 0, "Reading git oids (left & right)…"))
                    try:
                        left_oids = GitScopeResolver(left_fs).resolve_oids()
                        right_oids = GitScopeResolver(right_fs).resolve_oids()
                    except GitNotAvailable as exc:
                        w.post(Error(str(exc), context="git scope"))
                        return
                    report = engine.compare_oids(left_oids, right_oids)
                else:
                    report = engine.compare()
            except Cancelled:
                w.post(Progress(0, 0, "cancelled"))
                return
            w.post(CompareDone(report=report))

        self.worker.submit(task, name="compare")

    # ---- copy ----
    def copy(self, relpath: str, direction: str) -> None:
        """direction: 'l2r' (left->right) or 'r2l' (right->left)."""
        if self.left_fs is None or self.right_fs is None:
            self.worker.post(Error("Both sources must be set before copying."))
            return
        if direction == "l2r":
            src, dst = self.left_fs, self.right_fs
        elif direction == "r2l":
            src, dst = self.right_fs, self.left_fs
        else:
            self.worker.post(Error(f"unknown direction: {direction}"))
            return

        def task(w: WorkerThread) -> None:
            copier = SyncCopier(
                progress_cb=lambda rel, c, t: w.post(Progress(c, t, f"Copying {rel}"))
            )
            copier.copy(src, dst, relpath)
            w.post(CopyDone(relpath=relpath, direction=direction, ok=True))

        self.worker.submit(task, name=f"copy {direction} {relpath}")

    # ---- batch copy ----
    def copy_many(self, items) -> None:
        """items: iterable of (relpath, direction)."""
        if self.left_fs is None or self.right_fs is None:
            self.worker.post(Error("Both sources must be set before copying."))
            return
        left_fs, right_fs = self.left_fs, self.right_fs
        items = list(items)

        def task(w: WorkerThread) -> None:
            copier = SyncCopier()
            total = len(items)
            for i, (relpath, direction) in enumerate(items):
                if w.cancel_event.is_set():
                    w.post(Progress(0, 0, "cancelled"))
                    return
                arrow = "→" if direction == "l2r" else "←"
                w.post(Progress(i, total, f"Copying {arrow} {relpath}"))
                src, dst = (
                    (left_fs, right_fs) if direction == "l2r" else (right_fs, left_fs)
                )
                copier.copy(src, dst, relpath)
                w.post(CopyDone(relpath=relpath, direction=direction, ok=True))
            w.post(Progress(total, total, f"Copied {total} file(s)"))

        self.worker.submit(task, name="copy_many")

    def cancel(self) -> None:
        self.worker.cancel()

    def close(self) -> None:
        for fs in (self.left_fs, self.right_fs):
            if fs is not None:
                try:
                    fs.close()
                except Exception:  # noqa: BLE001
                    pass
