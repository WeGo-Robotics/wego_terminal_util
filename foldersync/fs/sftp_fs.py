"""SFTP/SSH filesystem backend (paramiko)."""

from __future__ import annotations

import posixpath
import stat as stat_mod
from typing import IO, Iterator, List, Optional, Tuple

import paramiko

from .base import FileEntry, FileStat, FileSystem
from .ssh_config import SourceSpec, build_ssh_client


class SftpFileSystem(FileSystem):
    def __init__(self, spec: SourceSpec):
        self.spec = spec
        self._client: paramiko.SSHClient = build_ssh_client(spec)
        self._sftp: paramiko.SFTPClient = self._client.open_sftp()
        # Normalize root (resolve ~, relative paths) on the remote side.
        try:
            self.root = self._sftp.normalize(spec.path or ".")
        except IOError:
            self.root = spec.path or "."
        self._has_sha256sum: Optional[bool] = None  # probed lazily

    # ---- path mapping ----
    def _abs(self, relpath: str) -> str:
        return posixpath.join(self.root, relpath) if relpath else self.root

    # ---- traversal ----
    def walk(self, subdir: str = "") -> Iterator[FileEntry]:
        stack = [subdir]
        while stack:
            cur = stack.pop()
            abs_cur = self._abs(cur)
            try:
                entries = self._sftp.listdir_attr(abs_cur)
            except IOError:
                continue
            for attr in entries:
                rel = posixpath.join(cur, attr.filename) if cur else attr.filename
                mode = attr.st_mode or 0
                if stat_mod.S_ISDIR(mode):
                    stack.append(rel)
                elif stat_mod.S_ISREG(mode):
                    yield FileEntry(
                        relpath=rel,
                        stat=FileStat(
                            is_dir=False,
                            size=attr.st_size or 0,
                            mtime=float(attr.st_mtime or 0),
                        ),
                    )
                # symlinks and other types are skipped

    def listdir(self, relpath: str = ""):
        out = []
        try:
            entries = self._sftp.listdir_attr(self._abs(relpath))
        except IOError:
            return []
        for attr in entries:
            out.append((attr.filename, stat_mod.S_ISDIR(attr.st_mode or 0)))
        return out

    def stat(self, relpath: str) -> Optional[FileStat]:
        try:
            attr = self._sftp.stat(self._abs(relpath))
        except IOError:
            return None
        mode = attr.st_mode or 0
        is_dir = stat_mod.S_ISDIR(mode)
        return FileStat(
            is_dir=is_dir,
            size=0 if is_dir else (attr.st_size or 0),
            mtime=float(attr.st_mtime or 0),
        )

    # ---- io ----
    def open_read(self, relpath: str) -> IO[bytes]:
        return self._sftp.open(self._abs(relpath), "rb")

    def open_write(self, relpath: str) -> IO[bytes]:
        parent = posixpath.dirname(relpath)
        if parent:
            self.makedirs(parent)
        return self._sftp.open(self._abs(relpath), "wb")

    def makedirs(self, relpath: str) -> None:
        parts = [p for p in relpath.split("/") if p]
        cur = ""
        for part in parts:
            cur = posixpath.join(cur, part) if cur else part
            abs_cur = self._abs(cur)
            try:
                self._sftp.stat(abs_cur)
            except IOError:
                try:
                    self._sftp.mkdir(abs_cur)
                except IOError:
                    pass  # racing or already exists

    def delete(self, relpath: str) -> None:
        abs_path = self._abs(relpath)
        try:
            attr = self._sftp.stat(abs_path)
        except IOError:
            return
        if stat_mod.S_ISDIR(attr.st_mode or 0):
            self._rmtree(relpath)
        else:
            self._sftp.remove(abs_path)

    def _rmtree(self, relpath: str) -> None:
        abs_path = self._abs(relpath)
        for attr in self._sftp.listdir_attr(abs_path):
            child = posixpath.join(relpath, attr.filename)
            if stat_mod.S_ISDIR(attr.st_mode or 0):
                self._rmtree(child)
            else:
                self._sftp.remove(self._abs(child))
        self._sftp.rmdir(abs_path)

    # ---- commands ----
    def run_cmd(self, args: List[str], cwd: str = "") -> Tuple[int, str, str]:
        quoted = " ".join(_shquote(a) for a in args)
        # Always cd into the target dir; cwd="" => root (matches LocalFileSystem,
        # whose run_cmd defaults to root). exec_command starts in the login home,
        # not self.root, so the cd is required for git to see the work tree.
        cmd = f"cd {_shquote(self._abs(cwd))} && {quoted}"
        stdin, stdout, stderr = self._client.exec_command(cmd)
        stdin.close()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err

    # ---- hashing ----
    def hash_file(self, relpath: str, algo: str = "sha256") -> str:
        if algo == "sha256" and self._sha256sum_available():
            rc, out, _err = self.run_cmd(["sha256sum", "--", self._abs(relpath)])
            if rc == 0 and out:
                return out.split()[0]
        # fall back to streamed read
        return super().hash_file(relpath, algo)

    def _sha256sum_available(self) -> bool:
        if self._has_sha256sum is None:
            rc, _out, _err = self.run_cmd(["command", "-v", "sha256sum"])
            self._has_sha256sum = rc == 0
        return self._has_sha256sum

    # ---- lifecycle ----
    def label(self) -> str:
        origin = self.spec.alias or f"{self.spec.user}@{self.spec.host}"
        return f"ssh {origin}:{self.root}"

    def close(self) -> None:
        try:
            self._sftp.close()
        finally:
            self._client.close()


def _shquote(s: str) -> str:
    """POSIX single-quote a shell argument."""
    if s and all(c.isalnum() or c in "@%_-+=:,./" for c in s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"
