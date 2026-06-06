"""FileSystem abstraction layer.

The keystone of foldersync. Everything above (compare, gitscope, sync) is
written against the ``FileSystem`` interface and never knows whether a pane is
local or remote.

Convention: every ``relpath`` is POSIX-style ("/" separators), relative to the
filesystem's ``root``. The local backend converts to ``os.sep`` internally, so
a Windows local pane and a Linux remote pane pair correctly by relpath.
"""

from __future__ import annotations

import hashlib
import posixpath
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import IO, Iterator, List, Optional, Tuple

# Chunk size for streamed reads/copies/hashes.
CHUNK = 1 << 20  # 1 MiB


@dataclass(frozen=True)
class FileStat:
    is_dir: bool
    size: int       # bytes (0 for dirs)
    mtime: float    # epoch seconds; advisory only, NOT a diff criterion


@dataclass(frozen=True)
class FileEntry:
    relpath: str    # posix-style, relative to the compare root
    stat: FileStat


class FileSystem(ABC):
    """Unified interface; ``relpath`` is always posix, relative to ``root``."""

    root: str

    # ---- traversal ----------------------------------------------------
    @abstractmethod
    def walk(self, subdir: str = "") -> Iterator[FileEntry]:
        """Recursively yield FileEntry for every regular file under subdir."""

    @abstractmethod
    def stat(self, relpath: str) -> Optional[FileStat]:
        """Return FileStat, or None if the path does not exist."""

    @abstractmethod
    def listdir(self, relpath: str = "") -> List[Tuple[str, bool]]:
        """List one directory level: [(name, is_dir), ...]. Empty on error."""

    # ---- io -----------------------------------------------------------
    @abstractmethod
    def open_read(self, relpath: str) -> IO[bytes]:
        """Open a binary file-like for reading."""

    @abstractmethod
    def open_write(self, relpath: str) -> IO[bytes]:
        """Open a binary file-like for writing, creating parent dirs."""

    @abstractmethod
    def makedirs(self, relpath: str) -> None:
        """Create directory and any missing parents; no error if it exists."""

    @abstractmethod
    def delete(self, relpath: str) -> None:
        """Remove a file or directory tree."""

    # ---- commands -----------------------------------------------------
    @abstractmethod
    def run_cmd(self, args: List[str], cwd: str = "") -> Tuple[int, str, str]:
        """Run a command; return (returncode, stdout, stderr).

        Local backend uses subprocess; SFTP backend uses ssh exec. ``cwd`` is a
        relpath under root. Used by the git scope resolver.
        """

    # ---- hashing (overridable) ---------------------------------------
    def hash_file(self, relpath: str, algo: str = "sha256") -> str:
        """Hash a file by streaming its bytes. Backends may override for speed."""
        h = hashlib.new(algo)
        with self.open_read(relpath) as f:
            while True:
                block = f.read(CHUNK)
                if not block:
                    break
                h.update(block)
        return h.hexdigest()

    # ---- helpers (concrete) ------------------------------------------
    @staticmethod
    def join(*parts: str) -> str:
        """Posix-join relpath parts, dropping empties."""
        return posixpath.join(*[p for p in parts if p])

    @staticmethod
    def parent(relpath: str) -> str:
        return posixpath.dirname(relpath)

    def label(self) -> str:
        """Human-readable description of this source (overridable)."""
        return self.root

    def close(self) -> None:
        """Release resources. Default no-op; SFTP closes channels."""
