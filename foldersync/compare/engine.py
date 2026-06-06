"""Comparison engine: pair files by relpath and classify (size-then-hash)."""

from __future__ import annotations

import threading
from typing import Callable, Dict, Iterable, Optional

from ..fs.base import FileStat, FileSystem
from .result import ComparePair, CompareReport, DiffStatus

ProgressCb = Callable[[int, int, str], None]


class Cancelled(Exception):
    """Raised when a compare run is cancelled via the cancel event."""


class CompareEngine:
    def __init__(
        self,
        left_fs: FileSystem,
        right_fs: FileSystem,
        algo: str = "sha256",
        progress_cb: Optional[ProgressCb] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        self.left_fs = left_fs
        self.right_fs = right_fs
        self.algo = algo
        self.progress_cb = progress_cb
        self.cancel_event = cancel_event

    def compare(
        self,
        left_relpaths: Optional[Iterable[str]] = None,
        right_relpaths: Optional[Iterable[str]] = None,
    ) -> CompareReport:
        """Compare both trees.

        If relpath sets are given (git mode), restrict to those paths and
        ``stat()`` each; otherwise ``walk()`` the whole tree.
        """
        left_map = self._build_map(self.left_fs, left_relpaths)
        right_map = self._build_map(self.right_fs, right_relpaths)

        keys = sorted(set(left_map) | set(right_map))
        total = len(keys)
        report = CompareReport()

        for i, rel in enumerate(keys):
            self._check_cancel()
            if self.progress_cb:
                self.progress_cb(i, total, rel)

            lst = left_map.get(rel)
            rst = right_map.get(rel)

            if lst is not None and rst is None:
                status = DiffStatus.LEFT_ONLY
            elif lst is None and rst is not None:
                status = DiffStatus.RIGHT_ONLY
            else:
                status = self._classify_both(rel, lst, rst)

            report.pairs.append(ComparePair(rel, status, lst, rst))

        if self.progress_cb:
            self.progress_cb(total, total, "")
        return report

    def compare_oids(
        self,
        left_oids: Dict[str, str],
        right_oids: Dict[str, str],
    ) -> CompareReport:
        """Classify purely by git blob oid — no content reads.

        ``stat()`` is called only on non-identical files (for size display),
        which are few, keeping this fast even for huge trees.
        """
        keys = sorted(set(left_oids) | set(right_oids))
        total = len(keys)
        report = CompareReport()
        for i, rel in enumerate(keys):
            self._check_cancel()
            if self.progress_cb:
                self.progress_cb(i, total, rel)
            lo = left_oids.get(rel)
            ro = right_oids.get(rel)
            if lo is not None and ro is None:
                status = DiffStatus.LEFT_ONLY
            elif lo is None and ro is not None:
                status = DiffStatus.RIGHT_ONLY
            elif lo == ro:
                status = DiffStatus.SAME
            else:
                status = DiffStatus.DIFFERENT

            lst = rst = None
            if status is not DiffStatus.SAME:
                lst = self.left_fs.stat(rel) if lo is not None else None
                rst = self.right_fs.stat(rel) if ro is not None else None
            report.pairs.append(ComparePair(rel, status, lst, rst))

        if self.progress_cb:
            self.progress_cb(total, total, "")
        return report

    # ---- internals ----
    def _classify_both(self, rel: str, lst: FileStat, rst: FileStat) -> DiffStatus:
        # size first — short-circuits most differences without hashing
        if lst.size != rst.size:
            return DiffStatus.DIFFERENT
        # size tie -> compare content hash
        lh = self.left_fs.hash_file(rel, self.algo)
        self._check_cancel()
        rh = self.right_fs.hash_file(rel, self.algo)
        return DiffStatus.SAME if lh == rh else DiffStatus.DIFFERENT

    def _build_map(
        self, fs: FileSystem, relpaths: Optional[Iterable[str]]
    ) -> Dict[str, FileStat]:
        result: Dict[str, FileStat] = {}
        if relpaths is None:
            for entry in fs.walk():
                self._check_cancel()
                result[entry.relpath] = entry.stat
        else:
            for rel in relpaths:
                self._check_cancel()
                st = fs.stat(rel)
                if st is not None and not st.is_dir:
                    result[rel] = st
        return result

    def _check_cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise Cancelled()
