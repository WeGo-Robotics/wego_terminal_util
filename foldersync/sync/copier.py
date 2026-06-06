"""Sync copier: stream a file from one FileSystem to another, any direction."""

from __future__ import annotations

import shutil
from typing import Callable, Optional

from ..fs.base import CHUNK, FileSystem


class SyncCopier:
    def __init__(self, progress_cb: Optional[Callable[[str, int, int], None]] = None):
        # progress_cb(relpath, copied_bytes, total_bytes)
        self.progress_cb = progress_cb

    def copy(
        self,
        src_fs: FileSystem,
        dst_fs: FileSystem,
        relpath: str,
        overwrite: bool = True,
    ) -> None:
        st = src_fs.stat(relpath)
        if st is None:
            raise FileNotFoundError(f"source missing: {relpath}")
        if st.is_dir:
            dst_fs.makedirs(relpath)
            return

        parent = dst_fs.parent(relpath)
        if parent:
            dst_fs.makedirs(parent)

        if not overwrite and dst_fs.stat(relpath) is not None:
            return

        total = st.size
        copied = 0
        with src_fs.open_read(relpath) as r, dst_fs.open_write(relpath) as w:
            if self.progress_cb is None:
                shutil.copyfileobj(r, w, CHUNK)
            else:
                while True:
                    block = r.read(CHUNK)
                    if not block:
                        break
                    w.write(block)
                    copied += len(block)
                    self.progress_cb(relpath, copied, total)
