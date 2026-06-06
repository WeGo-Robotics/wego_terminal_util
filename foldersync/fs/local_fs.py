"""Local filesystem backend."""

from __future__ import annotations

import os
import shutil
import stat as stat_mod
import subprocess
from typing import IO, Iterator, List, Optional, Tuple

from .base import FileEntry, FileStat, FileSystem


class LocalFileSystem(FileSystem):
    def __init__(self, root: str):
        self.root = os.path.abspath(os.path.expanduser(root))

    # ---- path mapping ----
    def _abs(self, relpath: str) -> str:
        # relpath is posix; convert to native separators.
        native = relpath.replace("/", os.sep)
        return os.path.join(self.root, native) if native else self.root

    def _rel(self, abspath: str) -> str:
        rel = os.path.relpath(abspath, self.root)
        return rel.replace(os.sep, "/")

    # ---- traversal ----
    def walk(self, subdir: str = "") -> Iterator[FileEntry]:
        start = self._abs(subdir)
        for dirpath, _dirnames, filenames in os.walk(start):
            for name in filenames:
                ap = os.path.join(dirpath, name)
                try:
                    st = os.stat(ap)
                except OSError:
                    continue
                yield FileEntry(
                    relpath=self._rel(ap),
                    stat=FileStat(is_dir=False, size=st.st_size, mtime=st.st_mtime),
                )

    def listdir(self, relpath: str = ""):
        out = []
        try:
            with os.scandir(self._abs(relpath)) as it:
                for e in it:
                    try:
                        is_dir = e.is_dir()
                    except OSError:
                        is_dir = False
                    out.append((e.name, is_dir))
        except OSError:
            return []
        return out

    def stat(self, relpath: str) -> Optional[FileStat]:
        try:
            st = os.stat(self._abs(relpath))
        except OSError:
            return None
        is_dir = stat_mod.S_ISDIR(st.st_mode)
        return FileStat(
            is_dir=is_dir,
            size=0 if is_dir else st.st_size,
            mtime=st.st_mtime,
        )

    # ---- io ----
    def open_read(self, relpath: str) -> IO[bytes]:
        return open(self._abs(relpath), "rb")

    def open_write(self, relpath: str) -> IO[bytes]:
        ap = self._abs(relpath)
        parent = os.path.dirname(ap)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return open(ap, "wb")

    def makedirs(self, relpath: str) -> None:
        os.makedirs(self._abs(relpath), exist_ok=True)

    def delete(self, relpath: str) -> None:
        ap = self._abs(relpath)
        if os.path.isdir(ap):
            shutil.rmtree(ap)
        elif os.path.exists(ap):
            os.remove(ap)

    # ---- commands ----
    def run_cmd(self, args: List[str], cwd: str = "") -> Tuple[int, str, str]:
        proc = subprocess.run(
            args,
            cwd=self._abs(cwd),
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout, proc.stderr

    # ---- label ----
    def label(self) -> str:
        return f"local: {self.root}"
